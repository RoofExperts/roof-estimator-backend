"""
Smart Condition Builder - Bridges spec analysis + plan vision data
to auto-generate complete, system-aware roof conditions WITH materials.

Flow:
1. Read spec analysis → determine system type, insulation, attachment, etc.
2. Read plan extractions → get measurements (area, perimeter, penetrations)
3. Create conditions with proper types (field, wall_flashing, roof_drain, etc.)
4. Auto-populate ConditionMaterial rows for each condition from MaterialTemplates
5. Use spec R-value target to select insulation products from cost database
6. Set project.system_type so the estimate engine uses the right materials
"""

import json
import math
import re
from sqlalchemy.orm import Session
from sqlalchemy import or_
from models import Project
from conditions_models import (
    RoofCondition, MaterialTemplate, ConditionMaterial, CostDatabaseItem, CONDITION_TYPES
)
from vision_models import RoofPlanFile, VisionExtraction


# ============================================================================
# SPEC DATA PARSER
# ============================================================================

def parse_spec_data(project: Project) -> dict:
    """Parse the spec analysis_result JSON into a structured dict."""
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
    """Determine TPO/EPDM/PVC from spec data. Returns system name."""
    membrane = (spec_data.get("membrane_type") or "").upper()
    system = (spec_data.get("system_type") or "").upper()
    combined = membrane + " " + system

    if "EPDM" in combined:
        return "EPDM"
    if "PVC" in combined or "KEE" in combined or "SARNAFIL" in combined:
        return "PVC"
    if "TPO" in combined:
        return "TPO"

    mfr = (spec_data.get("manufacturer") or "").upper()
    if "FIRESTONE" in mfr:
        return "EPDM"
    if "SARNAFIL" in mfr or "SIKA" in mfr:
        return "PVC"

    return "TPO"


# ============================================================================
# EXTRACTION TYPE → CONDITION MAPPING (updated for new condition types)
# ============================================================================

EXTRACTION_TO_CONDITION = {
    # From slab/roof plan — field areas
    "roof_area":              {"condition_type": "field",          "unit": "sqft"},
    "building_area":          {"condition_type": "field",          "unit": "sqft"},
    "building_dimensions":    {"condition_type": "field",          "unit": "sqft"},

    # Perimeter / edge
    "perimeter":              {"condition_type": "perimeter",      "unit": "lnft"},
    "parapet_wall":           {"condition_type": "coping",         "unit": "lnft"},
    "coping":                 {"condition_type": "coping",         "unit": "lnft"},
    "parapet_flashing":       {"condition_type": "wall_flashing",  "unit": "lnft"},
    "parapet_flashing_low":   {"condition_type": "wall_flashing",  "unit": "lnft"},
    "parapet_flashing_mid":   {"condition_type": "wall_flashing",  "unit": "lnft"},
    "parapet_flashing_high":  {"condition_type": "wall_flashing",  "unit": "lnft"},

    # Drains & scuppers (their own condition types now)
    "roof_drain":             {"condition_type": "roof_drain",     "unit": "each"},
    "roof_drains":            {"condition_type": "roof_drain",     "unit": "each"},
    "drain":                  {"condition_type": "roof_drain",     "unit": "each"},
    "scupper":                {"condition_type": "scupper",        "unit": "each"},
    "scuppers":               {"condition_type": "scupper",        "unit": "each"},

    # Pipe flashings
    "pipe":                   {"condition_type": "pipe_flashing",  "unit": "each"},
    "pipes":                  {"condition_type": "pipe_flashing",  "unit": "each"},

    # Pitch pans (separate condition type with sealant pocket + pourable sealer)
    "pitch_pan":              {"condition_type": "pitch_pan",      "unit": "each"},
    "pitch_pans":             {"condition_type": "pitch_pan",      "unit": "each"},

    # Penetrations (generic)
    "penetration":            {"condition_type": "penetration",    "unit": "each"},
    "rooftop_equipment":      {"condition_type": "penetration",    "unit": "each"},
    "rooftop_equipment_count":{"condition_type": "penetration",    "unit": "each"},

    # Curbs
    "curb":                   {"condition_type": "curb",           "unit": "lnft"},
    "curbs":                  {"condition_type": "curb",           "unit": "lnft"},

    # From elevations
    "collector_head":         {"condition_type": "custom",         "unit": "each"},
    "collector_heads":        {"condition_type": "custom",         "unit": "each"},
    "downspout":              {"condition_type": "custom",         "unit": "lnft"},
    "downspouts":             {"condition_type": "custom",         "unit": "lnft"},

    # Legacy mappings
    "flashing":               {"condition_type": "wall_flashing",  "unit": "lnft"},
    "equipment":              {"condition_type": "penetration",    "unit": "each"},
    "edge_detail":            {"condition_type": "edge_detail",    "unit": "lnft"},
    "transition":             {"condition_type": "transition",     "unit": "lnft"},
}

