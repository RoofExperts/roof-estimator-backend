"""
Condition-Based Commercial Roofing Estimating Engine - Database Models

This module defines SQLAlchemy models for the condition-based roofing estimation system:
- RoofCondition: Represents a specific condition/zone on a project
- MaterialTemplate: Defines materials and coverage rates for each condition type
- EstimateLineItem: Calculated line items for project estimates
- CostDatabaseItem: Internal pricing database for materials and labor
"""

from sqlalchemy import Column, Integer, String, Float, DateTime, Boolean, Text, ForeignKey
from sqlalchemy.orm import relationship
from database import Base
import datetime


# ============================================================================
# ROOF CONDITION MODEL
# ============================================================================

class RoofCondition(Base):
    """
    Represents a single condition or zone on a roofing project.
    
    Condition types include field areas, perimeters, corners, penetrations,
    edge details, transitions, and custom areas. Wind zones follow ASCE 7-16.
    """
    __tablename__ = "roof_conditions"
    
    id = Column(Integer, primary_key=True, index=True)
    project_id = Column(Integer, ForeignKey("projects.id"), nullable=False, index=True)
    condition_type = Column(
        String,
        nullable=False,
        index=True,
        comment="field, perimeter, corner, penetration, edge_detail, transition, custom"
    )
    description = Column(String, nullable=True)
    measurement_value = Column(Float, nullable=False, comment="Numeric measurement of the condition")
    measurement_unit = Column(
        String,
        nullable=False,
        default="sqft",
        comment="sqft, lnft (linear feet), each, or percent"
    )
    wind_zone = Column(
        String,
        nullable=True,
        comment="ASCE 7-16 wind zone: 1, 2, 3, or 4"
    )
    created_at = Column(DateTime, default=datetime.datetime.utcnow)
    
    # Relationships
    estimate_items = relationship("EstimateLineItem", back_populates="condition")


# ============================================================================
# MATERIAL TEMPLATE MODEL
# ============================================================================

class MaterialTemplate(Base):
    """
    Defines which materials are used for each condition type and at what coverage rates.
    
    Coverage rates are multiplied by the condition's measurement value to calculate
    the quantity needed. Waste factor is applied as a percentage (e.g., 0.10 = 10%).
    """
    __tablename__ = "material_templates"
    
    id = Column(Integer, primary_key=True, index=True)
    condition_type = Column(
        String,
        nullable=False,
        index=True,
        comment="field, perimeter, corner, penetration, edge_detail, transition, custom"
    )
    material_name = Column(String, nullable=False)
    material_category = Column(
        String,
        nullable=False,
        comment="membrane, insulation, fastener, adhesive, flashing, sealant, accessory"
    )
    unit = Column(String, nullable=False, comment="sqft, lnft, each, gallon, etc.")
    coverage_rate = Column(
        Float,
        nullable=False,
        comment="Units needed per unit of measurement (e.g., 1.0 fastener per 1 sqft)"
    )
    waste_factor = Column(Float, default=0.10, comment="Waste percentage (default 10%)")
    is_active = Column(Boolean, default=True, index=True)
    created_at = Column(DateTime, default=datetime.datetime.utcnow)


# ============================================================================
# ESTIMATE LINE ITEM MODEL
# ============================================================================

class EstimateLineItem(Base):
    """
    Represents a single line item in a project estimate.
    
    These are calculated from conditions, material templates, and the cost database.
    Each line item tracks the material, quantity, unit cost, and total cost.
    """
    __tablename__ = "estimate_line_items"
    
    id = Column(Integer, primary_key=True, index=True)
    project_id = Column(Integer, ForeignKey("projects.id"), nullable=False, index=True)
    condition_id = Column(Integer, ForeignKey("roof_conditions.id"), nullable=False, index=True)
    material_name = Column(String, nullable=False)
    material_category = Column(String, nullable=False)
    quantity = Column(Float, nullable=False, comment="Calculated quantity needed")
    unit = Column(String, nullable=False)
    unit_cost = Column(Float, nullable=False, comment="Cost per unit from cost database")
    total_cost = Column(Float, nullable=False, comment="quantity * unit_cost")
    notes = Column(String, nullable=True)
    created_at = Column(DateTime, default=datetime.datetime.utcnow)
    
    # Relationships
    condition = relationship("RoofCondition", back_populates="estimate_items")


# ============================================================================
# COST DATABASE ITEM MODEL
# ============================================================================

class CostDatabaseItem(Base):
    """
    The internal pricing database for all materials and labor.
    
    Contains unit costs and optional labor costs per unit. Updated regularly
    to reflect market pricing. Can be toggled active/inactive.
    """
    __tablename__ = "cost_database_items"
    
    id = Column(Integer, primary_key=True, index=True)
    material_name = Column(String, nullable=False, index=True)
    manufacturer = Column(String, nullable=True, comment="Equipment/brand manufacturer")
    material_category = Column(
        String,
        nullable=False,
        index=True,
        comment="membrane, insulation, fastener, adhesive, flashing, sealant, accessory"
    )
    unit = Column(String, nullable=False, comment="sqft, lnft, each, gallon, etc.")
    unit_cost = Column(Float, nullable=False, comment="Material cost per unit")
    labor_cost_per_unit = Column(Float, nullable=True, comment="Optional labor cost per unit")
    last_updated = Column(DateTime, default=datetime.datetime.utcnow, onupdate=datetime.datetime.utcnow)
    is_active = Column(Boolean, default=True, index=True)
