"""
Customer Router - CRUD endpoints for master customer database.
"""

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from pydantic import BaseModel
from typing import Optional, List
import datetime

from database import get_db
from models import Customer


customer_router = APIRouter(prefix="/api/v1", tags=["customers"])


# ── Request / Response Models ────────────────────────────────

class CustomerCreate(BaseModel):
    company_name: str
    contact_name: Optional[str] = None
    contact_email: Optional[str] = None
    contact_phone: Optional[str] = None
    address: Optional[str] = None
    notes: Optional[str] = None


class CustomerUpdate(BaseModel):
    company_name: Optional[str] = None
    contact_name: Optional[str] = None
    contact_email: Optional[str] = None
    contact_phone: Optional[str] = None
    address: Optional[str] = None
    notes: Optional[str] = None
    is_active: Optional[bool] = None


class CustomerResponse(BaseModel):
    id: int
    company_name: str
    contact_name: Optional[str]
    contact_email: Optional[str]
    contact_phone: Optional[str]
    address: Optional[str]
    notes: Optional[str]
    is_active: bool
    created_at: datetime.datetime
    updated_at: datetime.datetime

    class Config:
        from_attributes = True


# ── Endpoints ─────────────────────────────────────────────────

@customer_router.get("/customers", response_model=List[CustomerResponse])
def list_customers(
    search: Optional[str] = Query(None),
    is_active: bool = Query(True),
    db: Session = Depends(get_db)
):
    """List all customers, optionally filtered by search term."""
    query = db.query(Customer).filter(Customer.is_active == is_active)
    if search:
        query = query.filter(
            Customer.company_name.ilike(f"%{search}%") |
            Customer.contact_name.ilike(f"%{search}%")
        )
    return query.order_by(Customer.company_name).all()


@customer_router.get("/customers/{customer_id}", response_model=CustomerResponse)
def get_customer(customer_id: int, db: Session = Depends(get_db)):
    """Get a specific customer by ID."""
    customer = db.query(Customer).filter(Customer.id == customer_id).first()
    if not customer:
        raise HTTPException(status_code=404, detail="Customer not found")
    return customer


@customer_router.post("/customers", response_model=CustomerResponse)
def create_customer(data: CustomerCreate, db: Session = Depends(get_db)):
    """Create a new customer."""
    customer = Customer(
        company_name=data.company_name,
        contact_name=data.contact_name,
        contact_email=data.contact_email,
        contact_phone=data.contact_phone,
        address=data.address,
        notes=data.notes,
    )
    db.add(customer)
    db.commit()
    db.refresh(customer)
    return customer


@customer_router.put("/customers/{customer_id}", response_model=CustomerResponse)
def update_customer(customer_id: int, data: CustomerUpdate, db: Session = Depends(get_db)):
    """Update an existing customer."""
    customer = db.query(Customer).filter(Customer.id == customer_id).first()
    if not customer:
        raise HTTPException(status_code=404, detail="Customer not found")

    update_fields = data.model_dump(exclude_unset=True)
    for key, value in update_fields.items():
        setattr(customer, key, value)

    db.commit()
    db.refresh(customer)
    return customer


@customer_router.delete("/customers/{customer_id}")
def delete_customer(customer_id: int, db: Session = Depends(get_db)):
    """Soft-delete a customer."""
    customer = db.query(Customer).filter(Customer.id == customer_id).first()
    if not customer:
        raise HTTPException(status_code=404, detail="Customer not found")
    customer.is_active = False
    db.commit()
    return {"message": "Customer deleted successfully"}