# Types to skip (informational only, no material impact)
SKIP_TYPES = {"slope", "insulation", "parapet_height"}


# ============================================================================
# HELPERS
# ============================================================================

def estimate_perimeter_from_area(area_sqft: float) -> float:
    """Estimate roof perimeter from area assuming 1.5:1 length-to-width ratio."""
    if area_sqft <= 0:
        return 0
    w = math.sqrt(area_sqft / 1.5)
    l = 1.5 * w
    return round(2 * (l + w))


def _populate_materials_for_condition(
    condition: RoofCondition, system_type: str, org_id: int,
    db: Session, spec_data: dict = None
) -> int:
    """
    Populate ConditionMaterial rows for a condition from MaterialTemplates.
    Uses sort_order from templates for proper build-up stack ordering.
    Copies is_optional so the frontend knows which layers are toggleable.
    For field conditions, attempts R-value-aware insulation selection.
    Returns the number of materials added.
    """
    if spec_data is None:
        spec_data = {}

    # ── Prefer org-specific templates; fall back to global ──
    # Pull org-specific first, then global, and de-duplicate by name+category
    templates = db.query(MaterialTemplate).filter(
        MaterialTemplate.condition_type == condition.condition_type,
        MaterialTemplate.is_active == True,
        or_(
            MaterialTemplate.system_type == system_type,
            MaterialTemplate.system_type == "common"
        ),
        or_(
            MaterialTemplate.org_id == org_id,
            MaterialTemplate.is_global == True
        )
    ).order_by(
        MaterialTemplate.sort_order.asc(),
        MaterialTemplate.material_name.asc()
    ).all()

    # De-duplicate: org-specific overrides global template of same name+category
    seen = {}
    deduped = []
    for tmpl in templates:
        key = (tmpl.material_name, tmpl.material_category)
        if key in seen:
            # Keep org-specific over global
            if tmpl.org_id == org_id and seen[key].is_global:
                deduped = [t for t in deduped if (t.material_name, t.material_category) != key]
                deduped.append(tmpl)
                seen[key] = tmpl
        else:
            seen[key] = tmpl
            deduped.append(tmpl)

    added = 0
    for tmpl in deduped:
        cm = ConditionMaterial(
            condition_id=condition.id,
            material_template_id=tmpl.id,
            material_name=tmpl.material_name,
            material_category=tmpl.material_category,
            unit=tmpl.unit,
            coverage_rate=tmpl.coverage_rate,
            waste_factor=tmpl.waste_factor,
            calc_type=tmpl.calc_type,
            is_included=not tmpl.is_optional,   # Optional items start toggled OFF
            sort_order=tmpl.sort_order,          # Preserve build-up stack order
            notes=_build_material_notes(tmpl, spec_data),
        )
        db.add(cm)
        added += 1

    # ── For field conditions: try to select specific insulation products ──
    if condition.condition_type == "field":
        _try_assign_insulation_products(condition, spec_data, org_id, db)

    return added


def _build_material_notes(tmpl: MaterialTemplate, spec_data: dict) -> str:
    """Build notes string for a ConditionMaterial based on spec context."""
    notes_parts = []
    cat = tmpl.material_category

    if cat == "insulation" and spec_data.get("insulation_type"):
        notes_parts.append(f"Spec: {spec_data['insulation_type']}")
    if cat == "membrane" and spec_data.get("membrane_thickness"):
        notes_parts.append(f"Spec: {spec_data['membrane_thickness']}")
    if cat in ("fastener", "adhesive") and spec_data.get("attachment_method"):
        notes_parts.append(f"Spec: {spec_data['attachment_method']}")

    return " | ".join(notes_parts) if notes_parts else None


# ============================================================================
# R-VALUE INSULATION SELECTION
# ============================================================================

def _parse_r_value_from_notes(notes: str) -> float:
    """Extract R-value from a cost database item's notes field. Returns 0 if not found."""
    if not notes:
        return 0.0
    match = re.search(r'R-(\d+\.?\d*)', notes, re.IGNORECASE)
    return float(match.group(1)) if match else 0.0


def _parse_r_value_from_spec(spec_data: dict) -> float:
    """
    Try to extract a target R-value from the spec data.
    Specs often say things like 'R-30 minimum' in insulation_layers or special_requirements.
    """
    for field in ("insulation_layers", "special_requirements", "insulation_type"):
        text = spec_data.get(field) or ""
        match = re.search(r'R-?(\d+\.?\d*)', text, re.IGNORECASE)
        if match:
            return float(match.group(1))
    return 0.0


