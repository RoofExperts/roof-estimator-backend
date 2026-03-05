"""
Seed data for the commercial roofing estimating engine.
Creates default MaterialTemplates and CostDatabaseItems.
Each template is tagged with a system_type: TPO, EPDM, PVC, or common.

Global seed data (is_global=True, org_id=None) is shared read-only across all orgs.
When a new org is created, clone_seed_for_org() copies these into org-specific records.

CONDITION MATERIAL STACKS (build-up order):
============================================
Field:          base_sheet → bottom_insulation → top_insulation → coverboard →
                insulation_fasteners → insulation_plates → membrane →
                membrane_fasteners/membrane_adhesive
Wall Flashing:  membrane → adhesive → termination_bar → term_bar_fasteners
Curb Flashing:  membrane → adhesive
Drains:         waterblock (1 tube) → membrane (2 SF)
Pipe Flashing:  waterblock (0.5 tube) → pipe_boot (1) → sealant (0.5 tube) →
                membrane_screws_and_plates (4)
Pitch Pan:      sealant_pocket (1) → pourable_sealer (0.5 bag) →
                primer (0.2 gal) → membrane_screws_and_plates (4)
Scuppers:       waterblock (1 tube) → metal_scupper_box (1)
"""

from sqlalchemy.orm import Session
from sqlalchemy import or_
from conditions_models import MaterialTemplate, CostDatabaseItem


