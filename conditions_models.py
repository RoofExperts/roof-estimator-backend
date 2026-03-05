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
# CONDITION TYPES — the roof area breakouts an estimator uses
# ============================================================================
# Each maps to a default measurement unit and a set of material templates.
CONDITION_TYPES = {
    "field":          {"label": "Field of Roof",   "default_unit": "sqft"},
    "wall_flashing":  {"label": "Wall Flashings",  "default_unit": "lnft"},
    "roof_drain":     {"label": "Roof Drains",     "default_unit": "each"},
    "scupper":        {"label": "Scuppers",        "default_unit": "each"},
    "pipe_flashing":  {"label": "Pipe Flashings",  "default_unit": "each"},
    "coping":         {"label": "Coping",          "default_unit": "lnft"},
    "perimeter":      {"label": "Perimeter",       "default_unit": "lnft"},
    "corner":         {"label": "Corners",         "default_unit": "sqft"},
    "penetration":    {"label": "Penetrations",    "default_unit": "each"},
    "pitch_pan":      {"label": "Pitch Pans",      "default_unit": "each"},
    "expansion_joint":{"label": "Expansion Joints", "default_unit": "lnft"},
    "curb":           {"label": "Curbs",           "default_unit": "lnft"},
    "parapet":        {"label": "Parapets",        "default_unit": "lnft"},
    "edge_detail":    {"label": "Edge Details",    "default_unit": "lnft"},
    "transition":     {"label": "Transitions",     "default_unit": "lnft"},
    "custom":         {"label": "Custom",          "default_unit": "sqft"},
}


# ============================================================================
# ROOF CONDITION MODEL
# ============================================================================

class RoofCondition(Base):
    """
    Represents a single condition or zone on a roofing project.

    Condition types: field, wall_flashing, roof_drain, scupper, pipe_flashing,
    coping, perimeter, corner, penetration, expansion_joint, curb, parapet,
    edge_detail, transition, custom.
    """
    __tablename__ = "roof_conditions"

    id = Column(Integer, primary_key=True, index=True)
    project_id = Column(Integer, ForeignKey("projects.id"), nullable=False, index=True)
    condition_type = Column(
        String,
        nullable=False,
        index=True,
        comment="field, wall_flashing, roof_drain, scupper, pipe_flashing, coping, perimeter, etc."
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
    flashing_height = Column(
        Float,
        nullable=True,
        default=60.0,
        comment="Flashing height in inches (default 60\"). Used for wall flashing material calculations."
    )
    fastener_spacing = Column(
        Integer,
        nullable=True,
        default=12,
        comment="Fastener spacing in inches (e.g. 12 or 6). User selectable per condition."
    )
    created_at = Column(DateTime, default=datetime.datetime.utcnow)

    # Relationships
    estimate_items = relationship("EstimateLineItem", back_populates="condition")
    materials = relationship("ConditionMaterial", back_populates="condition", cascade="all, delete-orphan")


# ============================================================================
# CONDITION MATERIAL MODEL  (per-condition editable material list)
# ============================================================================

class ConditionMaterial(Base):
    """
    A specific material attached to a specific condition instance.
    Created by Smart Build from MaterialTemplates, then editable by the user.

    The estimate engine reads these rows (not MaterialTemplates directly)
    to calculate quantities and costs.
    """
    __tablename__ = "condition_materials"

    id = Column(Integer, primary_key=True, index=True)
    condition_id = Column(Integer, ForeignKey("roof_conditions.id"), nullable=False, index=True)
    material_template_id = Column(
        Integer, ForeignKey("material_templates.id"), nullable=True,
        comment="Source template (nullable for user-added custom materials)"
    )
    material_name = Column(String, nullable=False)
    material_category = Column(
        String, nullable=False,
        comment="membrane, insulation, fastener, adhesive, flashing, sealant, accessory"
    )
    unit = Column(String, nullable=False, comment="sqft, lnft, each, gallon, etc.")
    coverage_rate = Column(
        Float, nullable=False,
        comment="Units needed per unit of condition measurement"
    )
    waste_factor = Column(Float, default=0.10, comment="Waste percentage (0.10 = 10%)")
    calc_type = Column(
        String, nullable=True,
        comment="Special calc: 'wall_membrane', 'fastener', or NULL=standard"
    )
    is_included = Column(Boolean, default=True, comment="User can toggle materials on/off")
    override_quantity = Column(
        Float, nullable=True,
        comment="If set, use this qty instead of calculated. NULL = auto-calculate."
    )
    notes = Column(String, nullable=True)
    sort_order = Column(Integer, default=0)
    created_at = Column(DateTime, default=datetime.datetime.utcnow)

    # Relationships
    condition = relationship("RoofCondition", back_populates="materials")


# ============================================================================
# MATERIAL TEMPLATE MODEL
# ============================================================================

class MaterialTemplate(Base):
    """
    Defines which materials are used for each condition type and at what coverage rates.

    Coverage rates are multiplied by the condition's measurement value to calculate
    the quantity needed. Waste factor is applied as a percentage (e.g., 0.10 = 10%).

    system_type determines which roofing system this template belongs to:
    TPO, EPDM, PVC, or 'common' (shared across all systems).
    """
    __tablename__ = "material_templates"

    id = Column(Integer, primary_key=True, index=True)
    system_type = Column(
        String,
        nullable=False,
        default="common",
        index=True,
        comment="TPO, EPDM, PVC, or common (shared across all systems)"
    )
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
    calc_type = Column(
        String, nullable=True,
        comment="Special calculation type: 'wall_membrane' (uses flashing height), 'fastener' (uses spacing), NULL=standard"
    )
    sort_order = Column(Integer, default=0,
                       comment="Display order within condition (lower = first in build-up stack)")
    is_optional = Column(Boolean, default=False,
                         comment="True = material is optional (e.g. base sheet, insulation layers)")
    is_active = Column(Boolean, default=True, index=True)
    org_id = Column(Integer, ForeignKey("organizations.id"), nullable=True, index=True,
                    comment="NULL + is_global=True = shared seed template")
    is_global = Column(Boolean, default=False, index=True,
                       comment="True = shared across all orgs (seed data)")
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
    description = Column(String, nullable=True,
                         comment="Product description, R-value info, specs")
    notes = Column(String, nullable=True,
                   comment="Additional notes (R-value, psi, facers, etc.)")
    last_updated = Column(DateTime, default=datetime.datetime.utcnow, onupdate=datetime.datetime.utcnow)
    is_active = Column(Boolean, default=True, index=True)
    org_id = Column(Integer, ForeignKey("organizations.id"), nullable=True, index=True,
                    comment="NULL + is_global=True = shared seed pricing")
    is_global = Column(Boolean, default=False, index=True,
                       comment="True = shared across all orgs (seed data)")