def _try_assign_insulation_products(
    condition: RoofCondition, spec_data: dict, org_id: int, db: Session
):
    """
    If the spec calls for a target R-value and specific insulation type,
    find matching products from the cost database and annotate the
    insulation ConditionMaterial rows with recommended products.

    This doesn't auto-swap products (user still picks), but adds notes
    like 'Recommended: InsulBase HD Polyiso 2.6" (R-15.6) + 2.6" (R-15.6) = R-31.2'
    """
    target_r = _parse_r_value_from_spec(spec_data)
    if target_r <= 0:
        return

    insulation_type = (spec_data.get("insulation_type") or "").lower()

    # Determine preferred insulation category from spec
    preferred_keywords = []
    if "polyiso" in insulation_type or "iso" in insulation_type:
        preferred_keywords = ["polyiso", "insulbase"]
    elif "eps" in insulation_type:
        preferred_keywords = ["eps", "insulfoam"]
    elif "xps" in insulation_type:
        preferred_keywords = ["xps", "foamular"]

    # Query cost database for insulation products with R-values
    insulation_items = db.query(CostDatabaseItem).filter(
        CostDatabaseItem.material_category == "insulation",
        CostDatabaseItem.is_active == True,
        or_(
            CostDatabaseItem.org_id == org_id,
            CostDatabaseItem.is_global == True
        )
    ).all()

    # Filter to items with R-values and optionally matching type
    candidates = []
    for item in insulation_items:
        # Check both description and notes fields for R-value
        r_val = _parse_r_value_from_notes(item.description) or _parse_r_value_from_notes(item.notes)
        if r_val <= 0:
            continue
        name_lower = item.material_name.lower()
        # Score by preference match
        score = 0
        for kw in preferred_keywords:
            if kw in name_lower:
                score = 10
                break
        candidates.append((item, r_val, score))

    if not candidates:
        return

    # Sort by preference score (desc) then R-value (desc) for greedy selection
    candidates.sort(key=lambda x: (-x[2], -x[1]))

    # Greedy: pick highest R-value boards that sum to target
    # Try two-layer combo first (most common in commercial roofing)
    best_combo = None
    best_total_r = 0

    for i, (item1, r1, s1) in enumerate(candidates):
        if r1 >= target_r:
            # Single layer achieves target
            if best_combo is None or r1 < best_total_r:
                best_combo = [(item1, r1)]
                best_total_r = r1
            continue
        for j, (item2, r2, s2) in enumerate(candidates):
            total = r1 + r2
            if total >= target_r:
                if best_combo is None or total < best_total_r or (total == best_total_r and s1 + s2 > sum(x[2] for x in (best_combo or []))):
                    best_combo = [(item1, r1), (item2, r2)]
                    best_total_r = total
                    break

    if not best_combo:
        return

    # Annotate the insulation ConditionMaterial rows with recommendations
    insulation_cms = db.query(ConditionMaterial).filter(
        ConditionMaterial.condition_id == condition.id,
        ConditionMaterial.material_category == "insulation"
    ).order_by(ConditionMaterial.sort_order).all()

    combo_desc = " + ".join([f"{item.material_name} (R-{r:.1f})" for item, r in best_combo])
    recommendation = f"Target R-{target_r:.0f} → {combo_desc} = R-{best_total_r:.1f}"

    for idx, cm in enumerate(insulation_cms):
        if idx < len(best_combo):
            item, r_val = best_combo[idx]
            cm.notes = f"Recommended: {item.material_name} (R-{r_val:.1f}) | {recommendation}"
            cm.is_included = True  # Turn on insulation layers when we have a recommendation
        else:
            cm.notes = recommendation


# ============================================================================
# MAIN BUILD FUNCTION
# ============================================================================

