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
    # Check if NEW templates (with sort_order > 0) exist — if so, already seeded
    existing_new = db.query(MaterialTemplate).filter(
        MaterialTemplate.is_global == True,
        MaterialTemplate.sort_order > 0
    ).first()
    if existing_new:
        print("Global material templates (with build-up stacks) already exist. Skipping seed.")
        return

    # Delete old global templates that don't have sort_order (legacy seed data)
    old_count = db.query(MaterialTemplate).filter(
        MaterialTemplate.is_global == True,
        MaterialTemplate.org_id == None
    ).delete(synchronize_session=False)
    if old_count:
        db.commit()
        print(f"[seed] Removed {old_count} old global templates to replace with build-up stack templates.")

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
    t("TPO", "pipe_flashing", "Polyurethane Sealant",        "sealant",     "each", 0.5, 0.0, sort_order=30)
    t("TPO", "pipe_flashing", "Membrane Screws & Seam Plates", "fastener", "each", 4.0, 0.0, sort_order=40)

    t("EPDM", "pipe_flashing", "Waterblock Sealant",        "sealant",    "each", 0.5, 0.0, sort_order=10)
    t("EPDM", "pipe_flashing", "Pipe Boot Flashing",        "flashing",   "each", 1.0, 0.0, sort_order=20)
    t("EPDM", "pipe_flashing", "Polyurethane Sealant",       "sealant",    "each", 0.5, 0.0, sort_order=30)
    t("EPDM", "pipe_flashing", "Membrane Screws & Seam Plates", "fastener", "each", 4.0, 0.0, sort_order=40)

    t("PVC", "pipe_flashing", "Waterblock Sealant",          "sealant",   "each", 0.5, 0.0, sort_order=10)
    t("PVC", "pipe_flashing", "Pipe Boot Flashing",          "flashing",  "each", 1.0, 0.0, sort_order=20)
    t("PVC", "pipe_flashing", "Polyurethane Sealant",         "sealant",   "each", 0.5, 0.0, sort_order=30)
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
    t("common", "coping", "Polyurethane Sealant",            "sealant",    "each", 0.25, 0.10, sort_order=30)

    # ════════════════════════════════════════════════════════════════════════
    # PERIMETER — membrane strip + fasteners + bar
    # ════════════════════════════════════════════════════════════════════════

    t("TPO", "perimeter", "TPO Membrane",                    "membrane",   "lnft", 1.0, 0.10, sort_order=10)
    t("TPO", "perimeter", "Perimeter Fasteners",             "fastener",   "each", 2.0, 0.10, sort_order=20)
    t("TPO", "perimeter", "Termination Bar",        "accessory",  "lnft", 1.0, 0.05, sort_order=30)

    t("EPDM", "perimeter", "EPDM Membrane",                 "membrane",   "lnft", 1.0, 0.10, sort_order=10)
    t("EPDM", "perimeter", "Perimeter Fasteners",           "fastener",   "each", 2.0, 0.10, sort_order=20)
    t("EPDM", "perimeter", "Termination Bar",      "accessory",  "lnft", 1.0, 0.05, sort_order=30)

    t("PVC", "perimeter", "PVC Membrane",                    "membrane",   "lnft", 1.0, 0.10, sort_order=10)
    t("PVC", "perimeter", "Perimeter Fasteners",             "fastener",   "each", 2.0, 0.10, sort_order=20)
    t("PVC", "perimeter", "Termination Bar",        "accessory",  "lnft", 1.0, 0.05, sort_order=30)

    # ════════════════════════════════════════════════════════════════════════
    # CORNER — membrane + fasteners + sealant
    # ════════════════════════════════════════════════════════════════════════

    t("TPO", "corner", "TPO Membrane",                       "membrane",   "sqft", 2.0, 0.15, sort_order=10)
    t("EPDM", "corner", "EPDM Membrane",                    "membrane",   "sqft", 2.0, 0.15, sort_order=10)
    t("PVC", "corner", "PVC Membrane",                       "membrane",   "sqft", 2.0, 0.15, sort_order=10)
    t("common", "corner", "Corner Flashing (Aluminum)",      "flashing",   "lnft", 4.0, 0.05, sort_order=20)
    t("common", "corner", "Corner Fasteners",                "fastener",   "each", 4.0, 0.10, sort_order=30)
    t("common", "corner", "Polyurethane Sealant",            "sealant",    "each", 0.625, 0.10, sort_order=40)

    # ════════════════════════════════════════════════════════════════════════
    # PENETRATION — generic (non-pipe, non-pitch-pan)
    # ════════════════════════════════════════════════════════════════════════

    t("TPO", "penetration", "TPO Membrane",                  "membrane",   "sqft", 6.0, 0.15, sort_order=10)
    t("TPO", "penetration", "TPO Bonding Adhesive",          "adhesive",   "gallon", 0.05, 0.05, sort_order=20)
    t("EPDM", "penetration", "EPDM Membrane",               "membrane",   "sqft", 6.0, 0.15, sort_order=10)
    t("EPDM", "penetration", "EPDM Bonding Adhesive",       "adhesive",   "gallon", 0.05, 0.05, sort_order=20)
    t("PVC", "penetration", "PVC Membrane",                  "membrane",   "sqft", 6.0, 0.15, sort_order=10)
    t("PVC", "penetration", "PVC Bonding Adhesive",          "adhesive",   "gallon", 0.05, 0.05, sort_order=20)
    t("common", "penetration", "Polyurethane Sealant",       "sealant",    "each", 1.25, 0.05, sort_order=30)

    # ════════════════════════════════════════════════════════════════════════
    # EDGE DETAIL — membrane strip + metal + fasteners + sealant
    # ════════════════════════════════════════════════════════════════════════

    t("TPO", "edge_detail", "TPO Strip (6in)",               "membrane",   "lnft", 1.0, 0.10, sort_order=10)
    t("EPDM", "edge_detail", "EPDM Edge Strip",             "membrane",   "lnft", 1.0, 0.10, sort_order=10)
    t("PVC", "edge_detail", "PVC Edge Strip",                "membrane",   "lnft", 1.0, 0.10, sort_order=10)
    t("common", "edge_detail", "Metal Edge Flashing (24ga)", "flashing",   "lnft", 1.0, 0.05, sort_order=20)
    t("common", "edge_detail", "Drip Edge (Aluminum)",       "flashing",   "lnft", 1.0, 0.05, sort_order=25)
    t("common", "edge_detail", "Edge Fasteners",             "fastener",   "each", 3.0, 0.10, sort_order=30)
    t("common", "edge_detail", "Polyurethane Sealant",       "sealant",    "each", 0.25, 0.10, sort_order=40)

    # ════════════════════════════════════════════════════════════════════════
    # TRANSITION — membrane + sealant + term bar + fasteners
    # ════════════════════════════════════════════════════════════════════════

    t("TPO", "transition", "TPO Membrane",                   "membrane",   "lnft", 2.0, 0.15, sort_order=10)
    t("EPDM", "transition", "EPDM Membrane",                "membrane",   "lnft", 2.0, 0.15, sort_order=10)
    t("PVC", "transition", "PVC Membrane",                   "membrane",   "lnft", 2.0, 0.15, sort_order=10)
    t("common", "transition", "Polyurethane Sealant",        "sealant",    "each", 0.375, 0.10, sort_order=20)
    t("common", "transition", "Termination Bar",             "accessory",  "lnft", 1.0, 0.05, sort_order=30)
    t("common", "transition", "Transition Fasteners",        "fastener",   "each", 2.0, 0.10, sort_order=40)

    # ════════════════════════════════════════════════════════════════════════
    # EXPANSION JOINT — premade cover + sealant
    # ════════════════════════════════════════════════════════════════════════

    t("common", "expansion_joint", "Expansion Joint Cover",  "accessory",  "lnft", 1.0, 0.05, sort_order=10)
    t("common", "expansion_joint", "Polyurethane Sealant",   "sealant",    "each", 0.375, 0.10, sort_order=20)

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

    # Helper: name, manufacturer, category, unit, cost, labor,
    #         purchase_unit, units_per_purchase, product_name
    def c(name, mfr, cat, unit, cost, labor=None,
          p_unit=None, p_per=None, p_name=None):
        items.append(CostDatabaseItem(
            material_name=name, manufacturer=mfr,
            material_category=cat, unit=unit,
            unit_cost=cost, labor_cost_per_unit=labor, is_active=True,
            org_id=None, is_global=True,
            purchase_unit=p_unit, units_per_purchase=p_per,
            product_name=p_name
        ))

    # ── Membranes ──
    c("TPO Membrane", "Carlisle", "membrane", "sqft", 0.85, 0.75,
      "Roll", 1000, "TPO 60mil White 10x100")
    c("TPO Membrane", "GAF", "membrane", "sqft", 0.82, 0.75,
      "Roll", 1000, "GAF EverGuard TPO 60mil 10x100")
    c("EPDM Membrane", "Carlisle", "membrane", "sqft", 0.65, 0.70,
      "Roll", 1000, "EPDM 60mil Black 10x100")
    c("PVC Membrane", "Carlisle", "membrane", "sqft", 1.10, 0.80,
      "Roll", 1000, "PVC 60mil White 10x100")
    c("PVC Membrane", "GAF", "membrane", "sqft", 1.05, 0.80,
      "Roll", 1000, "GAF EverGuard PVC 60mil 10x100")

    # ── Insulation ──
    c("Bottom Insulation Layer", "TBD", "insulation", "sqft", 0.55, 0.30,
      "Pcs", 32, "Polyiso 2.6in 4x8 (R-15)")
    c("Top Insulation Layer", "TBD", "insulation", "sqft", 0.55, 0.30,
      "Pcs", 32, "Polyiso 1.5in 4x8 (R-8.6)")
    c("Coverboard", "TBD", "coverboard", "sqft", 0.45, 0.25,
      "Pcs", 32, "HD Coverboard 0.5in 4x8")
    c("Base Sheet (if needed)", "TBD", "base_sheet", "sqft", 0.35, 0.25,
      "Roll", 1000, "Fiberglass Base Sheet 3x333")

    # ── Insulation Fasteners & Plates ──
    c("Insulation Fasteners", "Carlisle", "fastener", "each", 0.18, 0.10,
      "Box", 500, "HD Fastener #15 (500ct)")
    c("Insulation Plates", "Carlisle", "fastener", "each", 0.12, 0.05,
      "Box", 1000, "3in Insulation Plates (1000ct)")

    # ── Membrane Fasteners & Plates ──
    c("Membrane Fasteners (screws)", "Carlisle", "fastener", "each", 0.22, 0.10,
      "Box", 500, "Membrane Screw #14 (500ct)")
    c("Membrane Plates (seam plates)", "Carlisle", "fastener", "each", 0.15, 0.08,
      "Box", 1000, "Seam Plates (1000ct)")
    c("Membrane Screws & Seam Plates", "Carlisle", "fastener", "each", 0.35, 0.15,
      "Box", 500, "Membrane Screw + Plate Kit (500ct)")
    c("Membrane Screws & Plates", "Carlisle", "fastener", "each", 0.35, 0.15,
      "Box", 500, "Membrane Screw + Plate Kit (500ct)")

    # ── Adhesives ──
    c("TPO Bonding Adhesive", "Carlisle", "adhesive", "gallon", 20.00, 5.00,
      "Pail", 5, "TPO Bonding Adhesive 5-Gal Pail")
    c("EPDM Bonding Adhesive", "Carlisle", "adhesive", "gallon", 22.00, 5.00,
      "Pail", 5, "EPDM Bonding Adhesive 5-Gal Pail")
    c("PVC Bonding Adhesive", "Carlisle", "adhesive", "gallon", 24.00, 5.00,
      "Pail", 5, "PVC Bonding Adhesive 5-Gal Pail")

    # ── Sealants ──
    c("Waterblock Sealant", "Carlisle", "sealant", "each", 12.50, 3.00,
      "Tube", 1, "Waterblock Sealant 10.3oz Tube")
    c("Polyurethane Sealant", "Tremco", "sealant", "each", 8.50, 2.00,
      "Tube", 1, "Polyurethane Sealant 10.1oz Tube")
    c("Pourable Sealer", "Carlisle", "sealant", "each", 18.00, 5.00,
      "Tube", 1, "Pourable Sealer 28oz Tube")

    # ── Primers ──
    c("TPO Primer", "Carlisle", "adhesive", "gallon", 28.00, 5.00,
      "Pail", 5, "TPO Primer 5-Gal Pail")
    c("EPDM Primer", "Carlisle", "adhesive", "gallon", 28.00, 5.00,
      "Pail", 5, "EPDM Primer 5-Gal Pail")
    c("PVC Primer", "Carlisle", "adhesive", "gallon", 28.00, 5.00,
      "Pail", 5, "PVC Primer 5-Gal Pail")

    # ── Flashing ──
    c("Pipe Boot Flashing", "Portals Plus", "flashing", "each", 12.00, 15.00,
      "EA", 1, "Pipe Boot Flashing (each)")
    c("Corner Flashing (Aluminum)", "Tremco", "flashing", "lnft", 2.50, 3.50,
      "Pcs", 10, "Corner Flashing 24ga 10ft Pcs")
    c("Metal Edge Flashing (24ga)", "Metal Era", "flashing", "lnft", 3.50, 2.50,
      "Sticks", 10, "Edge Flashing 24ga 10ft Sticks")
    c("Drip Edge (Aluminum)", "Metal Era", "flashing", "lnft", 2.25, 2.00,
      "Sticks", 10, "Drip Edge Aluminum 10ft Sticks")
    c("Metal Scupper Box", "Metal Era", "flashing", "each", 45.00, 25.00,
      "EA", 1, "Metal Scupper Box (each)")

    # ── Accessories ──
    c("Termination Bar", "Metal Era", "accessory", "lnft", 1.50, 1.25,
      "Sticks", 10, "Termination Bar 10ft Sticks")
    c("Termination Bar Fasteners", "Carlisle", "fastener", "each", 0.22, 0.08,
      "Box", 500, "Term Bar Fasteners (500ct)")
    c("Premolded Sealant Pocket", "Portals Plus", "accessory", "each", 22.00, 20.00,
      "EA", 1, "Premolded Sealant Pocket (each)")
    c("Perimeter Fasteners", "OMG", "fastener", "each", 0.35, 0.15,
      "Box", 500, "Perimeter Fasteners (500ct)")
    c("Corner Fasteners", "OMG", "fastener", "each", 0.35, 0.15,
      "Box", 500, "Corner Fasteners (500ct)")
    c("Edge Fasteners", "OMG", "fastener", "each", 0.25, 0.12,
      "Box", 500, "Edge Fasteners (500ct)")
    c("Transition Fasteners", "OMG", "fastener", "each", 0.25, 0.12,
      "Box", 500, "Transition Fasteners (500ct)")
    c("Expansion Joint Cover", "Tremco", "accessory", "lnft", 8.50, 6.00,
      "Sticks", 10, "Expansion Joint Cover 10ft Sticks")

    # ── Coping ──
    c("Coping Metal (24ga)", "Metal Era", "flashing", "lnft", 6.50, 4.00,
      "Sticks", 10, "Coping Metal 24ga 10ft Sticks")
    c("Coping Fasteners", "OMG", "fastener", "each", 0.25, 0.12,
      "Box", 500, "Coping Fasteners (500ct)")

    # ── Mod Bit ──
    c("SBS Mod Bit Cap Sheet", "GAF", "membrane", "sqft", 0.95, 0.85,
      "Roll", 100, "SBS Mod Bit Cap Sheet 3x33.3")
    c("Mod Bit Base Sheet", "GAF", "membrane", "sqft", 0.55, 0.45,
      "Roll", 100, "Mod Bit Base Sheet 3x33.3")
    c("Hot Asphalt (Type III)", "Building Products", "adhesive", "gallon", 8.50, 3.00,
      "Pail", 5, "Hot Asphalt Type III 5-Gal")
    c("Mod Bit Primer", "GAF", "adhesive", "gallon", 28.00, 5.00,
      "Pail", 5, "Mod Bit Primer 5-Gal Pail")
    c("Mod Bit Mastic", "GAF", "sealant", "gallon", 32.00, 8.00,
      "Pail", 5, "Mod Bit Mastic 5-Gal Pail")
    c("Mod Bit Edge Strip", "GAF", "membrane", "lnft", 1.20, 0.90,
      "Roll", 50, "Mod Bit Edge Strip 50ft Roll")

    # ── BUR ──
    c("Fiberglass Felt Ply (Type IV)", "Johns Manville", "membrane", "sqft", 0.18, 0.30,
      "Roll", 432, "Type IV Felt 36in x 144ft")
    c("BUR Flood Coat (Gravel)", "Building Products", "accessory", "sqft", 0.12, 0.20)
    c("Roofing Gravel (#4 Aggregate)", "Local Supply", "accessory", "sqft", 0.08, 0.15)
    c("BUR Mastic", "Johns Manville", "sealant", "gallon", 30.00, 8.00,
      "Pail", 5, "BUR Mastic 5-Gal Pail")
    c("BUR Edge Strip Ply", "Johns Manville", "membrane", "lnft", 0.55, 0.40,
      "Roll", 50, "BUR Edge Strip 50ft Roll")

    # ── Standing Seam Metal ──
    c("24ga Standing Seam Panel (Galvalume)", "MBCI", "membrane", "sqft", 3.85, 2.50,
      "Panel", 30, "24ga Standing Seam Panel 2x15ft")
    c("Standing Seam Clip (Fixed)", "MBCI", "fastener", "each", 0.65, 0.20,
      "Box", 100, "Fixed Clip (100ct)")
    c("Standing Seam Clip (Floating)", "MBCI", "fastener", "each", 0.85, 0.20,
      "Box", 100, "Floating Clip (100ct)")
    c("Panel Screw (#12x1.5)", "OMG", "fastener", "each", 0.08, 0.05,
      "Box", 250, "Panel Screws #12x1.5 (250ct)")
    c("Underlayment (Synthetic)", "GAF", "accessory", "sqft", 0.12, 0.10,
      "Roll", 1000, "Synthetic Underlayment 10x100")
    c("Eave Trim (24ga)", "MBCI", "flashing", "lnft", 4.50, 3.00,
      "Sticks", 10, "Eave Trim 24ga 10ft Sticks")
    c("Gable Trim (24ga)", "MBCI", "flashing", "lnft", 4.50, 3.00,
      "Sticks", 10, "Gable Trim 24ga 10ft Sticks")
    c("Hip/Valley Flashing (24ga)", "MBCI", "flashing", "lnft", 5.00, 4.00,
      "Sticks", 10, "Hip/Valley Flashing 24ga 10ft Sticks")
    c("Pipe Boot (Metal)", "Portals Plus", "flashing", "each", 16.00, 15.00,
      "EA", 1, "Metal Pipe Boot (each)")
    c("Metal Sealant (Butyl)", "Tremco", "sealant", "gallon", 28.00, 6.00,
      "Pail", 5, "Butyl Sealant 5-Gal Pail")
    c("Ridge Cap (24ga)", "MBCI", "flashing", "lnft", 6.00, 4.00,
      "Sticks", 10, "Ridge Cap 24ga 10ft Sticks")
    c("Ridge Vent (Continuous)", "Lomanco", "accessory", "lnft", 3.50, 2.00,
      "Sticks", 4, "Ridge Vent 4ft Sections")
    c("Transition Flashing (24ga)", "MBCI", "flashing", "lnft", 5.50, 4.00,
      "Sticks", 10, "Transition Flashing 24ga 10ft Sticks")

    # ── Membrane strips (for edge/perimeter) ──
    c("TPO Strip (6in)", "Carlisle", "membrane", "lnft", 0.75, 0.50,
      "Roll", 100, "TPO Strip 6in x 100ft")
    c("EPDM Edge Strip", "Carlisle", "membrane", "lnft", 1.10, 0.90,
      "Roll", 100, "EPDM Edge Strip 100ft Roll")
    c("PVC Edge Strip", "Carlisle", "membrane", "lnft", 1.40, 1.00,
      "Roll", 100, "PVC Edge Strip 100ft Roll")

    # ── Vapor Barrier ──
    c("Vapor Barrier", "TBD", "accessory", "sqft", 0.15, 0.10,
      "Roll", 1000, "Vapor Barrier 10x100")

    db.add_all(items)
    db.commit()
    print(f"Seeded {len(items)} global cost database items.")


