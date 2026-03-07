"""
Condition-Based Commercial Roofing Estimating Engine - Database Models

This module defines SQLAlchemy models for the condition-based roofing estimation system:
- RoofCondition: Represents a specific condition/zone on a project
- MaterialTemplate: Defines materials and coverage rates for each condition type
- EstimateLineItem: Calculated line items for project estimates
- CostDatabaseItem: Internal pricing database for materials and labor
- SystemTemplateCondition: Org-customizable system template conditions
"""

from sqlalchemy import Column, Integer, String, Float, DateTime, Boolean, Text, ForeignKey
from sqlalchemy.orm import relationship
from database import Base
import datetime


# ============================================================================
# ROOF SYSTEM MODEL — groups conditions into a complete roofing system
# ============================================================================

class RoofSystem(Base):
    """
    Represents a complete roofing system for a project area.

    A project can have multiple roof systems (e.g., "Main Roof - TPO", "Lower Roof - EPDM").
    Each system contains a full set of conditions (field, perimeter, wall flashing, etc.)
    that can be individually toggled on/off.
    """
    __tablename__ = "roof_systems"

    id = Column(Integer, primary_key=True, index=True)
    project_id = Column(Integer, ForeignKey("projects.id"), nullable=False, index=True)
    name = Column(String, nullable=False, default="Roof Area 1", comment="User-friendly name")
    system_type = Column(
        String, nullable=False, default="TPO",
        comment="TPO, EPDM, PVC, ModBit, BUR, StandingSeam"
    )
    is_active = Column(Boolean, default=True, comment="Include in estimate calculations")
    sort_order = Column(Integer, default=0)
    created_at = Column(DateTime, default=datetime.datetime.utcnow)

    # Specified Roof System details (user-editable dropdowns)
    manufacturer = Column(String, nullable=True, comment="Manufacturer name (e.g., Carlisle, Firestone, GAF)")
    membrane_thickness = Column(String, nullable=True, comment="45 mil, 60 mil, 80 mil, 90 mil fleeceback, etc.")
    field_attachment = Column(String, nullable=True, comment="Mechanically Fastened, Rhinobond, Adhesive, Low Rise Foam")
    wall_flashing_thickness = Column(String, nullable=True, comment="45 mil, 60 mil, 80 mil")
    has_coverboard = Column(Boolean, default=False)
    coverboard_attachment = Column(String, nullable=True, comment="Mechanically Fastened, Low Rise Foam")
    has_top_insulation = Column(Boolean, default=False)
    top_insulation_attachment = Column(String, nullable=True, comment="Mechanically Fastened, Gang Fastened, Low Rise Foam")
    has_bottom_insulation = Column(Boolean, default=False)
    bottom_insulation_attachment = Column(String, nullable=True, comment="Mechanically Fastened, Gang Fastened, Low Rise Foam")
    has_vapor_barrier = Column(Boolean, default=False)
    has_vapor_barrier_board = Column(Boolean, default=False)
    vapor_barrier_board_attachment = Column(String, nullable=True, comment="Mechanically Fastened, Gang Fastened, Low Rise Foam")

    # Relationships
    conditions = relationship("RoofCondition", back_populates="roof_system", cascade="all, delete-orphan")


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
    roof_system_id = Column(
        Integer, ForeignKey("roof_systems.id"), nullable=True, index=True,
        comment="FK to RoofSystem. Nullable for backward compat with existing conditions."
    )
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
    is_active = Column(
        Boolean,
        default=True,
        comment="Whether this condition is active/included. Inactive conditions are hidden from estimate."
    )
    created_at = Column(DateTime, default=datetime.datetime.utcnow)

    # Relationships
    roof_system = relationship("RoofSystem", back_populates="conditions")
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
    cost_database_item_id = Column(
        Integer, nullable=True,
        comment="Explicit link to a CostDatabaseItem (for product swap). If set, used instead of fuzzy name matching."
    )
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

    Purchase unit fields enable takeoff-style conversion:
    e.g., 13,000 SF of TPO → 14 Rolls (at 1,000 SF/Roll)
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

    # Purchase unit conversion (SF → Rolls, EA → Boxes, etc.)
    purchase_unit = Column(String, nullable=True,
                           comment="How purchased: Roll, Box, Pail, Tube, Tank, Bundle, etc.")
    units_per_purchase = Column(Float, nullable=True,
                                comment="Base units per purchase unit (e.g., 1000 SF per Roll)")
    product_name = Column(String, nullable=True,
                          comment="Full product name for takeoff (e.g., 'TPO 60mil White 10x100')")


# ============================================================================
# SYSTEM TEMPLATE CONDITION MODEL
# ============================================================================

class SystemTemplateCondition(Base):
    """
    Defines which conditions are included in a system template.

    Global rows (org_id=NULL, is_global=True) are the platform defaults (seeded from
    the hardcoded 15 condition types). Org-specific rows (org_id=X) allow Company Admins
    to customize their template — adding custom conditions (e.g., "vents"), removing
    unused ones, or changing defaults.

    When Smart Build runs, it checks for org-specific rows first, falls back to global.
    """
    __tablename__ = "system_template_conditions"

    id = Column(Integer, primary_key=True, index=True)
    org_id = Column(Integer, ForeignKey("organizations.id"), nullable=True, index=True,
                    comment="NULL + is_global=True = platform default template")
    system_type = Column(String, nullable=False, index=True,
                         comment="TPO, EPDM, PVC, ModBit, BUR, StandingSeam")
    condition_type = Column(String, nullable=False, index=True,
                            comment="field, perimeter, vents, custom name, etc.")
    description = Column(String, nullable=True,
                         comment="Human-friendly label, e.g. 'Field of Roof', 'Roof Vents'")
    measurement_unit = Column(String, default="sqft",
                              comment="sqft, lnft, each")
    flashing_height = Column(Float, nullable=True,
                             comment="Default flashing height in inches")
    fastener_spacing = Column(Integer, nullable=True,
                              comment="Default fastener spacing in inches")
    sort_order = Column(Integer, default=0,
                        comment="Display order in the system template")
    is_global = Column(Boolean, default=False, index=True,
                       comment="True = shared platform default")
    is_active = Column(Boolean, default=True,
                       comment="Soft delete / disable")
    created_at = Column(DateTime, default=datetime.datetime.utcnow)
