"""
Conditions-Driven Commercial Roofing Estimate Engine

This engine calculates estimates directly from ConditionMaterial rows —
the per-condition, per-project material list that users can edit.

Flow:
1. Load all conditions + their ConditionMaterial rows
2. For each included material, calculate quantity using the appropriate formula
3. Look up unit costs from the CostDatabaseItem table
4. Produce two views:
   - By Condition: materials grouped under each condition (for the accordion)
   - Consolidated: same materials aggregated across conditions (for purchasing)
5. Add labor, markup, tax → grand total
"""

from sqlalchemy.orm import Session
from sqlalchemy import or_, func
from conditions_models import (
    RoofCondition, MaterialTemplate, EstimateLineItem, CostDatabaseItem,
    ConditionMaterial, CONDITION_TYPES
)
from models import Project
from typing import Dict, List, Optional
import json


# ============================================================================
# HELPER: SMART COST LOOKUP WITH FALLBACK MATCHING
# ============================================================================

def _find_cost_item(material_name: str, unit: str, org_id: int, db: Session) -> "CostDatabaseItem":
    """
    Smart cost lookup with fallback matching:
    1. Exact match on material_name
    2. Case-insensitive match
    3. Keyword-based match (longest overlap wins)

    Returns the best matching CostDatabaseItem or None.
    """
    base_filter = [
        CostDatabaseItem.is_active == True,
        or_(
            CostDatabaseItem.org_id == org_id,
            CostDatabaseItem.is_global == True
        )
    ]

    # 1. Exact match
    item = db.query(CostDatabaseItem).filter(
        CostDatabaseItem.material_name == material_name,
        *base_filter
    ).first()
    if item:
        return item

    # 2. Case-insensitive exact match
    item = db.query(CostDatabaseItem).filter(
        func.lower(CostDatabaseItem.material_name) == material_name.lower(),
        *base_filter
    ).first()
    if item:
        return item

    # 3. Keyword-based matching
    # Break the material name into keywords and find cost items containing key terms
    keywords = [w.lower() for w in material_name.split() if len(w) > 2]
    # Remove filler words
    filler = {"the", "and", "for", "per", "layer", "top", "bottom"}
    keywords = [k for k in keywords if k not in filler]

    if not keywords:
        return None

    # Get all active cost items for this org
    all_items = db.query(CostDatabaseItem).filter(*base_filter).all()

    best_match = None
    best_score = 0

    for ci in all_items:
        ci_lower = ci.material_name.lower()
        ci_words = set(w.lower() for w in ci.material_name.split() if len(w) > 2)

        # Score: number of matching keywords + bonus for unit match
        score = sum(1 for k in keywords if k in ci_lower or k in ci_words)
        # Bonus for unit match
        if ci.unit and unit and ci.unit.lower() == unit.lower():
            score += 0.5

        if score > best_score and score >= max(1, len(keywords) * 0.4):
            best_score = score
            best_match = ci

    return best_match


# ============================================================================
# HELPER: DETECT SYSTEM TYPE FROM PROJECT
# ============================================================================

def detect_system_type(project: "Project") -> str:
    """Determine the roofing system type for a project."""
    if project.system_type:
        st = project.system_type.upper().strip()
        if "EPDM" in st:
            return "EPDM"
        if "PVC" in st:
            return "PVC"
        if "TPO" in st:
            return "TPO"
        if "MOD" in st:
            return "ModBit"
        if "BUR" in st:
            return "BUR"
        if "STANDING" in st or "METAL" in st:
            return "StandingSeam"

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

    return "TPO"


# ============================================================================
# HELPER: CALCULATE QUANTITY FOR A CONDITION MATERIAL
# ============================================================================

def _calculate_quantity(condition: RoofCondition, mat: ConditionMaterial) -> float:
    """
    Calculate quantity for a condition material.

    If override_quantity is set, use it directly.
    Otherwise apply the formula based on calc_type:
      - wall_membrane: length × (height_in + 18) / 12
      - fastener: length / spacing_in
      - standard: measurement × coverage_rate
    Then apply waste factor.
    """
    # User override
    if mat.override_quantity is not None:
        return mat.override_quantity

    measurement = condition.measurement_value
    coverage = mat.coverage_rate
    calc_type = mat.calc_type

    if calc_type == "wall_membrane":
        height_in = condition.flashing_height or 60.0
        width_ft = (height_in + 18.0) / 12.0
        base = measurement * width_ft * coverage
    elif calc_type == "fastener":
        spacing_in = condition.fastener_spacing or 12
        fasteners_per_lf = 12.0 / spacing_in
        base = measurement * fasteners_per_lf * coverage
    else:
        base = measurement * coverage

    # Apply waste
    return base * (1 + mat.waste_factor)