def seed_material_templates(db: Session):
    """Seed global material templates for all roofing systems with proper build-up stacks."""
    existing = db.query(MaterialTemplate).filter(MaterialTemplate.is_global == True).first()
    if existing:
        print("Global material templates already exist. Skipping seed.")
        return

    templates = []

    def t(system, ctype, name, cat, unit, rate, waste=0.10, calc_type=None,
          sort_order=0, is_optional=False):
        templates.append(MaterialTemplate(
            system_type=system, condition_type=ctype, material_name=name,
            material_category=cat, unit=unit,
            coverage_rate=rate, waste_factor=waste, calc_type=calc_type,
            sort_order=sort_order, is_optional=is_optional,
            is_active=True, org_id=None, is_global=True
        ))

    # ════════════════════════════════════════════════════════════════════════
    # FIELD CONDITION — common layers (shared across TPO/EPDM/PVC)
    # Build-up order: base sheet → insulation → coverboard → fasteners → membrane → attachment
    # ════════════════════════════════════════════════════════════════════════
    t("common", "field", "Base Sheet (if needed)",          "base_sheet",  "sqft", 1.0, 0.05, sort_order=10, is_optional=True)
    t("common", "field", "Bottom Insulation Layer",         "insulation",  "sqft", 1.0, 0.05, sort_order=20, is_optional=True)
    t("common", "field", "Top Insulation Layer",            "insulation",  "sqft", 1.0, 0.05, sort_order=30, is_optional=True)
    t("common", "field", "Coverboard",                      "coverboard",  "sqft", 1.0, 0.05, sort_order=40, is_optional=True)
    t("common", "field", "Insulation Fasteners",            "fastener",    "each", 1.0, 0.10, sort_order=50, calc_type="fastener")
    t("common", "field", "Insulation Plates",               "fastener",    "each", 1.0, 0.10, sort_order=55, calc_type="fastener")

    # ════════════════════════════════════════════════════════════════════════
    # FIELD CONDITION — system-specific membrane + attachment
    # ════════════════════════════════════════════════════════════════════════

    # ── TPO Field ──
    t("TPO", "field", "TPO Membrane",                       "membrane",    "sqft", 1.0, 0.10, sort_order=60)
    t("TPO", "field", "Membrane Fasteners (screws)",        "fastener",    "each", 1.0, 0.10, sort_order=70, calc_type="fastener")
    t("TPO", "field", "Membrane Plates (seam plates)",      "fastener",    "each", 1.0, 0.10, sort_order=75, calc_type="fastener")
    # Adhesive alternative (user picks fasteners OR adhesive)
    t("TPO", "field", "TPO Bonding Adhesive",               "adhesive",    "gallon", 0.015, 0.05, sort_order=70, is_optional=True)

    # ── EPDM Field ──
    t("EPDM", "field", "EPDM Membrane",                    "membrane",    "sqft", 1.0, 0.10, sort_order=60)
    t("EPDM", "field", "EPDM Bonding Adhesive",            "adhesive",    "gallon", 0.010, 0.05, sort_order=70)
    t("EPDM", "field", "Membrane Fasteners (screws)",       "fastener",    "each", 1.0, 0.10, sort_order=70, calc_type="fastener", is_optional=True)
    t("EPDM", "field", "Membrane Plates (seam plates)",     "fastener",    "each", 1.0, 0.10, sort_order=75, calc_type="fastener", is_optional=True)

    # ── PVC Field ──
    t("PVC", "field", "PVC Membrane",                       "membrane",    "sqft", 1.0, 0.10, sort_order=60)
    t("PVC", "field", "Membrane Fasteners (screws)",        "fastener",    "each", 1.0, 0.10, sort_order=70, calc_type="fastener")
    t("PVC", "field", "Membrane Plates (seam plates)",      "fastener",    "each", 1.0, 0.10, sort_order=75, calc_type="fastener")
    t("PVC", "field", "PVC Bonding Adhesive",               "adhesive",    "gallon", 0.015, 0.05, sort_order=70, is_optional=True)

    # ════════════════════════════════════════════════════════════════════════
    # WALL FLASHING — membrane → adhesive → termination bar → fasteners
    # ════════════════════════════════════════════════════════════════════════

    # ── TPO Wall Flashing ──
    t("TPO", "wall_flashing", "TPO Membrane",               "membrane",    "sqft", 1.0, 0.10, sort_order=10, calc_type="wall_membrane")
    t("TPO", "wall_flashing", "TPO Bonding Adhesive",       "adhesive",    "gallon", 0.02, 0.05, sort_order=20)
    t("TPO", "wall_flashing", "Termination Bar",            "accessory",   "lnft", 1.0, 0.05, sort_order=30)
    t("TPO", "wall_flashing", "Termination Bar Fasteners",  "fastener",    "each", 1.0, 0.05, sort_order=40, calc_type="fastener")

    # ── EPDM Wall Flashing ──
    t("EPDM", "wall_flashing", "EPDM Membrane",            "membrane",    "sqft", 1.0, 0.10, sort_order=10, calc_type="wall_membrane")
    t("EPDM", "wall_flashing", "EPDM Bonding Adhesive",    "adhesive",    "gallon", 0.02, 0.05, sort_order=20)
    t("EPDM", "wall_flashing", "Termination Bar",           "accessory",   "lnft", 1.0, 0.05, sort_order=30)
    t("EPDM", "wall_flashing", "Termination Bar Fasteners", "fastener",    "each", 1.0, 0.05, sort_order=40, calc_type="fastener")

    # ── PVC Wall Flashing ──
    t("PVC", "wall_flashing", "PVC Membrane",               "membrane",    "sqft", 1.0, 0.10, sort_order=10, calc_type="wall_membrane")
    t("PVC", "wall_flashing", "PVC Bonding Adhesive",       "adhesive",    "gallon", 0.02, 0.05, sort_order=20)
    t("PVC", "wall_flashing", "Termination Bar",            "accessory",   "lnft", 1.0, 0.05, sort_order=30)
    t("PVC", "wall_flashing", "Termination Bar Fasteners",  "fastener",    "each", 1.0, 0.05, sort_order=40, calc_type="fastener")

    # ════════════════════════════════════════════════════════════════════════
    # CURB FLASHING — membrane → adhesive
    # ════════════════════════════════════════════════════════════════════════

    t("TPO", "curb", "TPO Membrane",                        "membrane",    "lnft", 3.0, 0.15, sort_order=10)
    t("TPO", "curb", "TPO Bonding Adhesive",                "adhesive",    "gallon", 0.03, 0.05, sort_order=20)

    t("EPDM", "curb", "EPDM Membrane",                     "membrane",    "lnft", 3.0, 0.15, sort_order=10)
    t("EPDM", "curb", "EPDM Bonding Adhesive",             "adhesive",    "gallon", 0.03, 0.05, sort_order=20)

    t("PVC", "curb", "PVC Membrane",                        "membrane",    "lnft", 3.0, 0.15, sort_order=10)
    t("PVC", "curb", "PVC Bonding Adhesive",                "adhesive",    "gallon", 0.03, 0.05, sort_order=20)

    # ════════════════════════════════════════════════════════════════════════
    # ROOF DRAINS — 1 tube waterblock + 2 SF membrane (per drain)
    # ════════════════════════════════════════════════════════════════════════

    t("TPO", "roof_drain", "Waterblock Sealant",            "sealant",     "each", 1.0, 0.0, sort_order=10)
    t("TPO", "roof_drain", "TPO Membrane",                  "membrane",    "sqft", 2.0, 0.10, sort_order=20)

    t("EPDM", "roof_drain", "Waterblock Sealant",           "sealant",     "each", 1.0, 0.0, sort_order=10)
    t("EPDM", "roof_drain", "EPDM Membrane",               "membrane",    "sqft", 2.0, 0.10, sort_order=20)

    t("PVC", "roof_drain", "Waterblock Sealant",            "sealant",     "each", 1.0, 0.0, sort_order=10)
    t("PVC", "roof_drain", "PVC Membrane",                  "membrane",    "sqft", 2.0, 0.10, sort_order=20)

    # ════════════════════════════════════════════════════════════════════════
    # PIPE FLASHING — 0.5 tube waterblock + 1 pipe boot + 0.5 tube sealant + 4 screws/plates
    # ════════════════════════════════════════════════════════════════════════

    t("TPO", "pipe_flashing", "Waterblock Sealant",         "sealant",     "each", 0.5, 0.0, sort_order=10)
    t("TPO", "pipe_flashing", "Pipe Boot Flashing",         "flashing",    "each", 1.0, 0.0, sort_order=20)
    t("TPO", "pipe_flashing", "All Purpose Sealant",        "sealant",     "each", 0.5, 0.0, sort_order=30)
    t("TPO", "pipe_flashing", "Membrane Screws & Seam Plates", "fastener", "each", 4.0, 0.0, sort_order=40)

    t("EPDM", "pipe_flashing", "Waterblock Sealant",        "sealant",    "each", 0.5, 0.0, sort_order=10)
    t("EPDM", "pipe_flashing", "Pipe Boot Flashing",        "flashing",   "each", 1.0, 0.0, sort_order=20)
    t("EPDM", "pipe_flashing", "All Purpose Sealant",       "sealant",    "each", 0.5, 0.0, sort_order=30)
    t("EPDM", "pipe_flashing", "Membrane Screws & Seam Plates", "fastener", "each", 4.0, 0.0, sort_order=40)

    t("PVC", "pipe_flashing", "Waterblock Sealant",          "sealant",   "each", 0.5, 0.0, sort_order=10)
    t("PVC", "pipe_flashing", "Pipe Boot Flashing",          "flashing",  "each", 1.0, 0.0, sort_order=20)
    t("PVC", "pipe_flashing", "All Purpose Sealant",         "sealant",   "each", 0.5, 0.0, sort_order=30)
    t("PVC", "pipe_flashing", "Membrane Screws & Seam Plates", "fastener", "each", 4.0, 0.0, sort_order=40)

    # ════════════════════════════════════════════════════════════════════════
    # PITCH PAN / SEALANT POCKET — 1 pocket + 0.5 bag sealer + 0.2 gal primer + 4 screws/plates
    # ════════════════════════════════════════════════════════════════════════

    t("TPO", "pitch_pan", "Premolded Sealant Pocket",       "accessory",   "each", 1.0, 0.0, sort_order=10)
    t("TPO", "pitch_pan", "Pourable Sealer",                "sealant",     "each", 0.5, 0.0, sort_order=20)
    t("TPO", "pitch_pan", "TPO Primer",                     "adhesive",    "gallon", 0.2, 0.0, sort_order=30)
    t("TPO", "pitch_pan", "Membrane Screws & Plates",       "fastener",    "each", 4.0, 0.0, sort_order=40)

    t("EPDM", "pitch_pan", "Premolded Sealant Pocket",      "accessory",  "each", 1.0, 0.0, sort_order=10)
    t("EPDM", "pitch_pan", "Pourable Sealer",               "sealant",    "each", 0.5, 0.0, sort_order=20)
    t("EPDM", "pitch_pan", "EPDM Primer",                   "adhesive",   "gallon", 0.2, 0.0, sort_order=30)
    t("EPDM", "pitch_pan", "Membrane Screws & Plates",      "fastener",   "each", 4.0, 0.0, sort_order=40)

    t("PVC", "pitch_pan", "Premolded Sealant Pocket",        "accessory",  "each", 1.0, 0.0, sort_order=10)
    t("PVC", "pitch_pan", "Pourable Sealer",                 "sealant",    "each", 0.5, 0.0, sort_order=20)
    t("PVC", "pitch_pan", "PVC Primer",                      "adhesive",   "gallon", 0.2, 0.0, sort_order=30)
    t("PVC", "pitch_pan", "Membrane Screws & Plates",        "fastener",   "each", 4.0, 0.0, sort_order=40)

    # ════════════════════════════════════════════════════════════════════════
    # SCUPPERS — 1 tube waterblock + 1 metal scupper box (per scupper)
    # ════════════════════════════════════════════════════════════════════════

    t("common", "scupper", "Waterblock Sealant",             "sealant",    "each", 1.0, 0.0, sort_order=10)
    t("common", "scupper", "Metal Scupper Box",              "flashing",   "each", 1.0, 0.0, sort_order=20)

    # ════════════════════════════════════════════════════════════════════════
    # COPING — metal + fasteners + sealant
    # ════════════════════════════════════════════════════════════════════════

    t("common", "coping", "Coping Metal (24ga)",             "flashing",   "lnft", 1.0, 0.05, sort_order=10)
    t("common", "coping", "Coping Fasteners",                "fastener",   "each", 3.0, 0.10, sort_order=20)
    t("common", "coping", "Polyurethane Sealant",            "sealant",    "gallon", 0.02, 0.10, sort_order=30)

    # ════════════════════════════════════════════════════════════════════════
    # PERIMETER — membrane strip + fasteners + bar
    # ════════════════════════════════════════════════════════════════════════

    t("TPO", "perimeter", "TPO Membrane",                    "membrane",   "lnft", 1.0, 0.10, sort_order=10)
    t("TPO", "perimeter", "Perimeter Fasteners",             "fastener",   "each", 2.0, 0.10, sort_order=20)
    t("TPO", "perimeter", "Perimeter Bar (Aluminum)",        "accessory",  "lnft", 1.0, 0.05, sort_order=30)

    t("EPDM", "perimeter", "EPDM Membrane",                 "membrane",   "lnft", 1.0, 0.10, sort_order=10)
    t("EPDM", "perimeter", "Perimeter Fasteners",           "fastener",   "each", 2.0, 0.10, sort_order=20)
    t("EPDM", "perimeter", "Perimeter Bar (Aluminum)",      "accessory",  "lnft", 1.0, 0.05, sort_order=30)

    t("PVC", "perimeter", "PVC Membrane",                    "membrane",   "lnft", 1.0, 0.10, sort_order=10)
    t("PVC", "perimeter", "Perimeter Fasteners",             "fastener",   "each", 2.0, 0.10, sort_order=20)
    t("PVC", "perimeter", "Perimeter Bar (Aluminum)",        "accessory",  "lnft", 1.0, 0.05, sort_order=30)

    # ════════════════════════════════════════════════════════════════════════
    # CORNER — membrane + fasteners + sealant
    # ════════════════════════════════════════════════════════════════════════

    t("TPO", "corner", "TPO Membrane",                       "membrane",   "sqft", 2.0, 0.15, sort_order=10)
    t("EPDM", "corner", "EPDM Membrane",                    "membrane",   "sqft", 2.0, 0.15, sort_order=10)
    t("PVC", "corner", "PVC Membrane",                       "membrane",   "sqft", 2.0, 0.15, sort_order=10)
    t("common", "corner", "Corner Flashing (Aluminum)",      "flashing",   "lnft", 4.0, 0.05, sort_order=20)
    t("common", "corner", "Corner Fasteners",                "fastener",   "each", 4.0, 0.10, sort_order=30)
    t("common", "corner", "Polyurethane Sealant",            "sealant",    "gallon", 0.05, 0.10, sort_order=40)

    # ════════════════════════════════════════════════════════════════════════
    # PENETRATION — generic (non-pipe, non-pitch-pan)
    # ════════════════════════════════════════════════════════════════════════

    t("TPO", "penetration", "TPO Membrane",                  "membrane",   "sqft", 6.0, 0.15, sort_order=10)
    t("TPO", "penetration", "TPO Bonding Adhesive",          "adhesive",   "gallon", 0.05, 0.05, sort_order=20)
    t("EPDM", "penetration", "EPDM Membrane",               "membrane",   "sqft", 6.0, 0.15, sort_order=10)
    t("EPDM", "penetration", "EPDM Bonding Adhesive",       "adhesive",   "gallon", 0.05, 0.05, sort_order=20)
    t("PVC", "penetration", "PVC Membrane",                  "membrane",   "sqft", 6.0, 0.15, sort_order=10)
    t("PVC", "penetration", "PVC Bonding Adhesive",          "adhesive",   "gallon", 0.05, 0.05, sort_order=20)
    t("common", "penetration", "Polyurethane Sealant",       "sealant",    "gallon", 0.10, 0.05, sort_order=30)

    # ════════════════════════════════════════════════════════════════════════
    # EDGE DETAIL — membrane strip + metal + fasteners + sealant
    # ════════════════════════════════════════════════════════════════════════

    t("TPO", "edge_detail", "TPO Strip (6in)",               "membrane",   "lnft", 1.0, 0.10, sort_order=10)
    t("EPDM", "edge_detail", "EPDM Edge Strip",             "membrane",   "lnft", 1.0, 0.10, sort_order=10)
    t("PVC", "edge_detail", "PVC Edge Strip",                "membrane",   "lnft", 1.0, 0.10, sort_order=10)
    t("common", "edge_detail", "Metal Edge Flashing (24ga)", "flashing",   "lnft", 1.0, 0.05, sort_order=20)
    t("common", "edge_detail", "Drip Edge (Aluminum)",       "flashing",   "lnft", 1.0, 0.05, sort_order=25)
    t("common", "edge_detail", "Edge Fasteners",             "fastener",   "each", 3.0, 0.10, sort_order=30)
    t("common", "edge_detail", "Polyurethane Sealant",       "sealant",    "gallon", 0.02, 0.10, sort_order=40)

    # ════════════════════════════════════════════════════════════════════════
    # TRANSITION — membrane + sealant + term bar + fasteners
    # ════════════════════════════════════════════════════════════════════════

    t("TPO", "transition", "TPO Membrane",                   "membrane",   "lnft", 2.0, 0.15, sort_order=10)
    t("EPDM", "transition", "EPDM Membrane",                "membrane",   "lnft", 2.0, 0.15, sort_order=10)
    t("PVC", "transition", "PVC Membrane",                   "membrane",   "lnft", 2.0, 0.15, sort_order=10)
    t("common", "transition", "Polyurethane Sealant",        "sealant",    "gallon", 0.03, 0.10, sort_order=20)
    t("common", "transition", "Termination Bar",             "accessory",  "lnft", 1.0, 0.05, sort_order=30)
    t("common", "transition", "Transition Fasteners",        "fastener",   "each", 2.0, 0.10, sort_order=40)

    # ════════════════════════════════════════════════════════════════════════
    # EXPANSION JOINT — premade cover + sealant
    # ════════════════════════════════════════════════════════════════════════

    t("common", "expansion_joint", "Expansion Joint Cover",  "accessory",  "lnft", 1.0, 0.05, sort_order=10)
    t("common", "expansion_joint", "Polyurethane Sealant",   "sealant",    "gallon", 0.03, 0.10, sort_order=20)

    # ════════════════════════════════════════════════════════════════════════
    # PARAPET — membrane + adhesive + coping
    # ════════════════════════════════════════════════════════════════════════

    t("TPO", "parapet", "TPO Membrane",                      "membrane",   "sqft", 1.0, 0.10, sort_order=10, calc_type="wall_membrane")
    t("TPO", "parapet", "TPO Bonding Adhesive",              "adhesive",   "gallon", 0.02, 0.05, sort_order=20)
    t("EPDM", "parapet", "EPDM Membrane",                   "membrane",   "sqft", 1.0, 0.10, sort_order=10, calc_type="wall_membrane")
    t("EPDM", "parapet", "EPDM Bonding Adhesive",           "adhesive",   "gallon", 0.02, 0.05, sort_order=20)
    t("PVC", "parapet", "PVC Membrane",                      "membrane",   "sqft", 1.0, 0.10, sort_order=10, calc_type="wall_membrane")
    t("PVC", "parapet", "PVC Bonding Adhesive",              "adhesive",   "gallon", 0.02, 0.05, sort_order=20)
    t("common", "parapet", "Termination Bar",                "accessory",  "lnft", 1.0, 0.05, sort_order=30)
    t("common", "parapet", "Termination Bar Fasteners",      "fastener",   "each", 1.0, 0.05, sort_order=40, calc_type="fastener")

    # ════════════════════════════════════════════════════════════════════════
    # MODIFIED BITUMEN (MOD BIT) SYSTEM
    # ════════════════════════════════════════════════════════════════════════

    t("ModBit", "field", "Mod Bit Base Sheet",               "membrane",   "sqft", 1.0, 0.10, sort_order=60)
    t("ModBit", "field", "SBS Mod Bit Cap Sheet",            "membrane",   "sqft", 1.0, 0.10, sort_order=65)
    t("ModBit", "field", "Hot Asphalt (Type III)",           "adhesive",   "gallon", 0.08, 0.05, sort_order=70)
    t("ModBit", "field", "Mod Bit Primer",                   "adhesive",   "gallon", 0.01, 0.05, sort_order=75)
    t("ModBit", "perimeter", "SBS Mod Bit Cap Sheet",        "membrane",   "lnft", 1.5, 0.10, sort_order=10)
    t("ModBit", "perimeter", "Hot Asphalt (Type III)",       "adhesive",   "gallon", 0.10, 0.05, sort_order=20)
    t("ModBit", "corner", "SBS Mod Bit Cap Sheet",           "membrane",   "sqft", 2.0, 0.15, sort_order=10)
    t("ModBit", "penetration", "SBS Mod Bit Cap Sheet",      "membrane",   "sqft", 6.0, 0.15, sort_order=10)
    t("ModBit", "penetration", "Mod Bit Mastic",             "sealant",    "gallon", 0.05, 0.05, sort_order=20)
    t("ModBit", "edge_detail", "Mod Bit Edge Strip",         "membrane",   "lnft", 1.0, 0.10, sort_order=10)
    t("ModBit", "transition", "SBS Mod Bit Cap Sheet",       "membrane",   "lnft", 2.0, 0.15, sort_order=10)
    t("ModBit", "transition", "Mod Bit Mastic",              "sealant",    "gallon", 0.03, 0.10, sort_order=20)
    t("ModBit", "wall_flashing", "Mod Bit Base Sheet",       "membrane",   "sqft", 1.0, 0.10, sort_order=10, calc_type="wall_membrane")
    t("ModBit", "wall_flashing", "SBS Mod Bit Cap Sheet",    "membrane",   "sqft", 1.0, 0.10, sort_order=15, calc_type="wall_membrane")
    t("ModBit", "wall_flashing", "Hot Asphalt (Type III)",   "adhesive",   "gallon", 0.04, 0.05, sort_order=20)
    t("ModBit", "wall_flashing", "Termination Bar",          "accessory",  "lnft", 1.0, 0.05, sort_order=30)
    t("ModBit", "wall_flashing", "Termination Bar Fasteners", "fastener",  "each", 1.0, 0.05, sort_order=40, calc_type="fastener")
    t("ModBit", "curb", "SBS Mod Bit Cap Sheet",             "membrane",   "lnft", 3.0, 0.15, sort_order=10)
    t("ModBit", "curb", "Hot Asphalt (Type III)",            "adhesive",   "gallon", 0.03, 0.05, sort_order=20)

    # ════════════════════════════════════════════════════════════════════════
    # BUILT-UP ROOFING (BUR) SYSTEM
    # ════════════════════════════════════════════════════════════════════════

    t("BUR", "field", "Fiberglass Felt Ply (Type IV)",       "membrane",   "sqft", 3.0, 0.10, sort_order=60)
    t("BUR", "field", "Hot Asphalt (Type III)",              "adhesive",   "gallon", 0.25, 0.05, sort_order=65)
    t("BUR", "field", "BUR Flood Coat (Gravel)",             "accessory",  "sqft", 1.0, 0.10, sort_order=70)
    t("BUR", "field", "Roofing Gravel (#4 Aggregate)",       "accessory",  "sqft", 1.0, 0.10, sort_order=75)
    t("BUR", "perimeter", "Fiberglass Felt Ply (Type IV)",   "membrane",   "lnft", 3.0, 0.10, sort_order=10)
    t("BUR", "perimeter", "Hot Asphalt (Type III)",          "adhesive",   "gallon", 0.30, 0.05, sort_order=20)
    t("BUR", "corner", "Fiberglass Felt Ply (Type IV)",      "membrane",   "sqft", 4.0, 0.15, sort_order=10)
    t("BUR", "penetration", "Fiberglass Felt Ply (Type IV)", "membrane",   "sqft", 6.0, 0.15, sort_order=10)
    t("BUR", "penetration", "Hot Asphalt (Type III)",        "adhesive",   "gallon", 0.05, 0.05, sort_order=20)
    t("BUR", "penetration", "BUR Mastic",                    "sealant",    "gallon", 0.05, 0.05, sort_order=30)
    t("BUR", "edge_detail", "BUR Edge Strip Ply",            "membrane",   "lnft", 1.5, 0.10, sort_order=10)
    t("BUR", "transition", "Fiberglass Felt Ply (Type IV)",  "membrane",   "lnft", 3.0, 0.15, sort_order=10)

    # ════════════════════════════════════════════════════════════════════════
    # STANDING SEAM METAL SYSTEM
    # ════════════════════════════════════════════════════════════════════════

    t("StandingSeam", "field", "24ga Standing Seam Panel (Galvalume)", "membrane", "sqft", 1.0, 0.08, sort_order=60)
    t("StandingSeam", "field", "Standing Seam Clip (Fixed)",  "fastener",  "each", 0.5, 0.05, sort_order=65)
    t("StandingSeam", "field", "Standing Seam Clip (Floating)", "fastener", "each", 0.5, 0.05, sort_order=70)
    t("StandingSeam", "field", "Panel Screw (#12x1.5)",       "fastener",  "each", 2.0, 0.10, sort_order=75)
    t("StandingSeam", "field", "Underlayment (Synthetic)",    "accessory", "sqft", 1.0, 0.05, sort_order=55)
    t("StandingSeam", "perimeter", "Eave Trim (24ga)",        "flashing",  "lnft", 1.0, 0.05, sort_order=10)
    t("StandingSeam", "perimeter", "Gable Trim (24ga)",       "flashing",  "lnft", 1.0, 0.05, sort_order=20)
    t("StandingSeam", "corner", "Hip/Valley Flashing (24ga)", "flashing",  "lnft", 1.0, 0.05, sort_order=10)
    t("StandingSeam", "penetration", "Pipe Boot (Metal)",     "flashing",  "each", 1.0, 0.0, sort_order=10)
    t("StandingSeam", "penetration", "Metal Sealant (Butyl)", "sealant",   "gallon", 0.02, 0.05, sort_order=20)
    t("StandingSeam", "edge_detail", "Ridge Cap (24ga)",      "flashing",  "lnft", 1.0, 0.05, sort_order=10)
    t("StandingSeam", "edge_detail", "Ridge Vent (Continuous)", "accessory", "lnft", 1.0, 0.05, sort_order=20)
    t("StandingSeam", "transition", "Transition Flashing (24ga)", "flashing", "lnft", 1.0, 0.05, sort_order=10)
    t("StandingSeam", "transition", "Metal Sealant (Butyl)",  "sealant",   "gallon", 0.02, 0.05, sort_order=20)

    db.add_all(templates)
    db.commit()
    print(f"Seeded {len(templates)} global material templates.")


