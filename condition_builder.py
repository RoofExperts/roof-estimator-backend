"""
Smart Condition Builder - Bridges spec analysis + plan vision data
to auto-generate complete, system-aware roof conditions.

Flow:
1. Read spec analysis → determine system type, insulation, attachment, etc.
2. Read plan extractions → get measurements (area, perimeter, penetrations)
3. Create conditions with proper descriptions referencing the actual spec materials
4. Set project.system_type so the estimate engine uses the right material templates
"""

import json
from sqlalchemy.orm import Session
from models import Project
from conditions_models import RoofCondition
from vision_models import RoofPlanFile, VisionExtraction


# ============================================================================
# SPEC DATA PARSER
# ============================================================================

def parse_spec_data(project: Project) -> dict:
    """
    Parse the spec analysis_result JSON into a structured dict.
    Returns a dict with normalized roofing spec fields.
    """
    defaults = {
        "system_type": None,
        "membrane_type": None,
        "membrane_thickness": None,
        "attachment_method": None,
        "insulation_type": None,
        "insulation_layers": None,
        "cover_board": None,
        "fastening_pattern": None,
        "warranty_years": None,
        "manufacturer": None,
        "special_requirements": None,
    }

    if not project.analysis_result:
        return defaults

    try:
        spec = json.loads(project.analysis_result) if isinstance(project.analysis_result, str) else project.analysis_result
        if isinstance(spec, dict) and "error" not in spec:
            for key in defaults:
                if key in spec and spec[key]:
                    defaults[key] = spec[key]
    except (json.JSONDecodeError, TypeError):
        pass

    return defaults


def detect_system_from_spec(spec_data: dict) -> str:
    """Determine TPO/EPDM/PVC from spec data. Returns uppercase system name."""
    membrane = (spec_data.get("membrane_type") or "").upper()
    system = (spec_data.get("system_type") or "").upper()
    combined = membrane + " " + system

    if "EPDM" in combined:
        return "EPDM"
    if "PVC" in combined or "KEE" in combined or "SARNAFIL" in combined:
        return "PVC"
    if "TPO" in combined:
        return "TPO"

    # Try manufacturer hints
    mfr = (spec_data.get("manufacturer") or "").upper()
    if "FIRESTONE" in mfr:
        return "EPDM"
    if "SARNAFIL" in mfr or "SIKA" in mfr:
        return "PVC"

    return "TPO"  # Default


# ============================================================================
# EXTRACTION TYPE → CONDITION MAPPING (enhanced from vision_ai.py)
# ============================================================================

EXTRACTION_TO_CONDITION = {
    # From slab plan
    "roof_area": {"condition_type": "field", "unit": "sqft"},
    "building_area": {"condition_type": "field", "unit": "sqft"},
    "building_dimensions": {"condition_type": "field", "unit": "sqft"},
    "parapet_wall": {"condition_type": "edge_detail", "unit": "lnft"},
    "coping": {"condition_type": "edge_detail", "unit": "lnft"},

    # From roof plan
    "roof_drain": {"condition_type": "penetration", "unit": "each"},
    "roof_drains": {"condition_type": "penetration", "unit": "each"},
    "scupper": {"condition_type": "penetration", "unit": "each"},
    "scuppers": {"condition_type": "penetration", "unit": "each"},
    "pitch_pan": {"condition_type": "penetration", "unit": "each"},
    "pitch_pans": {"condition_type": "penetration", "unit": "each"},
    "pipe": {"condition_type": "penetration", "unit": "each"},
    "pipes": {"condition_type": "penetration", "unit": "each"},
    "curb": {"condition_type": "penetration", "unit": "lnft"},
    "curbs": {"condition_type": "penetration", "unit": "lnft"},
    "rooftop_equipment": {"condition_type": "penetration", "unit": "each"},
    "rooftop_equipment_count": {"condition_type": "penetration", "unit": "each"},

    # From elevations
    "parapet_flashing": {"condition_type": "edge_detail", "unit": "lnft"},
    "parapet_flashing_low": {"condition_type": "edge_detail", "unit": "lnft"},
    "parapet_flashing_mid": {"condition_type": "edge_detail", "unit": "lnft"},
    "parapet_flashing_high": {"condition_type": "edge_detail", "unit": "lnft"},
    "collector_head": {"condition_type": "custom", "unit": "each"},
    "collector_heads": {"condition_type": "custom", "unit": "each"},
    "downspout": {"condition_type": "custom", "unit": "lnft"},
    "downspouts": {"condition_type": "custom", "unit": "lnft"},

    # Legacy
    "perimeter": {"condition_type": "perimeter", "unit": "lnft"},
    "penetration": {"condition_type": "penetration", "unit": "each"},
    "flashing": {"condition_type": "edge_detail", "unit": "lnft"},
    "drain": {"condition_type": "penetration", "unit": "each"},
    "equipment": {"condition_type": "penetration", "unit": "each"},
}

# Types to skip (informational only, no material impact)
SKIP_TYPES = {"slope", "insulation", "parapet_height"}


# ============================================================================
# SMART CONDITION BUILDER: auto-perimeter from roof area
# ============================================================================

def estimate_perimeter_from_area(area_sqft: float) -> float:
    """
    Estimate roof perimeter from area assuming a roughly rectangular building.
    Uses a 1.5:1 length-to-width ratio (common for commercial).
    perimeter = 2 * (L + W) where area = L * W and L = 1.5 * W
    """
    if area_sqft <= 0:
        return 0
    import math
    w = math.sqrt(area_sqft / 1.5)
    l = 1.5 * w
    return round(2 * (l + w))


