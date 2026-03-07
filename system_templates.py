"""
Roof System Templates — defines the complete set of conditions for each system type.

When Smart Build creates a new roof system, it instantiates ALL conditions from the
appropriate template. Conditions that the AI doesn't find evidence for start as
is_active=False with measurement_value=0. The user can toggle any condition on and
fill in measurements manually.
"""

# Each entry: (condition_type, default_unit, description, default_flashing_height, default_fastener_spacing)
# flashing_height and fastener_spacing are None unless relevant.

SINGLE_PLY_CONDITIONS = [
    {
        "condition_type": "field",
        "measurement_unit": "sqft",
        "description": "Field of Roof",
        "flashing_height": None,
        "fastener_spacing": 12,
        "sort_order": 1,
    },
    {
        "condition_type": "perimeter",
        "measurement_unit": "lnft",
        "description": "Perimeter Edge",
        "flashing_height": None,
        "fastener_spacing": 12,
        "sort_order": 2,
    },
    {
        "condition_type": "wall_flashing",
        "measurement_unit": "lnft",
        "description": "Wall Flashings",
        "flashing_height": 60.0,
        "fastener_spacing": 12,
        "sort_order": 3,
    },
    {
        "condition_type": "coping",
        "measurement_unit": "lnft",
        "description": "Coping",
        "flashing_height": None,
        "fastener_spacing": None,
        "sort_order": 4,
    },
    {
        "condition_type": "parapet",
        "measurement_unit": "lnft",
        "description": "Parapet Walls",
        "flashing_height": 60.0,
        "fastener_spacing": 12,
        "sort_order": 5,
    },
    {
        "condition_type": "edge_detail",
        "measurement_unit": "lnft",
        "description": "Edge Details / Drip Edge",
        "flashing_height": None,
        "fastener_spacing": None,
        "sort_order": 6,
    },
    {
        "condition_type": "roof_drain",
        "measurement_unit": "each",
        "description": "Roof Drains",
        "flashing_height": None,
        "fastener_spacing": None,
        "sort_order": 7,
    },
    {
        "condition_type": "scupper",
        "measurement_unit": "each",
        "description": "Scuppers",
        "flashing_height": None,
        "fastener_spacing": None,
        "sort_order": 8,
    },
    {
        "condition_type": "pipe_flashing",
        "measurement_unit": "each",
        "description": "Pipe Flashings",
        "flashing_height": None,
        "fastener_spacing": None,
        "sort_order": 9,
    },
    {
        "condition_type": "pitch_pan",
        "measurement_unit": "each",
        "description": "Pitch Pans",
        "flashing_height": None,
        "fastener_spacing": None,
        "sort_order": 10,
    },
    {
        "condition_type": "curb",
        "measurement_unit": "lnft",
        "description": "Equipment Curbs",
        "flashing_height": None,
        "fastener_spacing": None,
        "sort_order": 11,
    },
    {
        "condition_type": "penetration",
        "measurement_unit": "each",
        "description": "Miscellaneous Penetrations",
        "flashing_height": None,
        "fastener_spacing": None,
        "sort_order": 12,
    },
    {
        "condition_type": "expansion_joint",
        "measurement_unit": "lnft",
        "description": "Expansion Joints",
        "flashing_height": None,
        "fastener_spacing": None,
        "sort_order": 13,
    },
    {
        "condition_type": "transition",
        "measurement_unit": "lnft",
        "description": "Roof Transitions",
        "flashing_height": None,
        "fastener_spacing": None,
        "sort_order": 14,
    },
    {
        "condition_type": "corner",
        "measurement_unit": "each",
        "description": "Inside / Outside Corners",
        "flashing_height": None,
        "fastener_spacing": None,
        "sort_order": 15,
    },
]

# Map system types to their condition templates
# Currently all single-ply systems use the same condition set;
# future system types (ModBit, BUR, StandingSeam) could have different sets.
SYSTEM_TEMPLATES = {
    "TPO": SINGLE_PLY_CONDITIONS,
    "EPDM": SINGLE_PLY_CONDITIONS,
    "PVC": SINGLE_PLY_CONDITIONS,
    "ModBit": SINGLE_PLY_CONDITIONS,
    "BUR": SINGLE_PLY_CONDITIONS,
    "StandingSeam": SINGLE_PLY_CONDITIONS,
}


def get_system_conditions(system_type: str, org_id: int = None, db=None):
    """
    Return the condition template list for a given system type.

    Priority:
    1. Org-specific DB rows (if org_id + db provided and rows exist)
    2. Global DB rows (seeded defaults)
    3. Hardcoded SINGLE_PLY_CONDITIONS (backward compat fallback)
    """
    if db is not None:
        from conditions_models import SystemTemplateCondition

        # 1. Check for org-specific template
        if org_id:
            org_rows = db.query(SystemTemplateCondition).filter(
                SystemTemplateCondition.org_id == org_id,
                SystemTemplateCondition.system_type == system_type,
                SystemTemplateCondition.is_active == True,
            ).order_by(SystemTemplateCondition.sort_order).all()

            if org_rows:
                return [_row_to_dict(r) for r in org_rows]

        # 2. Fall back to global defaults from DB
        global_rows = db.query(SystemTemplateCondition).filter(
            SystemTemplateCondition.org_id == None,
            SystemTemplateCondition.is_global == True,
            SystemTemplateCondition.system_type == system_type,
            SystemTemplateCondition.is_active == True,
        ).order_by(SystemTemplateCondition.sort_order).all()

        if global_rows:
            return [_row_to_dict(r) for r in global_rows]

    # 3. Hardcoded fallback (no DB available or no rows seeded yet)
    return SYSTEM_TEMPLATES.get(system_type, SINGLE_PLY_CONDITIONS)


def _row_to_dict(row):
    """Convert a SystemTemplateCondition row to the dict format used by condition_builder."""
    return {
        "condition_type": row.condition_type,
        "measurement_unit": row.measurement_unit,
        "description": row.description,
        "flashing_height": row.flashing_height,
        "fastener_spacing": row.fastener_spacing,
        "sort_order": row.sort_order,
    }