def seed_cost_database(db: Session):
    """Seed the global cost database with realistic commercial roofing pricing."""
    existing = db.query(CostDatabaseItem).filter(CostDatabaseItem.is_global == True).first()
    if existing:
        print("Global cost database already populated. Skipping seed.")
        return

    items = []

    def c(name, mfr, cat, unit, cost, labor=None):
        items.append(CostDatabaseItem(
            material_name=name, manufacturer=mfr,
            material_category=cat, unit=unit,
            unit_cost=cost, labor_cost_per_unit=labor, is_active=True,
            org_id=None, is_global=True
        ))

    # ── Membranes ──
    c("TPO Membrane", "Carlisle", "membrane", "sqft", 0.85, 0.75)
    c("TPO Membrane", "GAF", "membrane", "sqft", 0.82, 0.75)
    c("EPDM Membrane", "Carlisle", "membrane", "sqft", 0.65, 0.70)
    c("PVC Membrane", "Carlisle", "membrane", "sqft", 1.10, 0.80)
    c("PVC Membrane", "GAF", "membrane", "sqft", 1.05, 0.80)

    # ── Insulation (placeholder costs — updated from spreadsheets) ──
    c("Bottom Insulation Layer", "TBD", "insulation", "sqft", 0.55, 0.30)
    c("Top Insulation Layer", "TBD", "insulation", "sqft", 0.55, 0.30)
    c("Coverboard", "TBD", "coverboard", "sqft", 0.45, 0.25)
    c("Base Sheet (if needed)", "TBD", "base_sheet", "sqft", 0.35, 0.25)

    # ── Insulation Fasteners & Plates ──
    c("Insulation Fasteners", "Carlisle", "fastener", "each", 0.18, 0.10)
    c("Insulation Plates", "Carlisle", "fastener", "each", 0.12, 0.05)

    # ── Membrane Fasteners & Plates ──
    c("Membrane Fasteners (screws)", "Carlisle", "fastener", "each", 0.22, 0.10)
    c("Membrane Plates (seam plates)", "Carlisle", "fastener", "each", 0.15, 0.08)
    c("Membrane Screws & Seam Plates", "Carlisle", "fastener", "each", 0.35, 0.15)
    c("Membrane Screws & Plates", "Carlisle", "fastener", "each", 0.35, 0.15)

    # ── Adhesives ──
    c("TPO Bonding Adhesive", "Carlisle", "adhesive", "gallon", 20.00, 5.00)
    c("EPDM Bonding Adhesive", "Carlisle", "adhesive", "gallon", 22.00, 5.00)
    c("PVC Bonding Adhesive", "Carlisle", "adhesive", "gallon", 24.00, 5.00)

    # ── Sealants ──
    c("Waterblock Sealant", "Carlisle", "sealant", "each", 12.50, 3.00)
    c("All Purpose Sealant", "Carlisle", "sealant", "each", 8.50, 2.00)
    c("Polyurethane Sealant", "Tremco", "sealant", "gallon", 35.00, 8.00)
    c("Pourable Sealer", "Carlisle", "sealant", "each", 18.00, 5.00)

    # ── Primers ──
    c("TPO Primer", "Carlisle", "adhesive", "gallon", 28.00, 5.00)
    c("EPDM Primer", "Carlisle", "adhesive", "gallon", 28.00, 5.00)
    c("PVC Primer", "Carlisle", "adhesive", "gallon", 28.00, 5.00)

    # ── Flashing ──
    c("Pipe Boot Flashing", "Portals Plus", "flashing", "each", 12.00, 15.00)
    c("Corner Flashing (Aluminum)", "Tremco", "flashing", "lnft", 2.50, 3.50)
    c("Metal Edge Flashing (24ga)", "Metal Era", "flashing", "lnft", 3.50, 2.50)
    c("Drip Edge (Aluminum)", "Metal Era", "flashing", "lnft", 2.25, 2.00)
    c("Metal Scupper Box", "Metal Era", "flashing", "each", 45.00, 25.00)

    # ── Accessories ──
    c("Termination Bar", "Metal Era", "accessory", "lnft", 1.50, 1.25)
    c("Termination Bar Fasteners", "Carlisle", "fastener", "each", 0.22, 0.08)
    c("Premolded Sealant Pocket", "Portals Plus", "accessory", "each", 22.00, 20.00)
    c("Perimeter Bar (Aluminum)", "Metal Era", "accessory", "lnft", 1.75, 1.50)
    c("Perimeter Fasteners", "OMG", "fastener", "each", 0.35, 0.15)
    c("Corner Fasteners", "OMG", "fastener", "each", 0.35, 0.15)
    c("Edge Fasteners", "OMG", "fastener", "each", 0.25, 0.12)
    c("Transition Fasteners", "OMG", "fastener", "each", 0.25, 0.12)
    c("Expansion Joint Cover", "Tremco", "accessory", "lnft", 8.50, 6.00)

    # ── Coping ──
    c("Coping Metal (24ga)", "Metal Era", "flashing", "lnft", 6.50, 4.00)
    c("Coping Fasteners", "OMG", "fastener", "each", 0.25, 0.12)

    # ── Mod Bit ──
    c("SBS Mod Bit Cap Sheet", "GAF", "membrane", "sqft", 0.95, 0.85)
    c("Mod Bit Base Sheet", "GAF", "membrane", "sqft", 0.55, 0.45)
    c("Hot Asphalt (Type III)", "Building Products", "adhesive", "gallon", 8.50, 3.00)
    c("Mod Bit Primer", "GAF", "adhesive", "gallon", 28.00, 5.00)
    c("Mod Bit Mastic", "GAF", "sealant", "gallon", 32.00, 8.00)
    c("Mod Bit Edge Strip", "GAF", "membrane", "lnft", 1.20, 0.90)

    # ── BUR ──
    c("Fiberglass Felt Ply (Type IV)", "Johns Manville", "membrane", "sqft", 0.18, 0.30)
    c("BUR Flood Coat (Gravel)", "Building Products", "accessory", "sqft", 0.12, 0.20)
    c("Roofing Gravel (#4 Aggregate)", "Local Supply", "accessory", "sqft", 0.08, 0.15)
    c("BUR Mastic", "Johns Manville", "sealant", "gallon", 30.00, 8.00)
    c("BUR Edge Strip Ply", "Johns Manville", "membrane", "lnft", 0.55, 0.40)

    # ── Standing Seam Metal ──
    c("24ga Standing Seam Panel (Galvalume)", "MBCI", "membrane", "sqft", 3.85, 2.50)
    c("Standing Seam Clip (Fixed)", "MBCI", "fastener", "each", 0.65, 0.20)
    c("Standing Seam Clip (Floating)", "MBCI", "fastener", "each", 0.85, 0.20)
    c("Panel Screw (#12x1.5)", "OMG", "fastener", "each", 0.08, 0.05)
    c("Underlayment (Synthetic)", "GAF", "accessory", "sqft", 0.12, 0.10)
    c("Eave Trim (24ga)", "MBCI", "flashing", "lnft", 4.50, 3.00)
    c("Gable Trim (24ga)", "MBCI", "flashing", "lnft", 4.50, 3.00)
    c("Hip/Valley Flashing (24ga)", "MBCI", "flashing", "lnft", 5.00, 4.00)
    c("Pipe Boot (Metal)", "Portals Plus", "flashing", "each", 16.00, 15.00)
    c("Metal Sealant (Butyl)", "Tremco", "sealant", "gallon", 28.00, 6.00)
    c("Ridge Cap (24ga)", "MBCI", "flashing", "lnft", 6.00, 4.00)
    c("Ridge Vent (Continuous)", "Lomanco", "accessory", "lnft", 3.50, 2.00)
    c("Transition Flashing (24ga)", "MBCI", "flashing", "lnft", 5.50, 4.00)

    # ── Membrane strips (for edge/perimeter) ──
    c("TPO Strip (6in)", "Carlisle", "membrane", "lnft", 0.75, 0.50)
    c("EPDM Edge Strip", "Carlisle", "membrane", "lnft", 1.10, 0.90)
    c("PVC Edge Strip", "Carlisle", "membrane", "lnft", 1.40, 1.00)

    db.add_all(items)
    db.commit()
    print(f"Seeded {len(items)} global cost database items.")


