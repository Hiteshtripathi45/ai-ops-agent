import os
import json

from fastapi import FastAPI, Depends, HTTPException, Header
from sqlalchemy.orm import Session

from app.database import Base, engine, SessionLocal
from app import models
from app.schema import (
    CustomerCreate,
    OrderCreate,
    PaymentCreate,
    TaskCreate,
    ApprovalDecision,
)
from app.agent import run_agent, resume_agent

Base.metadata.create_all(bind=engine)

app = FastAPI(title="AI Ops Agent")

# =====================================================================
# STARTUP / HEALTH
# =====================================================================

@app.on_event("startup")
def seed_if_empty():
    """On free hosts, the disk is temporary, so the DB resets on restart.
    If the database is empty, populate it with demo data."""
    db = SessionLocal()
    try:
        is_empty = db.query(models.Customer).count() == 0
    finally:
        db.close()
    
    if is_empty:
        from seed import seed
        try:
            seed()
            print("Database seeded successfully.")
        except Exception as e:
            print(f"Seeding failed (this is okay if using a persistent DB): {e}")

@app.get("/health")
def health():
    return {"status": "ok"}


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


# =====================================================================
# CUSTOMERS
# =====================================================================

@app.post("/customers")
def create_customer(payload: CustomerCreate, db: Session = Depends(get_db)):
    customer = models.Customer(name=payload.name, email=payload.email)
    db.add(customer)
    db.commit()
    db.refresh(customer)
    return customer


@app.get("/customers")
def list_customers(db: Session = Depends(get_db)):
    return db.query(models.Customer).all()


@app.get("/customers/{customer_id}")
def get_customer(customer_id: int, db: Session = Depends(get_db)):
    customer = db.query(models.Customer).filter(models.Customer.id == customer_id).first()
    if not customer:
        raise HTTPException(status_code=404, detail="Customer not found")
    return customer


# =====================================================================
# ORDERS
# =====================================================================

@app.post("/orders")
def create_order(payload: OrderCreate, db: Session = Depends(get_db)):
    order = models.Order(customer_id=payload.customer_id, item=payload.item, amount=payload.amount)
    db.add(order)
    db.commit()
    db.refresh(order)
    return order


@app.get("/orders/{order_id}")
def get_order(order_id: int, db: Session = Depends(get_db)):
    order = db.query(models.Order).filter(models.Order.id == order_id).first()
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")
    return order


# =====================================================================
# PAYMENTS
# =====================================================================

@app.post("/payments")
def create_payment(payload: PaymentCreate, db: Session = Depends(get_db)):
    payment = models.Payment(order_id=payload.order_id, amount=payload.amount)
    db.add(payment)
    db.commit()
    db.refresh(payment)
    return payment


@app.get("/orders/{order_id}/payments")
def get_payments_for_order(order_id: int, db: Session = Depends(get_db)):
    return db.query(models.Payment).filter(models.Payment.order_id == order_id).all()


# =====================================================================
# AGENT TASKS
# =====================================================================

def require_key(x_api_key: str = Header(None, alias="X-API-Key")):
    expected = os.getenv("APP_API_KEY")
    if not expected:
        raise HTTPException(status_code=500, detail="Server misconfigured: APP_API_KEY not set")
    if x_api_key != expected:
        raise HTTPException(status_code=401, detail="Invalid or missing API key")


@app.post("/tasks", dependencies=[Depends(require_key)])
def create_agent_task(payload: TaskCreate):
    return run_agent(payload.request, approval_handler=None, verbose=False)


@app.get("/tasks", dependencies=[Depends(require_key)])
def list_tasks(db: Session = Depends(get_db)):
    tasks = db.query(models.Task).order_by(models.Task.id.desc()).all()
    return [
        {
            "id": t.id,
            "request": t.request,
            "status": t.status,
            "created_at": t.created_at,
        }
        for t in tasks
    ]


@app.get("/tasks/{task_id}", dependencies=[Depends(require_key)])
def get_task(task_id: int, db: Session = Depends(get_db)):
    task = db.query(models.Task).filter(models.Task.id == task_id).first()
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")

    def _load(raw):
        if not raw:
            return None
        try:
            return json.loads(raw)
        except (TypeError, json.JSONDecodeError):
            return None

    return {
        "id": task.id,
        "request": task.request,
        "status": task.status,
        "final_answer": task.final_answer,
        "llm_calls": task.llm_calls,
        "created_at": task.created_at,
        "finished_at": task.finished_at,
        "pending": _load(task.pending),
        "state": _load(task.state),
        "steps": [
            {
                "tool": s.tool_name,
                "args": _load(s.tool_args),
                "result": _load(s.result),
                "created_at": s.created_at,
            }
            for s in task.steps
        ],
    }


@app.post("/tasks/{task_id}/approve", dependencies=[Depends(require_key)])
def decide_task(task_id: int, payload: ApprovalDecision):
    try:
        return resume_agent(task_id, payload.approved)
    except ValueError as e:
        raise HTTPException(status_code=409, detail=str(e))