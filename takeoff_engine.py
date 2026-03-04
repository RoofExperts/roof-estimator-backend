"""
Roofing Takeoff Engine - Generates a professional material takeoff
from project conditions + spec data, matching real-world product packaging.

Output format mirrors a professional estimator's spreadsheet:
  1. Project Summary (system specs, area, perimeter, cost summary)
  2. Flat Roof Materials (membrane, insulation, fasteners, wall flashing)
  3. Roof Related Metals (drainage, gutters, coping/edge metal)
  4. Labor & General Conditions (crew labor, equipment, site facilities)

Each line item has: description, qty, unit, unit_cost, extended_cost
Items are grouped by category within each page.
"""

import json
import math
from sqlalchemy.orm import Session
from models import Project
from conditions_models import RoofCondition


# ============================================================================
# PRODUCT CATALOG - Real packaging & sizing for commercial roofing
# ============================================================================

TPO_PRODUCTS = {
    "membrane_rolls": {
        "name": "TPO Membrane 60-mil White (10'x100')",
        "coverage_sqft": 1000,  # per roll
        "unit": "Roll",
        "unit_cost": 385.00,
    },
    "membrane_cleaner": {
        "name": "Weathered Membrane Cleaner LVOC (5 gal)",
        "coverage_sqft": 5000,
        "unit": "Pail",
        "unit_cost": 68.00,
    },
    "unsupported_flashing": {
        "name": 'TPO 24" Unsupported Flashing',
        "coverage_lnft": 50,  # per roll
        "unit": "Roll",
        "unit_cost": 145.00,
    },
    "cut_edge_sealant": {
        "name": "TPO Cut Edge Sealant",
        "coverage_lnft": 200,
        "unit": "Bottle",
        "unit_cost": 18.50,
    },
    "primer": {
        "name": "TPO Primer",
        "coverage_lnft": 300,
        "unit": "Gal",
        "unit_cost": 52.00,
    },
    "water_block": {
        "name": "Water Block Sealant",
        "coverage_each": 10,  # penetrations per tube
        "unit": "Tube",
        "unit_cost": 12.50,
    },
    "walkway_pad": {
        "name": 'Walkway Pad 34" x 50\'',
        "coverage_sqft": 1800,  # approx per roll for typical walkway
        "unit": "Roll",
        "unit_cost": 195.00,
    },
    "wall_flashing_roll": {
        "name": "TPO Wall Flashing 6' wide x 50' long",
        "coverage_lnft": 50,
        "unit": "Roll",
        "unit_cost": 265.00,
    },
    "cav_grip": {
        "name": "Cav-Grip Adhesive 40#",
        "coverage_lnft": 150,
        "unit": "Tank",
        "unit_cost": 185.00,
    },
    "inside_corners": {
        "name": "TPO Inside Corners",
        "unit": "Each",
        "unit_cost": 8.50,
    },
}

EPDM_PRODUCTS = {
    "membrane_rolls": {
        "name": "EPDM 45-mil Membrane (10'x100')",
        "coverage_sqft": 1000,
        "unit": "Roll",
        "unit_cost": 310.00,
    },
    "membrane_cleaner": {
        "name": "EPDM Splice Cleaner (1 gal)",
        "coverage_sqft": 3000,
        "unit": "Gal",
        "unit_cost": 45.00,
    },
    "unsupported_flashing": {
        "name": 'EPDM 24" Peel & Stick Flashing',
        "coverage_lnft": 50,
        "unit": "Roll",
        "unit_cost": 165.00,
    },
    "seam_tape": {
        "name": 'EPDM 3" Seam Tape (100\' roll)',
        "coverage_sqft": 2500,
        "unit": "Roll",
        "unit_cost": 42.00,
    },
    "bonding_adhesive": {
        "name": "EPDM Bonding Adhesive (5 gal)",
        "coverage_sqft": 1000,
        "unit": "Pail",
        "unit_cost": 195.00,
    },
    "water_block": {
        "name": "Water Block Sealant",
        "coverage_each": 10,
        "unit": "Tube",
        "unit_cost": 12.50,
    },
    "walkway_pad": {
        "name": 'Walkway Pad 34" x 50\'',
        "coverage_sqft": 1800,
        "unit": "Roll",
        "unit_cost": 195.00,
    },
    "wall_flashing_roll": {
        "name": "EPDM Wall Flashing 6' wide x 50' long",
        "coverage_lnft": 50,
        "unit": "Roll",
        "unit_cost": 245.00,
    },
    "cav_grip": {
        "name": "Cav-Grip Adhesive 40#",
        "coverage_lnft": 150,
        "unit": "Tank",
        "unit_cost": 185.00,
    },
    "inside_corners": {
        "name": "EPDM Inside Corners",
        "unit": "Each",
        "unit_cost": 7.50,
    },
}

