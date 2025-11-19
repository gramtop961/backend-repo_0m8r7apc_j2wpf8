"""
Database Schemas for Personal Finance Tracker

Each Pydantic model corresponds to a MongoDB collection.
Collection name is the lowercase of the class name.
"""
from pydantic import BaseModel, Field
from typing import Optional, Literal, List
from datetime import datetime

CategoryLiteral = Literal["Food", "Bills", "Transport", "Shopping", "Savings", "Other"]
TypeLiteral = Literal["income", "expense"]

DEFAULT_CATEGORIES = ["Food", "Bills", "Transport", "Shopping", "Savings", "Other"]

class Transaction(BaseModel):
    """
    Transactions collection schema
    Collection name: "transaction"
    """
    title: str = Field(..., description="Short label for the transaction")
    amount: float = Field(..., gt=0, description="Positive amount in your currency")
    type: TypeLiteral = Field(..., description="income or expense")
    category: CategoryLiteral = Field(..., description="Transaction category")
    date: datetime = Field(default_factory=datetime.utcnow, description="Transaction date/time (UTC)")
    notes: Optional[str] = Field(None, description="Optional notes")

class Budget(BaseModel):
    """
    Monthly budget settings
    Collection name: "budget"
    """
    month: str = Field(..., description="Month key in format YYYY-MM")
    amount: float = Field(..., gt=0, description="Monthly budget amount")

class Profile(BaseModel):
    """
    Simple user profile
    Collection name: "profile"
    """
    name: str = Field("You", description="Display name")
    currency: str = Field("$", description="Currency symbol")
    dark_mode: bool = Field(False, description="Preferred dark mode")
    categories: List[str] = Field(default_factory=lambda: DEFAULT_CATEGORIES.copy(), description="Preferred categories")
    onboarded: bool = Field(False, description="Whether onboarding is completed")
