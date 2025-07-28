# main.py

import enum
from typing import List, Optional

from fastapi import Depends, FastAPI, HTTPException, Request
from pydantic import BaseModel
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.util import get_remote_address
from sqlmodel import Field, Session, SQLModel, create_engine, select
from sqlalchemy import JSON, Column

# --- 1. Rate Limiter Setup ---
limiter = Limiter(key_func=get_remote_address)

# --- 2. API Application Setup ---
app = FastAPI(
    title="Dune: Awakening Crafting API",
    description="A lightweight API for all craftable items, including buildings and vehicles.",
    version="1.2.1" # NEW: Version bump for logic change
)
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

# --- 3. Database Setup ---
sqlite_file_name = "dune_crafting.db"
sqlite_url = f"sqlite:///{sqlite_file_name}"
engine = create_engine(sqlite_url, connect_args={"check_same_thread": False})

def create_db_and_tables():
    SQLModel.metadata.create_all(engine)

# --- 4. Data Models ---
class CraftingMaterial(BaseModel):
    item_name: str
    quantity: int

class ItemType(str, enum.Enum):
    WEAPON = "Weapon"
    ARMOR = "Armor"
    TOOL = "Tool"
    COMPONENT = "Component"
    CONSUMABLE = "Consumable"
    BUILDING = "Building"
    VEHICLE = "Vehicle"

class Item(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    name: str = Field(index=True, unique=True)
    description: str
    item_type: ItemType
    power_consumption: int = Field(default=0)
    power_generation: int = Field(default=0)
    crafting_materials: List[CraftingMaterial] = Field(sa_column=Column(JSON))

class ItemResponse(BaseModel):
    id: int
    name: str
    description: str
    item_type: ItemType
    power_consumption: int
    power_generation: int
    crafting_materials: List[CraftingMaterial]
    deep_desert_materials: List[CraftingMaterial]

# --- 5. Database Session Dependency ---
def get_db():
    with Session(engine) as session:
        yield session

# --- 6. API Startup Event ---
@app.on_event("startup")
def on_startup():
    """
    This function runs when the API starts. It creates the database and tables,
    then checks if the database is empty. If it is, it populates it with data
    from the items_data.json file.
    """
    create_db_and_tables()

    with Session(engine) as session:
        # Check if the database already has data. If so, do nothing.
        if session.exec(select(Item)).first():
            return

        # If the database is empty, open and read the JSON data file.
        with open("items_data.json", "r") as f:
            items_data = json.load(f)

            # Iterate through the data and create Item objects
            for item_data in items_data:
                # Use ** to unpack the dictionary directly into the model
                item = Item(**item_data)
                session.add(item)
            
            # Commit all the new items to the database in one transaction
            session.commit()

# --- 7. API Endpoints ---

# NEW: Helper function to keep our code DRY (Don't Repeat Yourself)
def create_item_response(db_item: Item) -> ItemResponse:
    """Converts a database Item object to an ItemResponse with calculated costs."""
    # Calculate Deep Desert materials with rounding up
    dd_materials = [
        CraftingMaterial(
            item_name=mat['item_name'],
            # THE FIX: This logic now rounds up to the nearest whole number.
            quantity=(mat['quantity'] + 1) // 2
        )
        for mat in db_item.crafting_materials
    ]
    
    # Create the final response object
    return ItemResponse(
        **db_item.dict(),
        deep_desert_materials=dd_materials
    )

@app.get("/", summary="Root Welcome Message")
def read_root():
    return {"message": "Welcome to the Dune: Awakening Crafting API!"}

@app.get("/api/v1/items", response_model=List[ItemResponse], summary="Get All Craftable Items")
@limiter.limit("20/minute")
def get_all_items(request: Request, db: Session = Depends(get_db)):
    """Returns a list of all craftable items, including calculated Deep Desert costs."""
    items_from_db = db.exec(select(Item)).all()
    # NEW: Use the helper function for a clean, single line of code.
    return [create_item_response(db_item) for db_item in items_from_db]

@app.get("/api/v1/items/{item_id}", response_model=ItemResponse, summary="Get Item by ID")
@limiter.limit("60/minute")
def get_item_by_id(request: Request, item_id: int, db: Session = Depends(get_db)):
    """Returns a single item, including calculated Deep Desert costs."""
    db_item = db.get(Item, item_id)
    if not db_item:
        raise HTTPException(status_code=404, detail=f"Item with ID {item_id} not found")
    # NEW: Use the helper function to create the response.
    return create_item_response(db_item)

@app.get("/api/v1/items/search/", response_model=List[ItemResponse], summary="Search for Items by Name")
@limiter.limit("10/minute")
def search_items_by_name(request: Request, name: str, db: Session = Depends(get_db)):
    """Searches for items and returns them with calculated Deep Desert costs."""
    statement = select(Item).where(Item.name.ilike(f"%{name}%"))
    results_from_db = db.exec(statement).all()
    if not results_from_db:
        raise HTTPException(status_code=404, detail=f"No items found with the name '{name}'")
    # NEW: Use the helper function here as well.
    return [create_item_response(db_item) for db_item in results_from_db]