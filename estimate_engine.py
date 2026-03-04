"""
Condition-Based Commercial Roofing Estimating Engine - Calculation Logic

This module provides the core calculation functions that:
1. Retrieve conditions for a project
2. Determine the project's roofing system (TPO, EPDM, PVC)
3. Match material templates by condition type AND system type
4. Calculate quantities based on coverage rates and waste
5. Look up unit costs from the cost database
6. Generate estimate line items and summary reports
"""

from sqlalchemy.orm import Session
from sqlalchemy import or_
from conditions_models import RoofCondition, MaterialTemplate, EstimateLineItem, CostDatabaseItem
from models import Project
from sqlalchemy import delete
from typing import Dict, List, Optional
import json


# ============================================================================
# HELPER: DETECT SYSTEM TYPE FROM PROJECT
# ============================================================================

def detect_system_type(project: "Project") -> str:
    """
    Determine the roofing system type for a project.

    Priority:
    1. project.system_type if explicitly set (user override)
    2. Parsed from spec analysis_result (membrane_type field)
    3. Default to 'TPO'
    """
    # 1. Explicit project system_type
    if project.system_type:
        st = project.system_type.upper().strip()
        if "EPDM" in st:
            return "EPDM"
        if "PVC" in st:
            return "PVC"
        if "TPO" in st:
            return "TPO"

    # 2. Parse from spec analysis
    if project.analysis_result:
        try:
            spec = json.loads(project.analysis_result) if isinstance(project.analysis_result, str) else project.analysis_result
            membrane = (spec.get("membrane_type") or "").upper()
            system_name = (spec.get("roof_system_type") or "").upper()

            if "EPDM" in membrane or "EPDM" in system_name:
                return "EPDM"
            if "PVC" in membrane or "PVC" in system_name:
                return "PVC"
            if "TPO" in membrane or "TPO" in system_name:
                return "TPO"
        except (json.JSONDecodeError, TypeError, AttributeError):
            pass

    return "TPO"  # Default


# ============================================================================
# HELPER: SMART QUANTITY CALCULATOR
# ============================================================================

def _calculate_quantity(condition: "RoofCondition", template: "MaterialTemplate") -> float:
    """
    Calculate base quantity for a condition + template pair.

    Special formulas:
    - wall_flashing membrane: length × (flashing_height_inches + 18) / 12  → converts to linear feet of material
    - wall_flashing fasteners: length / fastener_spacing_inches  → screws per LF
    - all others: measurement_value × coverage_rate (standard)

    calc_type field on MaterialTemplate (if present) drives special logic:
      'wall_membrane'  → uses flashing height formula
      'fastener'       → uses fastener spacing formula
      None / anything else → standard
    """
    measurement = condition.measurement_value
    coverage = template.coverage_rate
    calc_type = getattr(template, "calc_type", None)

    if calc_type == "wall_membrane":
        # TPO/EPDM/PVC sheet to cover wall: length × (height_in + 18") / 12
        height_in = getattr(condition, "flashing_height", None) or 60.0
        width_ft = (height_in + 18.0) / 12.0
        return measurement * width_ft * coverage

    elif calc_type == "fastener":
        # Screws/plates per linear foot based on spacing
        spacing_in = getattr(condition, "fastener_spacing", None) or 12
        fasteners_per_lf = 12.0 / spacing_in
        return measurement * fasteners_per_lf * coverage

    else:
        # Standard: measurement × coverage_rate
        return measurement * coverage


# ============================================================================
# MAIN CALCULATION FUNCTION
# ============================================================================

