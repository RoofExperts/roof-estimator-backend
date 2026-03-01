"""
Seed data for the commercial roofing estimating engine.
Creates default MaterialTemplates and CostDatabaseItems.
"""

from sqlalchemy.orm import Session
from conditions_models import MaterialTemplate, CostDatabaseItem


def seed_material_templates(db: Session):
    """Seed material templates for TPO, EPDM, and PVC systems."""
    existing = db.query(MaterialTemplate).first()
    if existing:
        print("Material templates already exist. Skipping seed.")
        return

    templates = []

    # Helper to add a template
    def t(ctype, name, cat, unit, rate, waste=0.10):
        templates.append(MaterialTemplate(
            condition_type=ctype, material_name=name,
            material_category=cat, unit=unit,
            coverage_rate=rate, waste_factor=waste, is_active=True
        ))

    # ======================== FIELD ========================
    t("field", "TPO 60mil Membrane", "membrane", "sqft", 1.0, 0.10)
    t("field", '2.6" Polyiso Insulation', "insulation", "sqft", 1.0, 0.05)
    t("field", '1/2" Tapered Coverboard', "accessory", "sqft", 1.0, 0.05)
    t("field", "Field Fasteners (Plastic)", "fastener", "each", 1.0, 0.10)
    t("field", "TPO Adhesive", "adhesive", "gallon", 0.15, 0.05)
    t("field", "Vapor Barrier", "accessory", "sqft", 1.0, 0.05)

    # ======================== PERIMETER ========================
    t("perimeter", "TPO 60mil Membrane", "membrane", "lnft", 1.0, 0.10)
    t("perimeter", "Perimeter Fasteners (Stainless)", "fastener", "each", 2.0, 0.10)
    t("perimeter", "TPO Adhesive", "adhesive", "gallon", 0.20, 0.05)
    t("perimeter", "Perimeter Bar (Aluminum)", "accessory", "lnft", 1.0, 0.05)

    # ======================== CORNER ========================
    t("corner", "TPO 60mil Membrane", "membrane", "sqft", 2.0, 0.15)
    t("corner", "Corner Flashing (Aluminum)", "flashing", "lnft", 4.0, 0.05)
    t("corner", "Polyurethane Sealant", "sealant", "gallon", 0.05, 0.10)
    t("corner", "Corner Fasteners (Stainless)", "fastener", "each", 4.0, 0.10)

    # ======================== PENETRATION ========================
    t("penetration", "TPO 60mil Membrane", "membrane", "sqft", 6.0, 0.15)
    t("penetration", "Pipe Boot Flashing", "flashing", "each", 1.0, 0.0)
    t("penetration", "Polyurethane Sealant", "sealant", "gallon", 0.10, 0.05)
    t("penetration", "Pitch Pan", "accessory", "each", 1.0, 0.0)
    t("penetration", "TPO Adhesive", "adhesive", "gallon", 0.05, 0.05)

    # ======================== EDGE DETAIL ========================
    t("edge_detail", "Metal Edge Flashing (24ga)", "flashing", "lnft", 1.0, 0.05)
    t("edge_detail", "Drip Edge (Aluminum)", "flashing", "lnft", 1.0, 0.05)
    t("edge_detail", "Polyurethane Sealant", "sealant", "gallon", 0.02, 0.10)
    t("edge_detail", "Edge Fasteners", "fastener", "each", 3.0, 0.10)
    t("edge_detail", "TPO Strip (6in)", "membrane", "lnft", 1.0, 0.10)

    # ======================== TRANSITION ========================
    t("transition", "TPO 60mil Membrane", "membrane", "lnft", 2.0, 0.15)
    t("transition", "Wall Flashing (Aluminum)", "flashing", "lnft", 1.0, 0.05)
    t("transition", "Polyurethane Sealant", "sealant", "gallon", 0.03, 0.10)
    t("transition", "Termination Bar", "accessory", "lnft", 1.0, 0.05)
    t("transition", "Transition Fasteners", "fastener", "each", 2.0, 0.10)

    # ======================== EPDM SYSTEM ========================
    t("field", "EPDM 45mil Membrane", "membrane", "sqft", 1.0, 0.10)
    t("field", "EPDM Bonding Adhesive", "adhesive", "gallon", 0.10, 0.05)
    t("perimeter", "EPDM 45mil Membrane", "membrane", "lnft", 1.0, 0.10)
    t("corner", "EPDM 45mil Membrane", "membrane", "sqft", 2.0, 0.15)
    t("penetration", "EPDM Pipe Boot", "flashing", "each", 1.0, 0.0)
    t("edge_detail", "EPDM Edge Strip", "membrane", "lnft", 1.0, 0.10)
    t("transition", "EPDM 45mil Membrane", "membrane", "lnft", 2.0, 0.15)

    # ======================== PVC SYSTEM ========================
    t("field", "PVC 60mil Membrane", "membrane", "sqft", 1.0, 0.10)
    t("field", "PVC Solvent Weld", "adhesive", "gallon", 0.12, 0.05)
    t("perimeter", "PVC 60mil Membrane", "membrane", "lnft", 1.0, 0.10)
    t("corner", "PVC 60mil Membrane", "membrane", "sqft", 2.0, 0.15)
    t("penetration", "PVC Pipe Boot", "flashing", "each", 1.0, 0.0)
    t("edge_detail", "PVC Edge Strip", "membrane", "lnft", 1.0, 0.10)
    t("transition", "PVC 60mil Membrane", "membrane", "lnft", 2.0, 0.15)

    db.add_all(templates)
    db.commit()
    print(f"Seeded {len(templates)} material templates.")


