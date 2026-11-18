from sqlalchemy import Column, Integer, String, Float, ForeignKey, DateTime, Text
from sqlalchemy.orm import relationship
from datetime import datetime, timezone
from app.database import Base


def _utcnow():
    return datetime.now(timezone.utc)


class Customer(Base):
    __tablename__ = "customers"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, nullable=False)
    email = Column(String, unique=True, nullable=False)

    orders = relationship("Order", back_populates="customer")


class Order(Base):
    __tablename__ = "orders"

    id = Column(Integer, primary_key=True, index=True)
    customer_id = Column(Integer, ForeignKey("customers.id"), nullable=False)
    item = Column(String, nullable=False)
    amount = Column(Float, nullable=False)
    status = Column(String, default="placed")  # placed, cancelled, refunded
    created_at = Column(DateTime(timezone=True), default=_utcnow)

    customer = relationship("Customer", back_populates="orders")
    payments = relationship("Payment", back_populates="order")


class Payment(Base):
    __tablename__ = "payments"

    id = Column(Integer, primary_key=True, index=True)
    order_id = Column(Integer, ForeignKey("orders.id"), nullable=False)
    amount = Column(Float, nullable=False)
    status = Column(String, default="success")  # success, failed, refunded
    created_at = Column(DateTime(timezone=True), default=_utcnow)

    order = relationship("Order", back_populates="payments")


class Task(Base):
    """One agent run. status: running, waiting_for_approval, completed, needs_review"""
    __tablename__ = "tasks"

    id = Column(Integer, primary_key=True, index=True)
    request = Column(Text, nullable=False)
    status = Column(String, default="running")
    final_answer = Column(Text)
    llm_calls = Column(Integer, default=0)
    created_at = Column(DateTime(timezone=True), default=_utcnow)
    finished_at = Column(DateTime(timezone=True))

    steps = relationship("TaskStep", back_populates="task")
    state = Column(Text)     # JSON: conversation + progress, saved when paused
    pending = Column(Text)   # JSON: the action waiting for a human decision


class TaskStep(Base):
    """One tool call made during a task."""
    __tablename__ = "task_steps"

    id = Column(Integer, primary_key=True, index=True)
    task_id = Column(Integer, ForeignKey("tasks.id"), nullable=False)
    tool_name = Column(String, nullable=False)
    tool_args = Column(Text)
    result = Column(Text)
    created_at = Column(DateTime(timezone=True), default=_utcnow)

    task = relationship("Task", back_populates="steps")