def update_global_purchase_units(db: Session):
    """
    Update existing global cost items with purchase_unit data.
    Called on startup or manually to backfill purchase units on items
    that were seeded before purchase_unit columns existed.
    """
    # Build a lookup of purchase_unit data from the seed definitions
    purchase_data = {
        # Membranes
        ("tpo membrane", "sqft"): ("Roll", 1000, "TPO 60mil White 10x100"),
        ("epdm membrane", "sqft"): ("Roll", 1000, "EPDM 60mil Black 10x100"),
        ("pvc membrane", "sqft"): ("Roll", 1000, "PVC 60mil White 10x100"),
        # Insulation
        ("bottom insulation layer", "sqft"): ("Pcs", 32, "Polyiso 2.6in 4x8 (R-15)"),
        ("top insulation layer", "sqft"): ("Pcs", 32, "Polyiso 1.5in 4x8 (R-8.6)"),
        ("coverboard", "sqft"): ("Pcs", 32, "HD Coverboard 0.5in 4x8"),
        ("base sheet (if needed)", "sqft"): ("Roll", 1000, "Fiberglass Base Sheet 3x333"),
        # Fasteners
        ("insulation fasteners", "each"): ("Box", 500, "HD Fastener #15 (500ct)"),
        ("insulation plates", "each"): ("Box", 1000, "3in Insulation Plates (1000ct)"),
        ("membrane fasteners (screws)", "each"): ("Box", 500, "Membrane Screw #14 (500ct)"),
        ("membrane plates (seam plates)", "each"): ("Box", 1000, "Seam Plates (1000ct)"),
        ("membrane screws & seam plates", "each"): ("Box", 500, "Membrane Screw + Plate Kit (500ct)"),
        ("membrane screws & plates", "each"): ("Box", 500, "Membrane Screw + Plate Kit (500ct)"),
        # Adhesives
        ("tpo bonding adhesive", "gallon"): ("Pail", 5, "TPO Bonding Adhesive 5-Gal Pail"),
        ("epdm bonding adhesive", "gallon"): ("Pail", 5, "EPDM Bonding Adhesive 5-Gal Pail"),
        ("pvc bonding adhesive", "gallon"): ("Pail", 5, "PVC Bonding Adhesive 5-Gal Pail"),
        # Sealants
        ("waterblock sealant", "each"): ("Tube", 1, "Waterblock Sealant 10.3oz Tube"),
        ("polyurethane sealant", "each"): ("Tube", 1, "Polyurethane Sealant 10.1oz Tube"),
        ("pourable sealer", "each"): ("Tube", 1, "Pourable Sealer 28oz Tube"),
        # Primers
        ("tpo primer", "gallon"): ("Pail", 5, "TPO Primer 5-Gal Pail"),
        ("epdm primer", "gallon"): ("Pail", 5, "EPDM Primer 5-Gal Pail"),
        ("pvc primer", "gallon"): ("Pail", 5, "PVC Primer 5-Gal Pail"),
        # Flashing
        ("pipe boot flashing", "each"): ("EA", 1, "Pipe Boot Flashing (each)"),
        ("corner flashing (aluminum)", "lnft"): ("Pcs", 10, "Corner Flashing 24ga 10ft Pcs"),
        ("metal edge flashing (24ga)", "lnft"): ("Sticks", 10, "Edge Flashing 24ga 10ft Sticks"),
        ("drip edge (aluminum)", "lnft"): ("Sticks", 10, "Drip Edge Aluminum 10ft Sticks"),
        ("metal scupper box", "each"): ("EA", 1, "Metal Scupper Box (each)"),
        # Accessories
        ("termination bar", "lnft"): ("Sticks", 10, "Termination Bar 10ft Sticks"),
        ("termination bar fasteners", "each"): ("Box", 500, "Term Bar Fasteners (500ct)"),
        ("premolded sealant pocket", "each"): ("EA", 1, "Premolded Sealant Pocket (each)"),
        ("perimeter fasteners", "each"): ("Box", 500, "Perimeter Fasteners (500ct)"),
        ("corner fasteners", "each"): ("Box", 500, "Corner Fasteners (500ct)"),
        ("edge fasteners", "each"): ("Box", 500, "Edge Fasteners (500ct)"),
        ("transition fasteners", "each"): ("Box", 500, "Transition Fasteners (500ct)"),
        ("expansion joint cover", "lnft"): ("Sticks", 10, "Expansion Joint Cover 10ft Sticks"),
        # Coping
        ("coping metal (24ga)", "lnft"): ("Sticks", 10, "Coping Metal 24ga 10ft Sticks"),
        ("coping fasteners", "each"): ("Box", 500, "Coping Fasteners (500ct)"),
        # Vapor Barrier
        ("vapor barrier", "sqft"): ("Roll", 1000, "Vapor Barrier 10x100"),
    }

    global_items = db.query(CostDatabaseItem).filter(
        CostDatabaseItem.is_global == True
    ).all()

    updated = 0
    for item in global_items:
        key = (item.material_name.lower().strip(), (item.unit or "").lower().strip())
        if key in purchase_data:
            p_unit, p_per, p_name = purchase_data[key]
            if item.purchase_unit != p_unit or item.units_per_purchase != p_per:
                item.purchase_unit = p_unit
                item.units_per_purchase = p_per
                item.product_name = p_name
                updated += 1

    if updated:
        db.flush()
    print(f"[seed] Updated {updated} global items with purchase_unit data")
    return updated


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
            purchase_unit=c.purchase_unit,
            units_per_purchase=c.units_per_purchase,
            product_name=c.product_name,
            is_active=True,
            org_id=org_id,
            is_global=False,
        )
        db.add(new_c)
        cloned_costs += 1

    db.flush()
    print(f"[seed] Cloned {cloned_templates} templates and {cloned_costs} cost items for org {org_id}")
    return {"templates": cloned_templates, "cost_items": cloned_costs}