def seed_cost_database(db: Session):
    """Seed the cost database with realistic commercial roofing pricing."""
    existing = db.query(CostDatabaseItem).first()
    if existing:
        print("Cost database already populated. Skipping seed.")
        return

    items = []

    def c(name, mfr, cat, unit, cost, labor=None):
        items.append(CostDatabaseItem(
            material_name=name, manufacturer=mfr,
            material_category=cat, unit=unit,
            unit_cost=cost, labor_cost_per_unit=labor, is_active=True
        ))

    # Membranes
    c("TPO 60mil Membrane", "Carlisle", "membrane", "sqft", 0.85, 0.75)
    c("TPO 60mil Membrane", "Carlisle", "membrane", "lnft", 1.25, 1.00)
    c("EPDM 45mil Membrane", "Firestone", "membrane", "sqft", 0.65, 0.70)
    c("EPDM 45mil Membrane", "Firestone", "membrane", "lnft", 0.95, 0.90)
    c("PVC 60mil Membrane", "Sika Sarnafil", "membrane", "sqft", 1.10, 0.80)
    c("PVC 60mil Membrane", "Sika Sarnafil", "membrane", "lnft", 1.50, 1.10)

    # Insulation
    c('2.6" Polyiso Insulation', "GAF", "insulation", "sqft", 0.65, 0.35)
    c('1/2" Tapered Coverboard', "DensDeck", "accessory", "sqft", 0.45, 0.25)

    # Fasteners
    c("Field Fasteners (Plastic)", "OMG", "fastener", "each", 0.15, 0.10)
    c("Perimeter Fasteners (Stainless)", "OMG", "fastener", "each", 0.35, 0.15)
    c("Corner Fasteners (Stainless)", "OMG", "fastener", "each", 0.35, 0.15)
    c("Edge Fasteners", "OMG", "fastener", "each", 0.25, 0.12)
    c("Transition Fasteners", "OMG", "fastener", "each", 0.25, 0.12)

    # Adhesives
    c("TPO Adhesive", "Carlisle", "adhesive", "gallon", 18.50, 5.00)
    c("EPDM Bonding Adhesive", "Firestone", "adhesive", "gallon", 22.00, 5.00)
    c("PVC Solvent Weld", "Sika Sarnafil", "adhesive", "gallon", 24.00, 5.00)

    # Flashing
    c("Corner Flashing (Aluminum)", "Tremco", "flashing", "lnft", 2.50, 3.50)
    c("Pipe Boot Flashing", "Portals Plus", "flashing", "each", 12.00, 15.00)
    c("Metal Edge Flashing (24ga)", "Metal Era", "flashing", "lnft", 3.50, 2.50)
    c("Drip Edge (Aluminum)", "Metal Era", "flashing", "lnft", 2.25, 2.00)
    c("Wall Flashing (Aluminum)", "Tremco", "flashing", "lnft", 3.00, 3.50)
    c("EPDM Pipe Boot", "Firestone", "flashing", "each", 10.00, 15.00)
    c("PVC Pipe Boot", "Sika Sarnafil", "flashing", "each", 14.00, 15.00)
    c("EPDM Edge Strip", "Firestone", "membrane", "lnft", 1.10, 0.90)
    c("PVC Edge Strip", "Sika Sarnafil", "membrane", "lnft", 1.40, 1.00)
    c("TPO Strip (6in)", "Carlisle", "membrane", "lnft", 0.75, 0.50)

    # Sealants
    c("Polyurethane Sealant", "Tremco", "sealant", "gallon", 35.00, 8.00)

    # Accessories
    c("Vapor Barrier", "Carlisle", "accessory", "sqft", 0.15, 0.10)
    c("Pitch Pan", "Portals Plus", "accessory", "each", 18.00, 20.00)
    c("Perimeter Bar (Aluminum)", "Metal Era", "accessory", "lnft", 1.75, 1.50)
    c("Termination Bar", "Metal Era", "accessory", "lnft", 1.50, 1.25)

    db.add_all(items)
    db.commit()
    print(f"Seeded {len(items)} cost database items.")


def seed_database(db: Session):
    """Run all seed functions."""
    print("Starting database seed...")
    seed_material_templates(db)
    seed_cost_database(db)
    print("Database seeding complete.")