def clone_seed_for_org(org_id: int, db: Session):
    """
    Clone all global seed templates and cost items for a new organization.
    This gives each org their own editable copy of the material database.
    """
    # Clone material templates
    global_templates = db.query(MaterialTemplate).filter(
        MaterialTemplate.is_global == True
    ).all()

    cloned_templates = 0
    for t in global_templates:
        new_t = MaterialTemplate(
            system_type=t.system_type,
            condition_type=t.condition_type,
            material_name=t.material_name,
            material_category=t.material_category,
            unit=t.unit,
            coverage_rate=t.coverage_rate,
            waste_factor=t.waste_factor,
            calc_type=t.calc_type,
            sort_order=t.sort_order,
            is_optional=t.is_optional,
            is_active=True,
            org_id=org_id,
            is_global=False,
        )
        db.add(new_t)
        cloned_templates += 1

    # Clone cost database items
    global_costs = db.query(CostDatabaseItem).filter(
        CostDatabaseItem.is_global == True
    ).all()

    cloned_costs = 0
    for c in global_costs:
        new_c = CostDatabaseItem(
            material_name=c.material_name,
            manufacturer=c.manufacturer,
            material_category=c.material_category,
            unit=c.unit,
            unit_cost=c.unit_cost,
            labor_cost_per_unit=c.labor_cost_per_unit,
            is_active=True,
            org_id=org_id,
            is_global=False,
        )
        db.add(new_c)
        cloned_costs += 1

    db.flush()
    print(f"[seed] Cloned {cloned_templates} templates and {cloned_costs} cost items for org {org_id}")
    return {"templates": cloned_templates, "cost_items": cloned_costs}


def seed_database(db: Session):
    """Run all seed functions."""
    print("Starting database seed...")
    seed_material_templates(db)
    seed_cost_database(db)
    print("Database seeding complete.")