PVC_PRODUCTS = {
    "membrane_rolls": {
        "name": "PVC 60-mil Membrane White (10'x100')",
        "coverage_sqft": 1000,
        "unit": "Roll",
        "unit_cost": 465.00,
    },
    "membrane_cleaner": {
        "name": "PVC Membrane Cleaner (5 gal)",
        "coverage_sqft": 5000,
        "unit": "Pail",
        "unit_cost": 72.00,
    },
    "unsupported_flashing": {
        "name": 'PVC 24" Unsupported Flashing',
        "coverage_lnft": 50,
        "unit": "Roll",
        "unit_cost": 175.00,
    },
    "cut_edge_sealant": {
        "name": "PVC Cut Edge Sealant",
        "coverage_lnft": 200,
        "unit": "Bottle",
        "unit_cost": 22.00,
    },
    "primer": {
        "name": "PVC Primer",
        "coverage_lnft": 300,
        "unit": "Gal",
        "unit_cost": 58.00,
    },
    "water_block": {
        "name": "Water Block Sealant",
        "coverage_each": 10,
        "unit": "Tube",
        "unit_cost": 12.50,
    },
    "walkway_pad": {
        "name": 'Walkway Pad 34" x 50\'',
        "coverage_sqft": 1800,
        "unit": "Roll",
        "unit_cost": 195.00,
    },
    "wall_flashing_roll": {
        "name": "PVC Wall Flashing 6' wide x 50' long",
        "coverage_lnft": 50,
        "unit": "Roll",
        "unit_cost": 285.00,
    },
    "cav_grip": {
        "name": "Cav-Grip Adhesive 40#",
        "coverage_lnft": 150,
        "unit": "Tank",
        "unit_cost": 185.00,
    },
    "inside_corners": {
        "name": "PVC Inside Corners",
        "unit": "Each",
        "unit_cost": 9.50,
    },
}

SYSTEM_PRODUCTS = {"TPO": TPO_PRODUCTS, "EPDM": EPDM_PRODUCTS, "PVC": PVC_PRODUCTS}

# Common products (insulation, fasteners) shared across systems
INSULATION_PRODUCTS = {
    "polyiso_board": {
        "name": 'Polyiso Insulation 2.2" (4\'x8\' boards)',
        "coverage_sqft": 32,  # 4x8 = 32 sqft per board
        "unit": "Pcs",
        "unit_cost": 28.50,
    },
    "tapered_panels": {
        "name": 'Tapered Q Panels 1/2"/ft (4\'x4\')',
        "coverage_sqft": 1000,  # about 6 per 1000 sqft
        "unit": "Pcs",
        "unit_cost": 22.00,
        "rate_per_1000sf": 6,
    },
    "fill_panels": {
        "name": '2" Fill Panels (4\'x4\')',
        "coverage_sqft": 1200,  # about 5 per 1200 sqft
        "unit": "Pcs",
        "unit_cost": 18.00,
        "rate_per_1000sf": 5,
    },
}