# ============================================================================
# MAIN BUILD FUNCTION
# ============================================================================

def smart_build_conditions(project_id: int, db: Session) -> dict:
    """
    Build conditions intelligently from spec + plan data.

    Steps:
    1. Parse spec analysis to determine system type and materials
    2. Set project.system_type from spec
    3. Gather all plan extractions for the project
    4. Create conditions with spec-enriched descriptions
    5. Auto-generate perimeter condition if we have area but no perimeter
    6. Return summary of what was created

    Returns:
        dict with status, system_type, conditions_created, and details
    """
    project = db.query(Project).filter(Project.id == project_id).first()
    if not project:
        return {"status": "error", "message": f"Project {project_id} not found"}

    # Step 1: Parse spec data
    spec_data = parse_spec_data(project)
    system_type = detect_system_from_spec(spec_data)

    # Step 2: Set system_type on project
    project.system_type = system_type
    db.commit()
    print(f"[ConditionBuilder] Project {project_id} system: {system_type}")

    # Build description enrichments from spec
    membrane_desc = spec_data.get("membrane_type") or system_type
    thickness = spec_data.get("membrane_thickness") or ""
    attachment = spec_data.get("attachment_method") or ""
    insulation = spec_data.get("insulation_type") or ""
    cover_board = spec_data.get("cover_board") or ""

    spec_summary = f"{membrane_desc}"
    if thickness:
        spec_summary += f" {thickness}"
    if attachment:
        spec_summary += f", {attachment}"

    # Step 3: Delete existing AI-generated conditions (keep manual ones)
    existing_ai = db.query(RoofCondition).filter(
        RoofCondition.project_id == project_id,
        RoofCondition.description.like("%[AI%")
    ).all()
    for c in existing_ai:
        db.delete(c)
    db.commit()

    # Step 4: Gather plan extractions
    plan_files = db.query(RoofPlanFile).filter(
        RoofPlanFile.project_id == project_id,
        RoofPlanFile.upload_status == "completed"
    ).all()

    all_extractions = []
    for pf in plan_files:
        exts = db.query(VisionExtraction).filter(
            VisionExtraction.plan_file_id == pf.id
        ).all()
        all_extractions.extend(exts)

    # Step 5: Create conditions from extractions
    created = []
    has_field = False
    has_perimeter = False
    field_area = 0

    for ext in all_extractions:
        if ext.extraction_type in SKIP_TYPES:
            continue

        mapping = EXTRACTION_TO_CONDITION.get(ext.extraction_type)
        if not mapping:
            continue

        ctype = mapping["condition_type"]
        unit = mapping["unit"]

        # Track field/perimeter for auto-generation
        if ctype == "field" and unit == "sqft":
            has_field = True
            field_area = max(field_area, ext.measurement_value)
        if ctype == "perimeter":
            has_perimeter = True

        # Build rich description
        desc_parts = [f"[AI/{system_type}] {ext.extraction_type}"]
        if ext.location_on_plan:
            desc_parts.append(ext.location_on_plan)
        if ctype == "field" and insulation:
            desc_parts.append(f"Insulation: {insulation}")
        if ctype == "field" and cover_board:
            desc_parts.append(f"Cover board: {cover_board}")
        if ext.confidence_score:
            desc_parts.append(f"confidence: {ext.confidence_score:.0%}")

        description = " | ".join(desc_parts)

        condition = RoofCondition(
            project_id=project_id,
            condition_type=ctype,
            description=description,
            measurement_value=ext.measurement_value,
            measurement_unit=unit,
            wind_zone="1",
        )
        db.add(condition)
        db.flush()

        # Link extraction to condition
        ext.condition_id = condition.id

        created.append({
            "id": condition.id,
            "type": ctype,
            "extraction_type": ext.extraction_type,
            "value": ext.measurement_value,
            "unit": unit,
            "description": description,
        })

    # Step 6: Auto-generate perimeter if we have area but no perimeter
    if has_field and not has_perimeter and field_area > 0:
        est_perimeter = estimate_perimeter_from_area(field_area)
        if est_perimeter > 0:
            perim_condition = RoofCondition(
                project_id=project_id,
                condition_type="perimeter",
                description=f"[AI/{system_type}] Auto-estimated perimeter from {field_area:,.0f} sqft roof area",
                measurement_value=est_perimeter,
                measurement_unit="lnft",
                wind_zone="1",
            )
            db.add(perim_condition)
            db.flush()
            created.append({
                "id": perim_condition.id,
                "type": "perimeter",
                "extraction_type": "auto_perimeter",
                "value": est_perimeter,
                "unit": "lnft",
                "description": perim_condition.description,
            })
            print(f"[ConditionBuilder] Auto-generated perimeter: {est_perimeter} lnft from {field_area} sqft")

    db.commit()

    return {
        "status": "success",
        "project_id": project_id,
        "system_type": system_type,
        "spec_data": {
            "membrane": membrane_desc,
            "thickness": thickness,
            "attachment": attachment,
            "insulation": insulation,
            "cover_board": cover_board,
            "warranty": spec_data.get("warranty_years"),
            "manufacturer": spec_data.get("manufacturer"),
        },
        "conditions_created": len(created),
        "conditions": created,
    }