def calculate_estimate(project_id: int, db: Session) -> Dict:
    """
    Calculate the complete estimate for a project based on conditions and material templates.

    Now system-aware: only uses material templates matching the project's roofing system
    (TPO, EPDM, PVC) plus 'common' templates shared across all systems.

    Process:
    1. Retrieve all conditions for the project
    2. Determine the project's roofing system
    3. For each condition, find matching material templates by condition_type AND system_type
    4. For each template, calculate: quantity = measurement_value * coverage_rate * (1 + waste_factor)
    5. Look up unit cost from cost database
    6. Create EstimateLineItem records (delete old ones first)
    7. Return success status and line item count
    """

    try:
        # Verify project exists
        project = db.query(Project).filter(Project.id == project_id).first()
        if not project:
            return {"status": "error", "message": f"Project {project_id} not found"}

        # Determine system type
        system_type = detect_system_type(project)
        print(f"[Estimate] Project {project_id} system_type: {system_type}")

        # Delete existing estimate line items for this project
        db.query(EstimateLineItem).filter(EstimateLineItem.project_id == project_id).delete()
        db.commit()

        # Get all conditions for this project
        conditions = db.query(RoofCondition).filter(RoofCondition.project_id == project_id).all()

        if not conditions:
            return {
                "status": "success",
                "message": "No conditions found for this project",
                "system_type": system_type,
                "line_items_created": 0,
                "total_cost": 0.0
            }

        line_items_created = 0
        total_cost = 0.0
        errors = []

        # Process each condition
        for condition in conditions:
            # Find material templates for this condition type AND system
            # Include both system-specific templates and common templates
            templates = db.query(MaterialTemplate).filter(
                MaterialTemplate.condition_type == condition.condition_type,
                MaterialTemplate.is_active == True,
                or_(
                    MaterialTemplate.system_type == system_type,
                    MaterialTemplate.system_type == "common"
                )
            ).all()

            # Generate line items from templates
            for template in templates:
                # Calculate quantity with waste (uses smart formula for wall flashing etc.)
                base_quantity = _calculate_quantity(condition, template)
                quantity = base_quantity * (1 + template.waste_factor)

                # Look up cost from database
                cost_item = db.query(CostDatabaseItem).filter(
                    CostDatabaseItem.material_name == template.material_name,
                    CostDatabaseItem.unit == template.unit,
                    CostDatabaseItem.is_active == True
                ).first()

                if not cost_item:
                    errors.append(
                        f"No cost found for {template.material_name} ({template.unit}) "
                        f"in condition {condition.id}"
                    )
                    continue

                # Calculate total cost (material + optional labor)
                unit_cost = cost_item.unit_cost
                if cost_item.labor_cost_per_unit:
                    unit_cost += cost_item.labor_cost_per_unit

                item_total = quantity * unit_cost

                # Create line item
                line_item = EstimateLineItem(
                    project_id=project_id,
                    condition_id=condition.id,
                    material_name=template.material_name,
                    material_category=template.material_category,
                    quantity=quantity,
                    unit=template.unit,
                    unit_cost=unit_cost,
                    total_cost=item_total,
                    notes=f"[{system_type}] {condition.description or condition.condition_type}"
                )

                db.add(line_item)
                line_items_created += 1
                total_cost += item_total

        db.commit()

        return {
            "status": "success",
            "system_type": system_type,
            "line_items_created": line_items_created,
            "total_cost": round(total_cost, 2),
            "errors": errors if errors else None
        }

    except Exception as e:
        db.rollback()
        return {
            "status": "error",
            "message": f"Failed to calculate estimate: {str(e)}"
        }


# ============================================================================
# ESTIMATE SUMMARY FUNCTION
# ============================================================================