FASTENER_PRODUCTS = {
    "insul_fasteners": {
        "name": '6" InsulFast Fasteners',
        "box_count": 500,
        "rate_per_sqft": 0.10,  # 1 per 10 sqft
        "unit": "Box",
        "unit_cost": 145.00,
    },
    "insul_plates": {
        "name": '3" Insulation Plates',
        "box_count": 1000,
        "rate_per_sqft": 0.10,
        "unit": "Box",
        "unit_cost": 85.00,
    },
    "field_fasteners": {
        "name": '6" HP-X Fasteners - Field',
        "box_count": 500,
        "rate_per_sqft": 0.08,
        "unit": "Box",
        "unit_cost": 165.00,
    },
    "perimeter_fasteners": {
        "name": '2" HP-X Fasteners - Perimeter',
        "box_count": 1000,
        "rate_per_lnft": 0.50,
        "unit": "Box",
        "unit_cost": 125.00,
    },
    "piranha_plates": {
        "name": '2⅜" Piranha Plates',
        "box_count": 1000,
        "rate_per_sqft": 0.08,
        "unit": "Box",
        "unit_cost": 95.00,
    },
}

METAL_PRODUCTS = {
    "scuppers": {"name": "Scuppers (Primary)", "unit": "Each", "unit_cost": 185.00},
    "collector_heads": {"name": "Collector Heads (for Primary Scuppers)", "unit": "Each", "unit_cost": 245.00},
    "box_gutters": {"name": "Box Gutters (10' sticks)", "unit": "Sticks", "unit_cost": 85.00, "coverage_lnft": 10},
    "downspouts": {"name": 'Downspouts 4" (10\' sticks)', "unit": "Sticks", "unit_cost": 45.00, "coverage_lnft": 10},
    "coping": {"name": "24 Ga Coping (10' sticks)", "unit": "Sticks", "unit_cost": 65.00, "coverage_lnft": 10},
}

LABOR_ITEMS = {
    "flat_roof_labor": {
        "name": "Flat Roof Installation Labor",
        "unit": "SQ",
        "rate": 85.00,
    },
    "telehandler": {
        "name": "Telehandler 36' - 1 Week",
        "unit": "Rental",
        "rate": 2329.50,
        "fixed_qty": 1,
    },
    "portable_toilets": {
        "name": "Portable Toilets",
        "unit": "Month",
        "rate": 0.0,
        "fixed_qty": "TBD",
    },
    "dumpster": {
        "name": "Dumpster - 30 Yard",
        "unit": "Month",
        "rate": 0.0,
        "fixed_qty": "TBD",
    },
    "building_permit": {
        "name": "Building Permit",
        "unit": "LS",
        "rate": 0.0,
        "fixed_qty": "TBD",
        "note": "Owner to verify",
    },
    "fire_marshal": {
        "name": "Fire Marshal Inspection",
        "unit": "LS",
        "rate": 0.0,
        "fixed_qty": "TBD",
        "note": "Owner to verify",
    },
}


# ============================================================================
# HELPERS
# ============================================================================

def _ceil(val):
    return math.ceil(val)


def _spec_val(spec, key, default=None):
    return spec.get(key) or default


def _parse_spec(project):
    if not project.analysis_result:
        return {}
    try:
        return json.loads(project.analysis_result) if isinstance(project.analysis_result, str) else project.analysis_result
    except:
        return {}


def _detect_system(project, spec):
    if project.system_type:
        st = project.system_type.upper().strip()
        if "EPDM" in st: return "EPDM"
        if "PVC" in st: return "PVC"
        if "TPO" in st: return "TPO"
    membrane = (spec.get("membrane_type") or "").upper()
    system = (spec.get("roof_system_type") or "").upper()
    combined = membrane + " " + system
    if "EPDM" in combined: return "EPDM"
    if "PVC" in combined: return "PVC"
    return "TPO"


def _get_conditions_summary(conditions):
    """Extract key measurements from conditions list."""
    total_area = 0
    total_perimeter = 0
    penetrations = 0
    edge_detail_lf = 0
    scuppers = 0
    drains = 0
    downspout_lf = 0
    curb_lf = 0
    transitions_lf = 0

    for c in conditions:
        ct = c.condition_type
        val = c.measurement_value or 0
        unit = c.measurement_unit or ""

        if ct == "field" and "sqft" in unit:
            total_area += val
        elif ct == "perimeter":
            total_perimeter += val
        elif ct == "penetration":
            if "lnft" in unit:
                curb_lf += val
            else:
                penetrations += val
        elif ct == "edge_detail":
            edge_detail_lf += val
        elif ct == "transition":
            transitions_lf += val
        elif ct == "custom":
            desc = (c.description or "").lower()
            if "scupper" in desc:
                scuppers += val
            elif "drain" in desc:
                drains += val
            elif "downspout" in desc:
                downspout_lf += val

    return {
        "total_area": total_area,
        "total_squares": round(total_area / 100, 2),
        "total_perimeter": total_perimeter,
        "penetrations": int(penetrations),
        "edge_detail_lf": edge_detail_lf,
        "scuppers": int(scuppers),
        "drains": int(drains),
        "downspout_lf": downspout_lf,
        "curb_lf": curb_lf,
        "transitions_lf": transitions_lf,
    }


