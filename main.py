# main.py

import enum
import json
import os
import uvicorn
from contextlib import asynccontextmanager
from typing import List, Optional

from fastapi import Depends, FastAPI, HTTPException, Request
from pydantic import BaseModel
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.util import get_remote_address
from sqlmodel import Field, Session, SQLModel, create_engine, select
from sqlalchemy import JSON, Column

# --- Lifespan Manager Function ---
@asynccontextmanager
async def lifespan(app: FastAPI):
    """Handles application startup and shutdown events."""
    print("Lifespan event: Application startup...")
    create_db_and_tables()
    with Session(engine) as session:
        if not session.exec(select(Item)).first():
            print("Database is empty, populating...")
            try:
                with open("items_data.json", "r") as f:
                    items_data = json.load(f)
                    for item_data in items_data:
                        session.add(Item(**item_data))
                    session.commit()
                print("Database populated successfully.")
            except FileNotFoundError:
                print("Warning: items_data.json not found. Database will be empty.")
            except Exception as e:
                print(f"An error occurred while populating the database: {e}")
    yield
    print("Lifespan event: Application shutdown.")


# --- API Application Setup ---
app = FastAPI(
    title="Dune: Awakening Crafting API",
    description="A lightweight API for all craftable items, including buildings and vehicles.",
    version="1.5.1", # Final, working version
    lifespan=lifespan
)

# --- Rate Limiter Setup ---
limiter = Limiter(key_func=get_remote_address)
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

# --- Database Setup ---
sqlite_file_name = "dune_crafting.db"
sqlite_url = f"sqlite:///{sqlite_file_name}"
engine = create_engine(sqlite_url, connect_args={"check_same_thread": False})

def create_db_and_tables():
    SQLModel.metadata.create_all(engine)

# --- Data Models ---
class CraftingMaterial(BaseModel):
    item_name: str
    quantity: int

class ItemType(str, enum.Enum):
    WEAPON = "Weapon"; ARMOR = "Armor"; TOOL = "Tool"; COMPONENT = "Component"
    CONSUMABLE = "Consumable"; BUILDING = "Building"; VEHICLE = "Vehicle"

class Item(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    name: str = Field(index=True, unique=True)
    description: str
    item_type: ItemType
    power_consumption: int = Field(default=0)
    power_generation: int = Field(default=0)
    crafting_materials: List[CraftingMaterial] = Field(sa_column=Column(JSON))

class ItemResponse(BaseModel):
    id: int; name: str; description: str; item_type: ItemType
    power_consumption: int; power_generation: int
    crafting_materials: List[CraftingMaterial]
    deep_desert_materials: List[CraftingMaterial]

# --- Database Session Dependency ---
def get_db():
    with Session(engine) as session:
        yield session

# --- API Endpoints Helper ---
def create_item_response(db_item: Item) -> ItemResponse:
    dd_materials = [
        CraftingMaterial(item_name=mat['item_name'], quantity=(mat['quantity'] + 1) // 2)
        for mat in db_item.crafting_materials
    ]
    return ItemResponse(**db_item.dict(), deep_desert_materials=dd_materials)

# --- API Endpoints ---
@app.get("/", summary="Root Welcome Message")
def read_root():
    return {"message": "Welcome to the Dune: Awakening Crafting API!"}

@app.get("/api/v1/items", response_model=List[ItemResponse], summary="Get All Craftable Items")
@limiter.limit("20/minute")
def get_all_items(request: Request, db: Session = Depends(get_db)):
    return [create_item_response(db_item) for db_item in db.exec(select(Item)).all()]

@app.get("/api/v1/items/{item_id}", response_model=ItemResponse, summary="Get Item by ID")
@limiter.limit("60/minute")
def get_item_by_id(request: Request, item_id: int, db: Session = Depends(get_db)):
    db_item = db.get(Item, item_id)
    if not db_item:
        raise HTTPException(status_code=404, detail=f"Item with ID {item_id} not found")
    return create_item_response(db_item)

@app.get("/api/v1/items/search/", response_model=List[ItemResponse], summary="Search for Items by Name")
@limiter.limit("10/minute")
def search_items_by_name(request: Request, name: str, db: Session = Depends(get_db)):
    results = db.exec(select(Item).where(Item.name.ilike(f"%{name}%"))).all()
    if not results:
        raise HTTPException(status_code=404, detail=f"No items found with the name '{name}'")
    return [create_item_response(db_item) for db_item in results]

# --- Uvicorn Server Runner for Production ---
if __name__ == "__main__":
    """
    This block is for running the app in a production environment (e.g., on Render).
    It runs the `app` object directly, which prevents the double-import error.
    """
    port = int(os.environ.get("PORT", 8000))
    # THE FIX: Pass the `app` object, NOT the import string "main:app".
    uvicorn.run(app, host="0.0.0.0", port=port, reload=False)
