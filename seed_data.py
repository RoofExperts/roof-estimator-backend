"""
Seed data for the commercial roofing estimating engine.
Creates default MaterialTemplates and CostDatabaseItems.
Each template is tagged with a system_type: TPO, EPDM, PVC, or common.
"""

from sqlalchemy.orm import Session
from conditions_models import MaterialTemplate, CostDatabaseItem


def seed_material_templates(db: Session):
    """Seed material templates for TPO, EPDM, and PVC systems with system_type tags."""
    existing = db.query(MaterialTemplate).first()
    if existing:
        print("Material templates already exist. Skipping seed.")
        return

    templates = []

    def t(system, ctype, name, cat, unit, rate, waste=0.10):
        templates.append(MaterialTemplate(
            system_type=system, condition_type=ctype, material_name=name,
            material_category=cat, unit=unit,
            coverage_rate=rate, waste_factor=waste, is_active=True
        ))

    # ======================== COMMON (shared across all systems) ========================
    # Insulation & coverboard - used by TPO, EPDM, and PVC alike
    t("common", "field", '2.6" Polyiso Insulation', "insulation", "sqft", 1.0, 0.05)
    t("common", "field", '1/2" Tapered Coverboard', "accessory", "sqft", 1.0, 0.05)
    t("common", "field", "Vapor Barrier", "accessory", "sqft", 1.0, 0.05)

    # Universal fasteners
    t("common", "field", "Field Fasteners (Plastic)", "fastener", "each", 1.0, 0.10)
    t("common", "perimeter", "Perimeter Fasteners (Stainless)", "fastener", "each", 2.0, 0.10)
    t("common", "perimeter", "Perimeter Bar (Aluminum)", "accessory", "lnft", 1.0, 0.05)
    t("common", "corner", "Corner Flashing (Aluminum)", "flashing", "lnft", 4.0, 0.05)
    t("common", "corner", "Polyurethane Sealant", "sealant", "gallon", 0.05, 0.10)
    t("common", "corner", "Corner Fasteners (Stainless)", "fastener", "each", 4.0, 0.10)

    # Universal penetration accessories
    t("common", "penetration", "Polyurethane Sealant", "sealant", "gallon", 0.10, 0.05)
    t("common", "penetration", "Pitch Pan", "accessory", "each", 1.0, 0.0)

    # Universal edge detail
    t("common", "edge_detail", "Metal Edge Flashing (24ga)", "flashing", "lnft", 1.0, 0.05)
    t("common", "edge_detail", "Drip Edge (Aluminum)", "flashing", "lnft", 1.0, 0.05)
    t("common", "edge_detail", "Polyurethane Sealant", "sealant", "gallon", 0.02, 0.10)
    t("common", "edge_detail", "Edge Fasteners", "fastener", "each", 3.0, 0.10)

    # Universal transition
    t("common", "transition", "Wall Flashing (Aluminum)", "flashing", "lnft", 1.0, 0.05)
    t("common", "transition", "Polyurethane Sealant", "sealant", "gallon", 0.03, 0.10)
    t("common", "transition", "Termination Bar", "accessory", "lnft", 1.0, 0.05)
    t("common", "transition", "Transition Fasteners", "fastener", "each", 2.0, 0.10)

    # ======================== TPO SYSTEM ========================
    t("TPO", "field", "TPO 60mil Membrane", "membrane", "sqft", 1.0, 0.10)
    t("TPO", "field", "TPO Adhesive", "adhesive", "gallon", 0.15, 0.05)
    t("TPO", "perimeter", "TPO 60mil Membrane", "membrane", "lnft", 1.0, 0.10)
    t("TPO", "perimeter", "TPO Adhesive", "adhesive", "gallon", 0.20, 0.05)
    t("TPO", "corner", "TPO 60mil Membrane", "membrane", "sqft", 2.0, 0.15)
    t("TPO", "penetration", "TPO 60mil Membrane", "membrane", "sqft", 6.0, 0.15)
    t("TPO", "penetration", "Pipe Boot Flashing", "flashing", "each", 1.0, 0.0)
    t("TPO", "penetration", "TPO Adhesive", "adhesive", "gallon", 0.05, 0.05)
    t("TPO", "edge_detail", "TPO Strip (6in)", "membrane", "lnft", 1.0, 0.10)
    t("TPO", "transition", "TPO 60mil Membrane", "membrane", "lnft", 2.0, 0.15)

    # ======================== EPDM SYSTEM ========================
    t("EPDM", "field", "EPDM 45mil Membrane", "membrane", "sqft", 1.0, 0.10)
    t("EPDM", "field", "EPDM Bonding Adhesive", "adhesive", "gallon", 0.10, 0.05)
    t("EPDM", "perimeter", "EPDM 45mil Membrane", "membrane", "lnft", 1.0, 0.10)
    t("EPDM", "corner", "EPDM 45mil Membrane", "membrane", "sqft", 2.0, 0.15)
    t("EPDM", "penetration", "EPDM 45mil Membrane", "membrane", "sqft", 6.0, 0.15)
    t("EPDM", "penetration", "EPDM Pipe Boot", "flashing", "each", 1.0, 0.0)
    t("EPDM", "penetration", "EPDM Bonding Adhesive", "adhesive", "gallon", 0.05, 0.05)
    t("EPDM", "edge_detail", "EPDM Edge Strip", "membrane", "lnft", 1.0, 0.10)
    t("EPDM", "transition", "EPDM 45mil Membrane", "membrane", "lnft", 2.0, 0.15)

    # ======================== PVC SYSTEM ========================
    t("PVC", "field", "PVC 60mil Membrane", "membrane", "sqft", 1.0, 0.10)
    t("PVC", "field", "PVC Solvent Weld", "adhesive", "gallon", 0.12, 0.05)
    t("PVC", "perimeter", "PVC 60mil Membrane", "membrane", "lnft", 1.0, 0.10)
    t("PVC", "corner", "PVC 60mil Membrane", "membrane", "sqft", 2.0, 0.15)
    t("PVC", "penetration", "PVC 60mil Membrane", "membrane", "sqft", 6.0, 0.15)
    t("PVC", "penetration", "PVC Pipe Boot", "flashing", "each", 1.0, 0.0)
    t("PVC", "penetration", "PVC Solvent Weld", "adhesive", "gallon", 0.05, 0.05)
    t("PVC", "edge_detail", "PVC Edge Strip", "membrane", "lnft", 1.0, 0.10)
    t("PVC", "transition", "PVC 60mil Membrane", "membrane", "lnft", 2.0, 0.15)

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