# ============================================================================
# GENERATE TAKEOFF
# ============================================================================

def generate_takeoff(project_id: int, db: Session) -> dict:
    """
    Generate a full professional takeoff from project conditions + spec data.
    Returns structured data matching the 4-sheet spreadsheet format.
    """
    project = db.query(Project).filter(Project.id == project_id).first()
    if not project:
        return {"status": "error", "message": "Project not found"}

    spec = _parse_spec(project)
    system = _detect_system(project, spec)
    products = SYSTEM_PRODUCTS.get(system, TPO_PRODUCTS)

    conditions = db.query(RoofCondition).filter(
        RoofCondition.project_id == project_id
    ).all()

    if not conditions:
        return {"status": "error", "message": "No conditions found. Run Smart Build first."}

    measurements = _get_conditions_summary(conditions)
    area = measurements["total_area"]
    squares = measurements["total_squares"]
    perimeter = measurements["total_perimeter"]
    penetrations = measurements["penetrations"]
    edge_lf = measurements["edge_detail_lf"]
    scuppers = measurements["scuppers"]
    drains = measurements["drains"]
    downspout_lf = measurements["downspout_lf"]

    # Total wall flashing LF = perimeter + transitions
    wall_flash_lf = perimeter + measurements["transitions_lf"]
    # Inside corners estimate: roughly 4 per building
    inside_corners = max(4, int(perimeter / 80))

    # ========== PAGE 2: FLAT ROOF MATERIALS ==========
    flat_materials = []
    line_num = 0

    # -- MEMBRANE & ACCESSORIES --
    membrane_items = []
    if area > 0:
        p = products["membrane_rolls"]
        qty = _ceil(area / p["coverage_sqft"])
        membrane_items.append({"line": (line_num := line_num + 1), "description": p["name"], "qty": qty, "unit": p["unit"], "unit_cost": p["unit_cost"], "extended": round(qty * p["unit_cost"], 2)})

        p = products["membrane_cleaner"]
        qty = _ceil(area / p["coverage_sqft"])
        membrane_items.append({"line": (line_num := line_num + 1), "description": p["name"], "qty": qty, "unit": p["unit"], "unit_cost": p["unit_cost"], "extended": round(qty * p["unit_cost"], 2)})

    if perimeter > 0 or edge_lf > 0:
        flash_lf = max(perimeter, edge_lf)
        p = products["unsupported_flashing"]
        qty = _ceil(flash_lf / p["coverage_lnft"])
        membrane_items.append({"line": (line_num := line_num + 1), "description": p["name"], "qty": qty, "unit": p["unit"], "unit_cost": p["unit_cost"], "extended": round(qty * p["unit_cost"], 2)})

    # System-specific accessories
    if system == "TPO" or system == "PVC":
        if "cut_edge_sealant" in products:
            p = products["cut_edge_sealant"]
            qty = _ceil(perimeter / p["coverage_lnft"]) if perimeter > 0 else 1
            membrane_items.append({"line": (line_num := line_num + 1), "description": p["name"], "qty": qty, "unit": p["unit"], "unit_cost": p["unit_cost"], "extended": round(qty * p["unit_cost"], 2)})

        if "primer" in products:
            p = products["primer"]
            qty = _ceil(perimeter / p["coverage_lnft"]) if perimeter > 0 else 1
            membrane_items.append({"line": (line_num := line_num + 1), "description": p["name"], "qty": qty, "unit": p["unit"], "unit_cost": p["unit_cost"], "extended": round(qty * p["unit_cost"], 2)})

    if system == "EPDM" and "seam_tape" in products:
        p = products["seam_tape"]
        qty = _ceil(area / p["coverage_sqft"])
        membrane_items.append({"line": (line_num := line_num + 1), "description": p["name"], "qty": qty, "unit": p["unit"], "unit_cost": p["unit_cost"], "extended": round(qty * p["unit_cost"], 2)})

        p = products["bonding_adhesive"]
        qty = _ceil(area / p["coverage_sqft"])
        membrane_items.append({"line": (line_num := line_num + 1), "description": p["name"], "qty": qty, "unit": p["unit"], "unit_cost": p["unit_cost"], "extended": round(qty * p["unit_cost"], 2)})

    if penetrations > 0:
        p = products["water_block"]
        qty = _ceil(penetrations / p["coverage_each"])
        membrane_items.append({"line": (line_num := line_num + 1), "description": p["name"], "qty": qty, "unit": p["unit"], "unit_cost": p["unit_cost"], "extended": round(qty * p["unit_cost"], 2)})

    if area > 0:
        p = products["walkway_pad"]
        qty = _ceil(area / p["coverage_sqft"])
        membrane_items.append({"line": (line_num := line_num + 1), "description": p["name"], "qty": qty, "unit": p["unit"], "unit_cost": p["unit_cost"], "extended": round(qty * p["unit_cost"], 2)})

    flat_materials.append({"category": "MEMBRANE & ACCESSORIES", "items": membrane_items})

    # -- INSULATION --
    insulation_items = []
    if area > 0:
        p = INSULATION_PRODUCTS["polyiso_board"]
        # 2 layers of insulation → need 2x boards
        layers = 2
        qty = _ceil((area * layers) / p["coverage_sqft"])
        insulation_items.append({"line": (line_num := line_num + 1), "description": p["name"], "qty": qty, "unit": p["unit"], "unit_cost": p["unit_cost"], "extended": round(qty * p["unit_cost"], 2)})

        p = INSULATION_PRODUCTS["tapered_panels"]
        qty = _ceil(area / 1000 * p.get("rate_per_1000sf", 6))
        insulation_items.append({"line": (line_num := line_num + 1), "description": p["name"], "qty": qty, "unit": p["unit"], "unit_cost": p["unit_cost"], "extended": round(qty * p["unit_cost"], 2)})

        p = INSULATION_PRODUCTS["fill_panels"]
        qty = _ceil(area / 1000 * p.get("rate_per_1000sf", 5))
        insulation_items.append({"line": (line_num := line_num + 1), "description": p["name"], "qty": qty, "unit": p["unit"], "unit_cost": p["unit_cost"], "extended": round(qty * p["unit_cost"], 2)})

    flat_materials.append({"category": "INSULATION", "items": insulation_items})

    # -- FASTENERS & PLATES --
    fastener_items = []
    if area > 0:
        for key in ["insul_fasteners", "insul_plates", "field_fasteners", "perimeter_fasteners", "piranha_plates"]:
            p = FASTENER_PRODUCTS[key]
            if "rate_per_sqft" in p:
                needed = area * p["rate_per_sqft"]
            elif "rate_per_lnft" in p:
                needed = perimeter * p["rate_per_lnft"]
            else:
                needed = 0

            qty = max(1, _ceil(needed / p["box_count"]))
            desc = f"{p['name']} (1 box @ {p['box_count']:,}/box)"
            fastener_items.append({"line": (line_num := line_num + 1), "description": desc, "qty": qty, "unit": p["unit"], "unit_cost": p["unit_cost"], "extended": round(qty * p["unit_cost"], 2)})

    flat_materials.append({"category": "FASTENERS & PLATES", "items": fastener_items})

    # -- WALL FLASHING --
    wall_items = []
    if wall_flash_lf > 0:
        p = products["wall_flashing_roll"]
        qty = _ceil(wall_flash_lf / p["coverage_lnft"])
        wall_items.append({"line": (line_num := line_num + 1), "description": p["name"], "qty": qty, "unit": p["unit"], "unit_cost": p["unit_cost"], "extended": round(qty * p["unit_cost"], 2)})

        p = products["cav_grip"]
        qty = _ceil(wall_flash_lf / p["coverage_lnft"])
        wall_items.append({"line": (line_num := line_num + 1), "description": p["name"], "qty": qty, "unit": p["unit"], "unit_cost": p["unit_cost"], "extended": round(qty * p["unit_cost"], 2)})

        p = products["inside_corners"]
        wall_items.append({"line": (line_num := line_num + 1), "description": p["name"], "qty": inside_corners, "unit": p["unit"], "unit_cost": p["unit_cost"], "extended": round(inside_corners * p["unit_cost"], 2)})

    flat_materials.append({"category": "WALL FLASHING", "items": wall_items})

    flat_total = sum(item["extended"] for group in flat_materials for item in group["items"])

    # ========== PAGE 3: ROOF RELATED METALS ==========
    metals = []
    line_num_m = 0

    # -- DRAINAGE --
    drainage_items = []
    if scuppers > 0:
        p = METAL_PRODUCTS["scuppers"]
        drainage_items.append({"line": (line_num_m := line_num_m + 1), "description": p["name"], "qty": scuppers, "unit": p["unit"], "unit_cost": p["unit_cost"], "extended": round(scuppers * p["unit_cost"], 2)})
        p = METAL_PRODUCTS["collector_heads"]
        drainage_items.append({"line": (line_num_m := line_num_m + 1), "description": p["name"], "qty": scuppers, "unit": p["unit"], "unit_cost": p["unit_cost"], "extended": round(scuppers * p["unit_cost"], 2)})
    if drains > 0:
        drainage_items.append({"line": (line_num_m := line_num_m + 1), "description": "Roof Drains (Primary)", "qty": drains, "unit": "Each", "unit_cost": 225.00, "extended": round(drains * 225.00, 2)})
    metals.append({"category": "DRAINAGE", "items": drainage_items})

    # -- GUTTERS & DOWNSPOUTS --
    gutter_items = []
    if perimeter > 0:
        p = METAL_PRODUCTS["box_gutters"]
        gutter_lf = perimeter * 0.2  # roughly 20% of perimeter gets gutters
        qty = _ceil(gutter_lf / p["coverage_lnft"]) if gutter_lf > 0 else 0
        if qty > 0:
            gutter_items.append({"line": (line_num_m := line_num_m + 1), "description": p["name"], "qty": qty, "unit": p["unit"], "unit_cost": p["unit_cost"], "extended": round(qty * p["unit_cost"], 2)})

    if downspout_lf > 0:
        p = METAL_PRODUCTS["downspouts"]
        qty = _ceil(downspout_lf / p["coverage_lnft"])
        gutter_items.append({"line": (line_num_m := line_num_m + 1), "description": p["name"], "qty": qty, "unit": p["unit"], "unit_cost": p["unit_cost"], "extended": round(qty * p["unit_cost"], 2)})
    metals.append({"category": "GUTTERS & DOWNSPOUTS", "items": gutter_items})

    # -- COPING & EDGE METAL --
    coping_items = []
    if perimeter > 0:
        p = METAL_PRODUCTS["coping"]
        qty = _ceil(perimeter / p["coverage_lnft"])
        coping_items.append({"line": (line_num_m := line_num_m + 1), "description": p["name"], "qty": qty, "unit": p["unit"], "unit_cost": p["unit_cost"], "extended": round(qty * p["unit_cost"], 2)})
    metals.append({"category": "COPING & EDGE METAL", "items": coping_items})

    metals_total = sum(item["extended"] for group in metals for item in group["items"])

    # ========== PAGE 4: LABOR & GENERAL CONDITIONS ==========
    labor = []
    line_num_l = 0

    # -- LABOR --
    labor_items = []
    p = LABOR_ITEMS["flat_roof_labor"]
    labor_cost = round(squares * p["rate"], 2) if squares > 0 else 0
    labor_items.append({"line": (line_num_l := line_num_l + 1), "description": p["name"], "qty": squares, "unit": p["unit"], "unit_cost": p["rate"], "extended": labor_cost})
    labor.append({"category": "LABOR", "items": labor_items})

    # -- EQUIPMENT --
    equip_items = []
    p = LABOR_ITEMS["telehandler"]
    equip_items.append({"line": (line_num_l := line_num_l + 1), "description": p["name"], "qty": p["fixed_qty"], "unit": p["unit"], "unit_cost": p["rate"], "extended": p["rate"]})
    labor.append({"category": "EQUIPMENT RENTAL", "items": equip_items})

    # -- SITE FACILITIES --
    site_items = []
    for key in ["portable_toilets", "dumpster"]:
        p = LABOR_ITEMS[key]
        site_items.append({"line": (line_num_l := line_num_l + 1), "description": p["name"], "qty": p["fixed_qty"], "unit": p["unit"], "unit_cost": p["rate"], "extended": 0.0})
    labor.append({"category": "SITE FACILITIES", "items": site_items})

    # -- PERMITS --
    permit_items = []
    for key in ["building_permit", "fire_marshal"]:
        p = LABOR_ITEMS[key]
        permit_items.append({"line": (line_num_l := line_num_l + 1), "description": p["name"], "qty": p["fixed_qty"], "unit": p["unit"], "unit_cost": p["rate"], "extended": 0.0, "note": p.get("note", "")})
    labor.append({"category": "PERMITS & FEES", "items": permit_items})

    labor_total = sum(item["extended"] for group in labor for item in group["items"])

    # Warranty cost
    warranty_cost = 950.00 if squares > 0 else 0
    manufacturer = _spec_val(spec, "manufacturer", "Carlisle")
    if isinstance(manufacturer, list):
        manufacturer = manufacturer[0] if manufacturer else "Carlisle"
    warranty_years = _spec_val(spec, "warranty_years", 20)

    # ========== PROJECT SUMMARY ==========
    subtotal = flat_total + metals_total + labor_total + warranty_cost
    markup_pct = 0.25
    markup = round(subtotal * markup_pct, 2)
    subtotal_with_markup = round(subtotal + markup, 2)
    tax_pct = 0.0825
    tax = round((flat_total + metals_total) * (1 + markup_pct) * tax_pct, 2)  # Tax on materials only
    grand_total = round(subtotal_with_markup + tax, 2)

    # System description
    membrane_type = _spec_val(spec, "membrane_type", system)
    thickness = _spec_val(spec, "membrane_thickness", "60 mil")
    attachment = _spec_val(spec, "attachment_method", "Mechanically Fastened")
    system_desc = f"{membrane_type} {thickness} {attachment}"
    insulation_desc = _spec_val(spec, "insulation_type", "Polyisocyanurate (Polyiso)")
    insulation_layers = _spec_val(spec, "insulation_layers", 'R-25 (2 layers × 2.2" polyiso)')
    cover_board = _spec_val(spec, "cover_board", "")

    summary = {
        "project_name": project.project_name,
        "address": project.address or "",
        "system_type": system,
        "system_description": system_desc,
        "manufacturer": manufacturer,
        "membrane": f"{thickness} White {system}" if thickness else f"60 mil White {system}",
        "insulation": insulation_layers if insulation_layers else insulation_desc,
        "cover_board": cover_board,
        "warranty": f"{warranty_years} Year Total-System",
        "roof_area_sf": area,
        "roof_area_sq": squares,
        "perimeter_lf": perimeter,
        "penetrations": penetrations,
        "cost_summary": {
            "flat_materials": round(flat_total, 2),
            "metals": round(metals_total, 2),
            "labor": round(labor_total, 2),
            "warranty": warranty_cost,
            "subtotal": round(subtotal, 2),
            "markup_pct": markup_pct,
            "markup": markup,
            "subtotal_with_markup": subtotal_with_markup,
            "tax_pct": tax_pct,
            "tax": tax,
            "grand_total": grand_total,
        },
    }

    return {
        "status": "success",
        "summary": summary,
        "flat_materials": flat_materials,
        "flat_materials_total": round(flat_total, 2),
        "metals": metals,
        "metals_total": round(metals_total, 2),
        "labor": labor,
        "labor_total": round(labor_total, 2),
        "warranty_cost": warranty_cost,
        "warranty_description": f"{manufacturer} {warranty_years} Year Total-System Warranty",
    }
