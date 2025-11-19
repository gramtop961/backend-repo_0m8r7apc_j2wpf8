import os
from datetime import datetime
from typing import List, Optional

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from database import db, create_document, get_documents
from schemas import Transaction, Budget, Profile, DEFAULT_CATEGORIES

app = FastAPI(title="Personal Finance Tracker API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.get("/")
def read_root():
    return {"message": "Finance Tracker Backend Running"}

@app.get("/test")
def test_database():
    """Verify database connectivity and show collections"""
    status = {
        "backend": "✅ Running",
        "database": "❌ Not Connected",
        "collections": [],
    }
    try:
        if db is None:
            status["database"] = "❌ Not Configured"
        else:
            status["database"] = "✅ Connected"
            status["collections"] = db.list_collection_names()
    except Exception as e:
        status["database"] = f"⚠️ {str(e)[:80]}"
    return status

# ---------------- Sample Data Bootstrap -----------------
class SampleBootstrap(BaseModel):
    create: bool = True

@app.post("/bootstrap")
def bootstrap_sample_data(_: SampleBootstrap):
    """Insert a small set of sample transactions and a budget for the current month."""
    if db is None:
        raise HTTPException(status_code=500, detail="Database not configured")

    # Only add if empty
    if db["transaction"].count_documents({}) == 0:
        sample_items = [
            {"title": "Groceries", "amount": 42.5, "type": "expense", "category": "Food"},
            {"title": "Salary", "amount": 1800, "type": "income", "category": "Other"},
            {"title": "Metro", "amount": 3.2, "type": "expense", "category": "Transport"},
            {"title": "Electric Bill", "amount": 65, "type": "expense", "category": "Bills"},
            {"title": "Coffee", "amount": 4.1, "type": "expense", "category": "Food"},
        ]
        for it in sample_items:
            create_document("transaction", Transaction(**it))

    # Set a budget for this month if missing
    now = datetime.utcnow()
    month_key = f"{now.year:04d}-{now.month:02d}"
    if db["budget"].count_documents({"month": month_key}) == 0:
        create_document("budget", Budget(month=month_key, amount=1200))

    # Simple profile
    if db["profile"].count_documents({}) == 0:
        create_document("profile", Profile())

    return {"status": "ok"}

# ---------------- Profile & Onboarding -----------------
class ProfileUpdate(BaseModel):
    name: Optional[str] = None
    currency: Optional[str] = None
    dark_mode: Optional[bool] = None
    categories: Optional[List[str]] = None
    onboarded: Optional[bool] = None

class OnboardingPayload(BaseModel):
    currency: str
    target: float
    categories: Optional[List[str]] = None

@app.get("/profile")
def get_profile():
    if db is None:
        raise HTTPException(status_code=500, detail="Database not configured")
    prof = db["profile"].find_one({})
    if not prof:
        # create default profile
        create_document("profile", Profile())
        prof = db["profile"].find_one({})
    prof["id"] = str(prof.pop("_id")) if prof.get("_id") else None
    # ensure categories
    if not prof.get("categories"):
        prof["categories"] = DEFAULT_CATEGORIES
    return prof

@app.post("/profile")
def update_profile(payload: ProfileUpdate):
    if db is None:
        raise HTTPException(status_code=500, detail="Database not configured")
    update = {k: v for k, v in payload.model_dump(exclude_none=True).items()}
    if not update:
        return {"status": "noop"}
    db["profile"].update_one({}, {"$set": update}, upsert=True)
    return {"status": "ok"}

@app.post("/onboarding")
def complete_onboarding(payload: OnboardingPayload):
    if db is None:
        raise HTTPException(status_code=500, detail="Database not configured")
    # Update profile
    update = {
        "currency": payload.currency,
        "onboarded": True,
    }
    if payload.categories:
        update["categories"] = payload.categories
    db["profile"].update_one({}, {"$set": update}, upsert=True)
    # Set budget (monthly target)
    now = datetime.utcnow()
    month_key = f"{now.year:04d}-{now.month:02d}"
    db["budget"].update_one(
        {"month": month_key},
        {"$set": {"month": month_key, "amount": float(payload.target), "updated_at": datetime.utcnow()}},
        upsert=True,
    )
    return {"status": "ok"}

# ---------------- Finance Endpoints -----------------
@app.get("/summary")
def get_summary(month: Optional[str] = Query(None, description="YYYY-MM")):
    """Return current balance, monthly spending, and budget progress."""
    if db is None:
        raise HTTPException(status_code=500, detail="Database not configured")

    # Current balance = sum(income) - sum(expense) across all time
    txs = get_documents("transaction")
    income = sum(t.get("amount", 0) for t in txs if t.get("type") == "income")
    expense = sum(t.get("amount", 0) for t in txs if t.get("type") == "expense")
    balance = income - expense

    # Month key
    if not month:
        now = datetime.utcnow()
        month = f"{now.year:04d}-{now.month:02d}"

    # Monthly spending and budget
    start = datetime.strptime(month + "-01", "%Y-%m-%d")
    # naive end-of-month (next month day 1)
    if start.month == 12:
        end = datetime(start.year + 1, 1, 1)
    else:
        end = datetime(start.year, start.month + 1, 1)

    month_txs = list(db["transaction"].find({"date": {"$gte": start, "$lt": end}}))
    month_spend = sum(t.get("amount", 0) for t in month_txs if t.get("type") == "expense")

    bud_doc = db["budget"].find_one({"month": month})
    budget_amount = bud_doc.get("amount", 0) if bud_doc else 0
    progress = month_spend / budget_amount if budget_amount else 0

    prof = db["profile"].find_one({}) or {}
    currency = prof.get("currency", "$")

    recent = list(db["transaction"].find().sort("date", -1).limit(10))
    # Convert ObjectId to str and datetime to isoformat
    def serialize(doc):
        doc["id"] = str(doc.pop("_id")) if doc.get("_id") else None
        if isinstance(doc.get("date"), datetime):
            doc["date"] = doc["date"].isoformat()
        return doc

    return {
        "balance": round(balance, 2),
        "income": round(income, 2),
        "expense": round(expense, 2),
        "month": month,
        "month_spend": round(month_spend, 2),
        "budget": budget_amount,
        "progress": progress,
        "currency": currency,
        "recent": [serialize(r) for r in recent],
    }

class TxCreate(BaseModel):
    title: str
    amount: float
    type: str  # 'income' | 'expense'
    category: str
    date: Optional[datetime] = None
    notes: Optional[str] = None

@app.post("/transactions")
def add_transaction(payload: TxCreate):
    if db is None:
        raise HTTPException(status_code=500, detail="Database not configured")
    tx = Transaction(
        title=payload.title,
        amount=payload.amount,
        type=payload.type,  # validation via Transaction model
        category=payload.category,
        date=payload.date or datetime.utcnow(),
        notes=payload.notes,
    )
    _id = create_document("transaction", tx)
    return {"id": _id}

@app.get("/transactions")
def list_transactions(
    start_date: Optional[str] = Query(None, description="YYYY-MM-DD"),
    end_date: Optional[str] = Query(None, description="YYYY-MM-DD"),
    category: Optional[str] = None,
    type: Optional[str] = None,
    min_amount: Optional[float] = None,
    max_amount: Optional[float] = None,
    limit: int = 100,
):
    if db is None:
        raise HTTPException(status_code=500, detail="Database not configured")

    query = {}
    date_filter = {}
    if start_date:
        date_filter["$gte"] = datetime.strptime(start_date, "%Y-%m-%d")
    if end_date:
        date_filter["$lt"] = datetime.strptime(end_date, "%Y-%m-%d")
    if date_filter:
        query["date"] = date_filter
    if category:
        query["category"] = category
    if type:
        query["type"] = type
    if min_amount is not None or max_amount is not None:
        amt = {}
        if min_amount is not None:
            amt["$gte"] = float(min_amount)
        if max_amount is not None:
            amt["$lte"] = float(max_amount)
        query["amount"] = amt

    docs = list(db["transaction"].find(query).sort("date", -1).limit(limit))

    def serialize(doc):
        doc["id"] = str(doc.pop("_id")) if doc.get("_id") else None
        if isinstance(doc.get("date"), datetime):
            doc["date"] = doc["date"].isoformat()
        return doc

    return [serialize(d) for d in docs]

class BudgetSet(BaseModel):
    month: Optional[str] = None  # default to current
    amount: float

@app.post("/budget")
def set_budget(payload: BudgetSet):
    if db is None:
        raise HTTPException(status_code=500, detail="Database not configured")
    if not payload.month:
        now = datetime.utcnow()
        payload.month = f"{now.year:04d}-{now.month:02d}"
    db["budget"].update_one(
        {"month": payload.month},
        {"$set": {"month": payload.month, "amount": float(payload.amount), "updated_at": datetime.utcnow()}},
        upsert=True,
    )
    return {"status": "ok"}

@app.get("/categories")
def categories():
    if db is None:
        raise HTTPException(status_code=500, detail="Database not configured")
    prof = db["profile"].find_one({}) or {}
    cats = prof.get("categories") or DEFAULT_CATEGORIES
    return cats

if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("PORT", 8000))
    uvicorn.run(app, host="0.0.0.0", port=port)