def resync_cost_items_for_org(org_id: int, db: Session, update_pricing: bool = False):
    """
    Re-sync an existing org's cost database from global platform defaults.
    - Any global item missing from the org gets cloned in.
    - If update_pricing=True, also updates pricing + purchase_unit on existing items.
    - Org-created custom items are never touched.
    """
    global_costs = db.query(CostDatabaseItem).filter(
        CostDatabaseItem.is_global == True,
        CostDatabaseItem.is_active == True
    ).all()

    org_costs = db.query(CostDatabaseItem).filter(
        CostDatabaseItem.org_id == org_id,
        CostDatabaseItem.is_global == False
    ).all()

    # Index org items by (lower material_name, lower unit)
    org_index = {}
    for oc in org_costs:
        key = (oc.material_name.lower().strip(), (oc.unit or "").lower().strip())
        if key not in org_index:
            org_index[key] = oc

    added = 0
    updated = 0

    for gc in global_costs:
        key = (gc.material_name.lower().strip(), (gc.unit or "").lower().strip())

        if key not in org_index:
            # Missing — clone it in
            new_c = CostDatabaseItem(
                material_name=gc.material_name,
                manufacturer=gc.manufacturer,
                material_category=gc.material_category,
                unit=gc.unit,
                unit_cost=gc.unit_cost,
                labor_cost_per_unit=gc.labor_cost_per_unit,
                purchase_unit=gc.purchase_unit,
                units_per_purchase=gc.units_per_purchase,
                product_name=gc.product_name,
                is_active=True,
                org_id=org_id,
                is_global=False,
            )
            db.add(new_c)
            added += 1
        else:
            # Exists — optionally update purchase_unit info + pricing
            existing = org_index[key]
            if update_pricing:
                existing.unit_cost = gc.unit_cost
                existing.labor_cost_per_unit = gc.labor_cost_per_unit
            # Always sync purchase unit data if the org item doesn't have it yet
            if not existing.purchase_unit and gc.purchase_unit:
                existing.purchase_unit = gc.purchase_unit
                existing.units_per_purchase = gc.units_per_purchase
                existing.product_name = gc.product_name
                updated += 1
            elif update_pricing and gc.purchase_unit:
                existing.purchase_unit = gc.purchase_unit
                existing.units_per_purchase = gc.units_per_purchase
                existing.product_name = gc.product_name
                updated += 1

    db.flush()
    print(f"[resync] Org {org_id}: added {added}, updated {updated} cost items")
    return {"added": added, "updated": updated}