# ============================================================================
# MAIN: CALCULATE ESTIMATE (conditions-driven)
# ============================================================================

def calculate_estimate(project_id: int, db: Session) -> Dict:
    """
    Calculate the complete estimate from ConditionMaterial rows.

    Returns a conditions_breakdown (for accordion view) and
    consolidated_materials (for purchasing view).
    """
    try:
        project = db.query(Project).filter(Project.id == project_id).first()
        if not project:
            return {"status": "error", "message": f"Project {project_id} not found"}

        system_type = detect_system_type(project)

        # Get all conditions for the project
        conditions = db.query(RoofCondition).filter(
            RoofCondition.project_id == project_id
        ).all()

        if not conditions:
            return {
                "status": "success",
                "system_type": system_type,
                "conditions_breakdown": [],
                "consolidated_materials": [],
                "summary": {
                    "materials_total": 0, "labor_total": 0,
                    "subtotal": 0, "markup": 0, "tax": 0, "grand_total": 0,
                },
            }

        # Also clear old EstimateLineItem records (legacy)
        db.query(EstimateLineItem).filter(EstimateLineItem.project_id == project_id).delete()

        conditions_breakdown = []
        consolidated = {}  # material_name+unit → aggregated data
        grand_materials_total = 0.0
        errors = []

        for condition in conditions:
            materials = db.query(ConditionMaterial).filter(
                ConditionMaterial.condition_id == condition.id
            ).order_by(ConditionMaterial.sort_order).all()

            ct_info = CONDITION_TYPES.get(condition.condition_type, {"label": condition.condition_type})
            condition_total = 0.0
            material_rows = []

            for mat in materials:
                if not mat.is_included:
                    material_rows.append({
                        "id": mat.id,
                        "material_name": mat.material_name,
                        "material_category": mat.material_category,
                        "unit": mat.unit,
                        "coverage_rate": mat.coverage_rate,
                        "waste_factor": mat.waste_factor,
                        "qty_calculated": 0,
                        "unit_cost": 0,
                        "labor_cost": 0,
                        "extended": 0,
                        "is_included": False,
                        "override_quantity": mat.override_quantity,
                        "notes": mat.notes,
                    })
                    continue

                qty = _calculate_quantity(condition, mat)

                # Look up cost (smart matching with fallback)
                cost_item = _find_cost_item(
                    mat.material_name, mat.unit, project.org_id, db
                )

                unit_cost = 0.0
                labor_cost = 0.0
                if cost_item:
                    unit_cost = cost_item.unit_cost or 0
                    labor_cost = cost_item.labor_cost_per_unit or 0
                else:
                    errors.append(f"No cost found for '{mat.material_name}' ({mat.unit})")

                extended = round(qty * (unit_cost + labor_cost), 2)
                condition_total += extended
                grand_materials_total += extended

                material_rows.append({
                    "id": mat.id,
                    "material_name": mat.material_name,
                    "material_category": mat.material_category,
                    "unit": mat.unit,
                    "coverage_rate": mat.coverage_rate,
                    "waste_factor": mat.waste_factor,
                    "qty_calculated": round(qty, 2),
                    "unit_cost": unit_cost,
                    "labor_cost": labor_cost,
                    "extended": extended,
                    "is_included": True,
                    "override_quantity": mat.override_quantity,
                    "notes": mat.notes,
                })

                # Aggregate into consolidated
                key = f"{mat.material_name}|{mat.unit}"
                if key not in consolidated:
                    # Pull purchase unit conversion from cost item
                    p_unit = None
                    p_per = None
                    p_name = None
                    if cost_item:
                        p_unit = getattr(cost_item, 'purchase_unit', None)
                        p_per = getattr(cost_item, 'units_per_purchase', None)
                        p_name = getattr(cost_item, 'product_name', None)

                    consolidated[key] = {
                        "material_name": mat.material_name,
                        "material_category": mat.material_category,
                        "unit": mat.unit,
                        "total_qty": 0,
                        "unit_cost": unit_cost,
                        "labor_cost": labor_cost,
                        "total_cost": 0,
                        "waste_pct": mat.waste_factor or 0,
                        "purchase_unit": p_unit,
                        "units_per_purchase": p_per,
                        "product_name": p_name,
                    }
                consolidated[key]["total_qty"] = round(consolidated[key]["total_qty"] + qty, 2)
                consolidated[key]["total_cost"] = round(consolidated[key]["total_cost"] + extended, 2)

                # Also write legacy EstimateLineItem for backward compat
                line_item = EstimateLineItem(
                    project_id=project_id,
                    condition_id=condition.id,
                    material_name=mat.material_name,
                    material_category=mat.material_category,
                    quantity=round(qty, 2),
                    unit=mat.unit,
                    unit_cost=unit_cost + labor_cost,
                    total_cost=extended,
                    notes=f"[{system_type}] {condition.description or ct_info['label']}"
                )
                db.add(line_item)

            conditions_breakdown.append({
                "condition": {
                    "id": condition.id,
                    "type": condition.condition_type,
                    "label": ct_info["label"],
                    "description": condition.description,
                    "measurement": condition.measurement_value,
                    "unit": condition.measurement_unit,
                    "flashing_height": condition.flashing_height,
                    "fastener_spacing": condition.fastener_spacing,
                },
                "materials": material_rows,
                "condition_total": round(condition_total, 2),
            })

        db.commit()

        # Build consolidated list with purchase unit conversions
        import math
        for item in consolidated.values():
            p_unit = item.get("purchase_unit")
            p_per = item.get("units_per_purchase")
            if p_unit and p_per and p_per > 0:
                item["purchase_qty"] = math.ceil(item["total_qty"] / p_per)
                # Recalculate extended cost based on purchase qty × units_per_purchase × unit_cost
                item["purchase_cost"] = round(
                    item["purchase_qty"] * p_per * (item["unit_cost"] + item["labor_cost"]), 2
                )
            else:
                item["purchase_qty"] = math.ceil(item["total_qty"])
                item["purchase_cost"] = item["total_cost"]

        consolidated_list = sorted(consolidated.values(), key=lambda x: (x["material_category"], x["material_name"]))

        # Calculate totals
        # Labor: estimate at $85/square for field area
        field_area = sum(
            c.measurement_value for c in conditions
            if c.condition_type == "field" and c.measurement_unit == "sqft"
        )
        squares = field_area / 100.0
        labor_rate = 85.00  # per square
        labor_total = round(squares * labor_rate, 2)

        subtotal = round(grand_materials_total + labor_total, 2)
        markup_pct = 0.25
        markup = round(subtotal * markup_pct, 2)
        subtotal_with_markup = round(subtotal + markup, 2)
        tax_pct = 0.0825
        tax = round(grand_materials_total * (1 + markup_pct) * tax_pct, 2)
        grand_total = round(subtotal_with_markup + tax, 2)

        # Parse spec for summary info
        spec = {}
        if project.analysis_result:
            try:
                spec = json.loads(project.analysis_result) if isinstance(project.analysis_result, str) else project.analysis_result
            except:
                spec = {}

        return {
            "status": "success",
            "system_type": system_type,
            "summary": {
                "project_name": project.project_name,
                "address": project.address or "",
                "system_type": system_type,
                "roof_area_sf": field_area,
                "roof_area_sq": round(squares, 2),
                "materials_total": round(grand_materials_total, 2),
                "labor_total": labor_total,
                "subtotal": subtotal,
                "markup_pct": markup_pct,
                "markup": markup,
                "subtotal_with_markup": subtotal_with_markup,
                "tax_pct": tax_pct,
                "tax": tax,
                "grand_total": grand_total,
                "cost_summary": {
                    "flat_materials": round(grand_materials_total, 2),
                    "metals": 0,
                    "labor": labor_total,
                    "warranty": 0,
                    "subtotal": subtotal,
                    "markup_pct": markup_pct,
                    "markup": markup,
                    "subtotal_with_markup": subtotal_with_markup,
                    "tax_pct": tax_pct,
                    "tax": tax,
                    "grand_total": grand_total,
                },
            },
            "conditions_breakdown": conditions_breakdown,
            "consolidated_materials": consolidated_list,
            "errors": errors if errors else None,
        }

    except Exception as e:
        db.rollback()
        import traceback
        traceback.print_exc()
        return {"status": "error", "message": f"Failed to calculate estimate: {str(e)}"}


# ============================================================================
# ESTIMATE SUMMARY (backward compat — now just calls calculate_estimate)
# ============================================================================

def get_estimate_summary(project_id: int, db: Session) -> Dict:
    """Generate estimate summary. Now delegates to calculate_estimate."""
    return calculate_estimate(project_id, db)


# ============================================================================
# HELPER FUNCTIONS (kept for backward compat with router imports)
# ============================================================================

def get_available_condition_types(db: Session) -> List[str]:
    """Get all unique condition types that have active material templates."""
    templates = db.query(MaterialTemplate.condition_type).filter(
        MaterialTemplate.is_active == True
    ).distinct().all()
    return [t[0] for t in templates]


def get_materials_for_condition(condition_type: str, db: Session, system_type: str = None) -> List[Dict]:
    """Get all active material templates for a specific condition type."""
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