def smart_build_conditions(project_id: int, db: Session, org_id: int = None) -> dict:
    """
    Build conditions from spec + plan data, then auto-populate materials.

    Steps:
    1. Parse spec analysis to determine system type and materials
    2. Set project.system_type from spec
    3. Delete existing AI-generated conditions (and their materials)
    4. Gather all plan extractions for the project
    5. Create conditions with proper types (field, wall_flashing, roof_drain, etc.)
    6. Auto-populate ConditionMaterial rows for each condition
    7. Auto-generate perimeter + coping conditions if we have area but no perimeter
    """
    project = db.query(Project).filter(Project.id == project_id).first()
    if not project:
        return {"status": "error", "message": f"Project {project_id} not found"}

    # Use org_id from parameter or project
    if not org_id:
        org_id = getattr(project, 'org_id', None) or 1

    # Step 1: Parse spec data
    spec_data = parse_spec_data(project)
    system_type = detect_system_from_spec(spec_data)

    # If project already has a system_type set (user override), keep it
    if project.system_type:
        system_type = project.system_type
    else:
        project.system_type = system_type
    db.commit()
    print(f"[ConditionBuilder] Project {project_id} system: {system_type}")

    membrane_desc = spec_data.get("membrane_type") or system_type
    thickness = spec_data.get("membrane_thickness") or ""
    attachment = spec_data.get("attachment_method") or ""
    insulation = spec_data.get("insulation_type") or ""
    cover_board = spec_data.get("cover_board") or ""

    # Step 3: Delete existing AI-generated conditions + their materials
    existing_ai = db.query(RoofCondition).filter(
        RoofCondition.project_id == project_id,
        RoofCondition.description.like("%[AI%")
    ).all()
    for c in existing_ai:
        db.query(ConditionMaterial).filter(ConditionMaterial.condition_id == c.id).delete()
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
    has_coping = False
    has_wall_flashing = False
    field_area = 0
    total_materials = 0

    for ext in all_extractions:
        if ext.extraction_type in SKIP_TYPES:
            continue

        mapping = EXTRACTION_TO_CONDITION.get(ext.extraction_type)
        if not mapping:
            continue

        ctype = mapping["condition_type"]
        unit = mapping["unit"]

        # Track for auto-generation
        if ctype == "field" and unit == "sqft":
            has_field = True
            field_area = max(field_area, ext.measurement_value)
        if ctype == "perimeter":
            has_perimeter = True
        if ctype == "coping":
            has_coping = True
        if ctype == "wall_flashing":
            has_wall_flashing = True

        # Build description
        ct_info = CONDITION_TYPES.get(ctype, {"label": ctype})
        desc_parts = [f"[AI/{system_type}] {ct_info['label']}"]
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

        # Step 6: Auto-populate materials for this condition
        mat_count = _populate_materials_for_condition(condition, system_type, org_id, db, spec_data)
        total_materials += mat_count

        created.append({
            "id": condition.id,
            "type": ctype,
            "label": ct_info["label"],
            "extraction_type": ext.extraction_type,
            "value": ext.measurement_value,
            "unit": unit,
            "description": description,
            "materials_count": mat_count,
        })

    # Step 7: Auto-generate perimeter if we have area but no perimeter
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
            mat_count = _populate_materials_for_condition(perim_condition, system_type, org_id, db, spec_data)
            total_materials += mat_count
            created.append({
                "id": perim_condition.id,
                "type": "perimeter",
                "label": "Perimeter",
                "extraction_type": "auto_perimeter",
                "value": est_perimeter,
                "unit": "lnft",
                "description": perim_condition.description,
                "materials_count": mat_count,
            })
            print(f"[ConditionBuilder] Auto-generated perimeter: {est_perimeter} lnft")

    # Auto-generate wall flashing from perimeter if not found
    if has_field and not has_wall_flashing and field_area > 0:
        est_perim = estimate_perimeter_from_area(field_area)
        # Assume ~60% of perimeter has wall flashing
        wall_lf = round(est_perim * 0.6)
        if wall_lf > 0:
            wall_condition = RoofCondition(
                project_id=project_id,
                condition_type="wall_flashing",
                description=f"[AI/{system_type}] Auto-estimated wall flashing (~60% of perimeter)",
                measurement_value=wall_lf,
                measurement_unit="lnft",
                wind_zone="1",
                flashing_height=60.0,
                fastener_spacing=12,
            )
            db.add(wall_condition)
            db.flush()
            mat_count = _populate_materials_for_condition(wall_condition, system_type, org_id, db, spec_data)
            total_materials += mat_count
            created.append({
                "id": wall_condition.id,
                "type": "wall_flashing",
                "label": "Wall Flashings",
                "extraction_type": "auto_wall_flashing",
                "value": wall_lf,
                "unit": "lnft",
                "description": wall_condition.description,
                "materials_count": mat_count,
            })

    # Auto-generate coping from perimeter if not found
    if has_field and not has_coping and field_area > 0:
        est_perim = estimate_perimeter_from_area(field_area)
        if est_perim > 0:
            coping_condition = RoofCondition(
                project_id=project_id,
                condition_type="coping",
                description=f"[AI/{system_type}] Auto-estimated coping (full perimeter)",
                measurement_value=est_perim,
                measurement_unit="lnft",
                wind_zone="1",
            )
            db.add(coping_condition)
            db.flush()
            mat_count = _populate_materials_for_condition(coping_condition, system_type, org_id, db, spec_data)
            total_materials += mat_count
            created.append({
                "id": coping_condition.id,
                "type": "coping",
                "label": "Coping",
                "extraction_type": "auto_coping",
                "value": est_perim,
                "unit": "lnft",
                "description": coping_condition.description,
                "materials_count": mat_count,
            })

    db.commit()

    target_r = _parse_r_value_from_spec(spec_data)

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
            "target_r_value": target_r if target_r > 0 else None,
        },
        "conditions_created": len(created),
        "materials_populated": total_materials,
        "conditions": created,
    }