def migrate_consolidate_perimeter_bar(db: Session):
    """Rename 'Perimeter Bar (Aluminum)' → 'Termination Bar' everywhere."""
    # Update material templates
    updated_templates = db.query(MaterialTemplate).filter(
        MaterialTemplate.material_name == "Perimeter Bar (Aluminum)"
    ).update({"material_name": "Termination Bar"}, synchronize_session=False)

    # Update condition materials (already-populated project materials)
    from conditions_models import ConditionMaterial
    updated_cond_mats = db.query(ConditionMaterial).filter(
        ConditionMaterial.material_name == "Perimeter Bar (Aluminum)"
    ).update({"material_name": "Termination Bar"}, synchronize_session=False)

    # Remove duplicate cost database entry for Perimeter Bar
    from conditions_models import CostDatabaseItem
    deleted_cost = db.query(CostDatabaseItem).filter(
        CostDatabaseItem.material_name == "Perimeter Bar (Aluminum)"
    ).delete(synchronize_session=False)

    if updated_templates or updated_cond_mats or deleted_cost:
        db.commit()
        print(f"[migrate] Consolidated Perimeter Bar → Termination Bar: "
              f"{updated_templates} templates, {updated_cond_mats} condition materials, "
              f"{deleted_cost} cost items removed")
    else:
        print("[migrate] Perimeter Bar already consolidated. Skipping.")


