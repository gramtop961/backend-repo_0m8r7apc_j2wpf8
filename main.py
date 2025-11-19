import os
from datetime import datetime
from typing import List, Optional

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from database import db, create_document, get_documents
from schemas import Transaction, Budget, Profile

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
    return ["Food", "Bills", "Transport", "Shopping", "Savings", "Other"]

if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("PORT", 8000))
    uvicorn.run(app, host="0.0.0.0", port=port)
