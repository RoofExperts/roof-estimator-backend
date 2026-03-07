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
    RoofCondition, RoofSystem, MaterialTemplate, ConditionMaterial, CostDatabaseItem, CONDITION_TYPES
)
from system_templates import get_system_conditions
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
    membrane = _safe_str(spec_data.get("membrane_type")).upper()
    system = _safe_str(spec_data.get("system_type")).upper()
    combined = membrane + " " + system

    if "EPDM" in combined:
        return "EPDM"
    if "PVC" in combined or "KEE" in combined or "SARNAFIL" in combined:
        return "PVC"
    if "TPO" in combined:
        return "TPO"

    mfr = _safe_str(spec_data.get("manufacturer")).upper()
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

    # ── Prefer system-specific templates over "common", org-specific over global ──
    # Pull system-specific first, then common, and de-duplicate intelligently
    OTHER_SYSTEMS = {"TPO", "EPDM", "PVC", "ModBit", "BUR", "StandingSeam"}
    wrong_systems = OTHER_SYSTEMS - {system_type}

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

    # Filter out "common" templates whose name contains a WRONG system type
    # (e.g. "TPO 60mil Membrane" in common when project is PVC)
    def _belongs_to_wrong_system(tmpl):
        if tmpl.system_type != "common":
            return False
        name_upper = tmpl.material_name.upper()
        for ws in wrong_systems:
            if ws.upper() in name_upper:
                return True
        return False

    templates = [t for t in templates if not _belongs_to_wrong_system(t)]

    # Split into system-specific and common templates
    system_templates = [t for t in templates if t.system_type == system_type]
    common_templates = [t for t in templates if t.system_type == "common"]

    # Use system-specific templates as the primary set.
    # Only add common templates for categories NOT already covered by system-specific.
    system_categories = {t.material_category for t in system_templates}

    deduped = list(system_templates)
    for tmpl in common_templates:
        if tmpl.material_category not in system_categories:
            deduped.append(tmpl)

    # Final dedup by name+category: org-specific overrides global
    seen = {}
    final = []
    for tmpl in deduped:
        name_key = (tmpl.material_name, tmpl.material_category)
        if name_key in seen:
            existing = seen[name_key]
            if tmpl.org_id == org_id and existing.is_global:
                final = [t for t in final if (t.material_name, t.material_category) != name_key]
                final.append(tmpl)
                seen[name_key] = tmpl
        else:
            seen[name_key] = tmpl
            final.append(tmpl)
    deduped = final

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
        notes_parts.append(f"Spec: {_safe_str(spec_data['insulation_type'])}")
    if cat == "membrane" and spec_data.get("membrane_thickness"):
        notes_parts.append(f"Spec: {_safe_str(spec_data['membrane_thickness'])}")
    if cat in ("fastener", "adhesive") and spec_data.get("attachment_method"):
        notes_parts.append(f"Spec: {_safe_str(spec_data['attachment_method'])}")

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


def _safe_str(value) -> str:
    """Safely convert a spec value to string for regex matching.
    Handles cases where GPT returns dicts/lists instead of strings."""
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    if isinstance(value, (dict, list)):
        return json.dumps(value)
    return str(value)