def migrate_fix_insulation_plates_packaging(db: Session):
    """Fix 3in Insulation Plates: 1000/box not 500/box."""
    from conditions_models import CostDatabaseItem
    updated = db.query(CostDatabaseItem).filter(
        CostDatabaseItem.material_name == "Insulation Plates",
        CostDatabaseItem.units_per_purchase == 500
    ).update({
        "units_per_purchase": 1000,
        "product_name": "3in Insulation Plates (1000ct)"
    }, synchronize_session=False)
    if updated:
        db.commit()
        print(f"[migrate] Fixed Insulation Plates packaging: {updated} items updated to 1000/box")
    else:
        print("[migrate] Insulation Plates packaging already correct. Skipping.")


def migrate_consolidate_sealants(db: Session):
    """Consolidate 'All Purpose Sealant' → 'Polyurethane Sealant' (tubes, not gallons)."""
    # Update material templates — rename + convert to tubes (each)
    updated_templates = db.query(MaterialTemplate).filter(
        MaterialTemplate.material_name == "All Purpose Sealant"
    ).update({
        "material_name": "Polyurethane Sealant",
        "unit": "each",
        "coverage_rate": 0.5,  # 0.5 tubes per pipe flashing
    }, synchronize_session=False)

    # Also convert any existing Polyurethane Sealant templates still in gallons → each
    updated_gallon = db.query(MaterialTemplate).filter(
        MaterialTemplate.material_name == "Polyurethane Sealant",
        MaterialTemplate.unit == "gallon"
    ).all()
    gallon_to_tube = {
        0.02: 0.25, 0.03: 0.375, 0.04: 0.5, 0.05: 0.625, 0.10: 1.25,
    }
    for tmpl in updated_gallon:
        tmpl.unit = "each"
        tmpl.coverage_rate = gallon_to_tube.get(tmpl.coverage_rate, tmpl.coverage_rate * 12.5)

    # Update condition materials
    from conditions_models import ConditionMaterial
    updated_cond_mats = db.query(ConditionMaterial).filter(
        ConditionMaterial.material_name == "All Purpose Sealant"
    ).update({
        "material_name": "Polyurethane Sealant",
        "unit": "each",
        "coverage_rate": 0.5,
    }, synchronize_session=False)

    # Also convert existing Polyurethane Sealant condition materials from gallon → each
    gallon_cond_mats = db.query(ConditionMaterial).filter(
        ConditionMaterial.material_name == "Polyurethane Sealant",
        ConditionMaterial.unit == "gallon"
    ).all()
    for cm in gallon_cond_mats:
        cm.unit = "each"
        cm.coverage_rate = gallon_to_tube.get(cm.coverage_rate, cm.coverage_rate * 12.5)

    # Remove old All Purpose Sealant cost database entry
    from conditions_models import CostDatabaseItem
    deleted_cost = db.query(CostDatabaseItem).filter(
        CostDatabaseItem.material_name == "All Purpose Sealant"
    ).delete(synchronize_session=False)

    # Update Polyurethane Sealant cost item from gallon/pail → each/tube
    db.query(CostDatabaseItem).filter(
        CostDatabaseItem.material_name == "Polyurethane Sealant",
        CostDatabaseItem.unit == "gallon"
    ).update({
        "unit": "each",
        "unit_cost": 8.50,
        "labor_cost_per_unit": 2.00,
        "purchase_unit": "Tube",
        "units_per_purchase": 1,
        "product_name": "Polyurethane Sealant 10.1oz Tube",
    }, synchronize_session=False)

    total_changes = updated_templates + len(updated_gallon) + updated_cond_mats + len(gallon_cond_mats) + deleted_cost
    if total_changes:
        db.commit()
        print(f"[migrate] Consolidated sealants → Polyurethane Sealant (tubes): "
              f"{updated_templates} renamed, {len(updated_gallon)} gallon→tube templates, "
              f"{updated_cond_mats + len(gallon_cond_mats)} condition materials, "
              f"{deleted_cost} old cost items removed")
    else:
        print("[migrate] Sealants already consolidated. Skipping.")


def seed_database(db: Session):
    """Run all seed functions."""
    print("Starting database seed...")
    seed_material_templates(db)
    seed_cost_database(db)
    # Always ensure global items have purchase_unit data
    update_global_purchase_units(db)
    # Run migrations
    migrate_consolidate_perimeter_bar(db)
    migrate_fix_insulation_plates_packaging(db)
    migrate_consolidate_sealants(db)
    db.commit()
    print("Database seeding complete.")
