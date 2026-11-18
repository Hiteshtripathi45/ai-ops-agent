from pydantic import BaseModel


class CustomerCreate(BaseModel):
    name: str
    email: str


class OrderCreate(BaseModel):
    customer_id: int
    item: str
    amount: float


class PaymentCreate(BaseModel):
    order_id: int
    amount: float

class TaskCreate(BaseModel):
    request: str


class ApprovalDecision(BaseModel):
    approved: bool    