def _parse_r_value_from_spec(spec_data: dict) -> float:
    """
    Try to extract a target R-value from the spec data.
    Specs often say things like 'R-30 minimum' in insulation_layers or special_requirements.
    """
    for field in ("insulation_layers", "special_requirements", "insulation_type"):
        text = _safe_str(spec_data.get(field))
        if not text:
            continue
        match = re.search(r'R[-_]?(\d+\.?\d*)', text, re.IGNORECASE)
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

    insulation_type = _safe_str(spec_data.get("insulation_type")).lower()

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
    Build a complete Roof System with ALL conditions, then map plan data.

    System Template approach:
    1. Parse spec analysis to determine system type and materials
    2. Create (or reuse) a RoofSystem for the project
    3. Delete existing system conditions (clean rebuild)
    4. Instantiate ALL conditions from the system template (all start is_active=False)
    5. Gather plan extractions and map to matching conditions (turn them ON)
    6. Auto-derive perimeter/wall_flashing/coping from field area
    7. Populate materials for ALL conditions from MaterialTemplates
    8. R-value insulation selection for field conditions
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

    membrane_desc = _safe_str(spec_data.get("membrane_type")) or system_type
    thickness = _safe_str(spec_data.get("membrane_thickness"))
    attachment = _safe_str(spec_data.get("attachment_method"))
    insulation = _safe_str(spec_data.get("insulation_type"))
    cover_board = _safe_str(spec_data.get("cover_board"))

    # Step 2: Create or reuse a RoofSystem
    existing_system = db.query(RoofSystem).filter(
        RoofSystem.project_id == project_id
    ).first()

    if existing_system:
        roof_system = existing_system
        # Update system type if changed
        roof_system.system_type = system_type

        # Step 3: Delete existing conditions for this system (clean rebuild)
        existing_conditions = db.query(RoofCondition).filter(
            RoofCondition.roof_system_id == roof_system.id
        ).all()
        if existing_conditions:
            cond_ids = [c.id for c in existing_conditions]
            # Null out FK references in vision_extractions
            db.query(VisionExtraction).filter(
                VisionExtraction.condition_id.in_(cond_ids)
            ).update({VisionExtraction.condition_id: None}, synchronize_session=False)
            db.flush()
            for c in existing_conditions:
                db.query(ConditionMaterial).filter(ConditionMaterial.condition_id == c.id).delete()
                db.delete(c)
            db.flush()
    else:
        roof_system = RoofSystem(
            project_id=project_id,
            name="Roof Area 1",
            system_type=system_type,
        )
        db.add(roof_system)
        db.flush()

    # Also clean up any legacy conditions (no roof_system_id) that were AI-generated
    legacy_ai = db.query(RoofCondition).filter(
        RoofCondition.project_id == project_id,
        RoofCondition.roof_system_id == None,
        RoofCondition.description.like("%[AI%")
    ).all()
    if legacy_ai:
        legacy_ids = [c.id for c in legacy_ai]
        db.query(VisionExtraction).filter(
            VisionExtraction.condition_id.in_(legacy_ids)
        ).update({VisionExtraction.condition_id: None}, synchronize_session=False)
        db.flush()
        for c in legacy_ai:
            db.query(ConditionMaterial).filter(ConditionMaterial.condition_id == c.id).delete()
            db.delete(c)
        db.flush()

    # Step 4: Create ALL conditions from the system template
    template_conditions = get_system_conditions(system_type)
    condition_map = {}  # condition_type -> RoofCondition object
    total_materials = 0
    created = []

    for tmpl in template_conditions:
        ct_info = CONDITION_TYPES.get(tmpl["condition_type"], {"label": tmpl["condition_type"]})
        desc = f"[AI/{system_type}] {ct_info['label']}"
        if tmpl["condition_type"] == "field" and insulation:
            desc += f" | Insulation: {insulation}"
        if tmpl["condition_type"] == "field" and cover_board:
            desc += f" | Cover board: {cover_board}"

        condition = RoofCondition(
            project_id=project_id,
            roof_system_id=roof_system.id,
            condition_type=tmpl["condition_type"],
            description=desc,
            measurement_value=0,  # Start at 0 — AI will fill in
            measurement_unit=tmpl["measurement_unit"],
            wind_zone="1",
            flashing_height=tmpl.get("flashing_height"),
            fastener_spacing=tmpl.get("fastener_spacing"),
            is_active=False,  # Start ALL conditions OFF
        )
        db.add(condition)
        db.flush()

        # Populate materials from templates for ALL conditions
        mat_count = _populate_materials_for_condition(condition, system_type, org_id, db, spec_data)
        total_materials += mat_count

        condition_map[tmpl["condition_type"]] = condition
        created.append({
            "id": condition.id,
            "type": tmpl["condition_type"],
            "label": ct_info["label"],
            "extraction_type": None,
            "value": 0,
            "unit": tmpl["measurement_unit"],
            "description": desc,
            "materials_count": mat_count,
            "is_active": False,
            "mapped_from": None,
        })

    # Step 5: Gather plan extractions and map to conditions
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

    mapped_count = 0
    field_area = 0
    has_perimeter_data = False
    has_coping_data = False
    has_wall_flashing_data = False

    for ext in all_extractions:
        if ext.extraction_type in SKIP_TYPES:
            continue

        mapping = EXTRACTION_TO_CONDITION.get(ext.extraction_type)
        if not mapping:
            continue

        ctype = mapping["condition_type"]

        # Skip "custom" type — no template condition for it
        if ctype == "custom":
            continue

        # Find the matching condition in the system
        condition = condition_map.get(ctype)
        if not condition:
            continue

        # Map the extraction data to the condition
        # For conditions that can have multiple extractions (e.g., multiple pipe flashings),
        # add to existing measurement
        if condition.measurement_value == 0:
            condition.measurement_value = ext.measurement_value
        else:
            condition.measurement_value += ext.measurement_value

        condition.is_active = True  # Turn ON conditions with data

        # Update description with extraction info
        desc_parts = [f"[AI/{system_type}] {CONDITION_TYPES.get(ctype, {}).get('label', ctype)}"]
        if ext.location_on_plan:
            desc_parts.append(ext.location_on_plan)
        if ext.confidence_score:
            desc_parts.append(f"confidence: {ext.confidence_score:.0%}")
        condition.description = " | ".join(desc_parts)

        # Link extraction to condition
        ext.condition_id = condition.id

        # Track for auto-derivation
        if ctype == "field":
            field_area = max(field_area, condition.measurement_value)
        if ctype == "perimeter":
            has_perimeter_data = True
        if ctype == "coping":
            has_coping_data = True
        if ctype == "wall_flashing":
            has_wall_flashing_data = True

        mapped_count += 1

        # Update the created list entry
        for entry in created:
            if entry["type"] == ctype:
                entry["value"] = condition.measurement_value
                entry["is_active"] = True
                entry["mapped_from"] = ext.extraction_type
                entry["description"] = condition.description
                break

    # Step 6: Auto-derive perimeter/wall_flashing/coping from field area
    if field_area > 0:
        est_perimeter = estimate_perimeter_from_area(field_area)

        if not has_perimeter_data and est_perimeter > 0:
            perim = condition_map.get("perimeter")
            if perim:
                perim.measurement_value = est_perimeter
                perim.is_active = True
                perim.description = f"[AI/{system_type}] Auto-estimated from {field_area:,.0f} sqft roof area"
                for entry in created:
                    if entry["type"] == "perimeter":
                        entry["value"] = est_perimeter
                        entry["is_active"] = True
                        entry["mapped_from"] = "auto_perimeter"
                        break

        if not has_wall_flashing_data:
            wall_lf = round(est_perimeter * 0.6)
            if wall_lf > 0:
                wall = condition_map.get("wall_flashing")
                if wall:
                    wall.measurement_value = wall_lf
                    wall.is_active = True
                    wall.description = f"[AI/{system_type}] Auto-estimated (~60% of perimeter)"
                    for entry in created:
                        if entry["type"] == "wall_flashing":
                            entry["value"] = wall_lf
                            entry["is_active"] = True
                            entry["mapped_from"] = "auto_wall_flashing"
                            break

        if not has_coping_data and est_perimeter > 0:
            coping = condition_map.get("coping")
            if coping:
                coping.measurement_value = est_perimeter
                coping.is_active = True
                coping.description = f"[AI/{system_type}] Auto-estimated (full perimeter)"
                for entry in created:
                    if entry["type"] == "coping":
                        entry["value"] = est_perimeter
                        entry["is_active"] = True
                        entry["mapped_from"] = "auto_coping"
                        break

    db.commit()

    target_r = _parse_r_value_from_spec(spec_data)
    active_count = sum(1 for e in created if e["is_active"])

    return {
        "status": "success",
        "project_id": project_id,
        "system_id": roof_system.id,
        "system_name": roof_system.name,
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
        "conditions_active": active_count,
        "conditions_inactive": len(created) - active_count,
        "conditions_mapped_from_plans": mapped_count,
        "materials_populated": total_materials,
        "conditions": created,
        "note": f"Created full system with {len(created)} conditions. {active_count} mapped from plan data, {len(created) - active_count} available to enable manually.",
    }