def get_estimate_summary(project_id: int, db: Session) -> Dict:
    """
    Generate a structured summary of the estimate for a project.

    Includes:
    - Detected system type
    - Conditions grouped with their line items
    - Subtotals per condition
    - Material and labor subtotals
    - Material category breakdown
    - Grand total
    """

    try:
        project = db.query(Project).filter(Project.id == project_id).first()
        if not project:
            return {"status": "error", "message": f"Project {project_id} not found"}

        system_type = detect_system_type(project)

        # Get all conditions with their line items
        conditions = db.query(RoofCondition).filter(
            RoofCondition.project_id == project_id
        ).all()

        if not conditions:
            return {
                "status": "success",
                "project_id": project_id,
                "project_name": project.project_name,
                "system_type": system_type,
                "conditions": [],
                "summary": {
                    "material_subtotal": 0.0,
                    "labor_subtotal": 0.0,
                    "grand_total": 0.0,
                    "category_breakdown": {}
                }
            }

        # Build condition details
        conditions_detail = []
        material_total = 0.0
        labor_total = 0.0
        category_breakdown = {}

        for condition in conditions:
            # Get line items for this condition
            line_items = db.query(EstimateLineItem).filter(
                EstimateLineItem.condition_id == condition.id
            ).all()

            condition_subtotal = 0.0
            items = []

            for item in line_items:
                # Estimate material vs labor split
                cost_item = db.query(CostDatabaseItem).filter(
                    CostDatabaseItem.material_name == item.material_name,
                    CostDatabaseItem.unit == item.unit
                ).first()

                material_portion = item.total_cost
                labor_portion = 0.0

                if cost_item and cost_item.labor_cost_per_unit:
                    labor_portion = item.quantity * cost_item.labor_cost_per_unit
                    material_portion = item.total_cost - labor_portion

                # Track category breakdown
                category = item.material_category
                if category not in category_breakdown:
                    category_breakdown[category] = 0.0
                category_breakdown[category] += item.total_cost

                items.append({
                    "id": item.id,
                    "material_name": item.material_name,
                    "material_category": item.material_category,
                    "quantity": item.quantity,
                    "unit": item.unit,
                    "unit_cost": item.unit_cost,
                    "total_cost": item.total_cost,
                    "material_portion": round(material_portion, 2),
                    "labor_portion": round(labor_portion, 2)
                })

                condition_subtotal += item.total_cost
                material_total += material_portion
                labor_total += labor_portion

            conditions_detail.append({
                "id": condition.id,
                "condition_type": condition.condition_type,
                "description": condition.description,
                "measurement_value": condition.measurement_value,
                "measurement_unit": condition.measurement_unit,
                "wind_zone": condition.wind_zone,
                "subtotal": round(condition_subtotal, 2),
                "line_items": items
            })

        grand_total = material_total + labor_total

        return {
            "status": "success",
            "project_id": project_id,
            "project_name": project.project_name,
            "system_type": system_type,
            "conditions": conditions_detail,
            "summary": {
                "material_subtotal": round(material_total, 2),
                "labor_subtotal": round(labor_total, 2),
                "grand_total": round(grand_total, 2),
                "category_breakdown": {cat: round(cost, 2) for cat, cost in category_breakdown.items()}
            }
        }

    except Exception as e:
        return {
            "status": "error",
            "message": f"Failed to generate estimate summary: {str(e)}"
        }


# ============================================================================
# HELPER FUNCTION: GET AVAILABLE CONDITION TYPES
# ============================================================================

def get_available_condition_types(db: Session) -> List[str]:
    """Get all unique condition types that have active material templates."""
    templates = db.query(MaterialTemplate.condition_type).filter(
        MaterialTemplate.is_active == True
    ).distinct().all()

    return [t[0] for t in templates]


# ============================================================================
# HELPER FUNCTION: GET MATERIALS FOR CONDITION TYPE (system-aware)
# ============================================================================

def get_materials_for_condition(condition_type: str, db: Session, system_type: str = None) -> List[Dict]:
    """
    Get all active material templates for a specific condition type.
    If system_type is provided, filters to that system + common templates.
    """
    query = db.query(MaterialTemplate).filter(
        MaterialTemplate.condition_type == condition_type,
        MaterialTemplate.is_active == True
    )

    if system_type:
        query = query.filter(
            or_(
                MaterialTemplate.system_type == system_type,
                MaterialTemplate.system_type == "common"
            )
        )

    templates = query.all()

    return [
        {
            "id": t.id,
            "system_type": t.system_type,
            "material_name": t.material_name,
            "material_category": t.material_category,
            "unit": t.unit,
            "coverage_rate": t.coverage_rate,
            "waste_factor": t.waste_factor
        }
        for t in templates
    ]
