"""
Lightweight database migration helper.
Adds missing columns to existing tables without needing Alembic.
Runs on app startup — safe to re-run (checks if column exists first).
"""

from sqlalchemy import text, inspect
from sqlalchemy.engine import Engine


def get_existing_columns(engine: Engine, table_name: str) -> set:
    """Get the set of column names for a table."""
    inspector = inspect(engine)
    if table_name not in inspector.get_table_names():
        return set()
    return {col["name"] for col in inspector.get_columns(table_name)}


def table_exists(engine: Engine, table_name: str) -> bool:
    """Check if a table exists."""
    inspector = inspect(engine)
    return table_name in inspector.get_table_names()


def add_column_if_missing(engine: Engine, table_name: str, column_name: str, column_type: str, default=None):
    """Add a column to a table if it doesn't already exist."""
    if not table_exists(engine, table_name):
        return False
    existing = get_existing_columns(engine, table_name)
    if column_name in existing:
        return False

    default_clause = ""
    if default is not None:
        if isinstance(default, str):
            default_clause = f" DEFAULT '{default}'"
        elif isinstance(default, bool):
            default_clause = f" DEFAULT {'TRUE' if default else 'FALSE'}"
        else:
            default_clause = f" DEFAULT {default}"

    sql = f'ALTER TABLE {table_name} ADD COLUMN {column_name} {column_type}{default_clause}'
    print(f"[migrations] Running: {sql}")
    with engine.connect() as conn:
        conn.execute(text(sql))
        conn.commit()
    return True


def run_migrations(engine: Engine):
    """Run all pending migrations."""
    print("[migrations] Checking for pending migrations...")
    changes = 0

    # ── company_settings: proposal type defaults & brand colors ──
    if add_column_if_missing(engine, "company_settings", "proposal_type_defaults_json", "TEXT"):
        changes += 1
    if add_column_if_missing(engine, "company_settings", "primary_color", "VARCHAR", "#1e40af"):
        changes += 1
    if add_column_if_missing(engine, "company_settings", "secondary_color", "VARCHAR", "#475569"):
        changes += 1
    if add_column_if_missing(engine, "company_settings", "accent_color", "VARCHAR", "#059669"):
        changes += 1

    # ── material_templates: system_type column ──
    if add_column_if_missing(engine, "material_templates", "system_type", "VARCHAR", "common"):
        changes += 1

    # ====================================================================
    # MULTI-TENANT MIGRATIONS
    # ====================================================================

    # ── New tables are created by Base.metadata.create_all in main.py ──
    # organizations, organization_members, user_invites

    # ── users: current_org_id ──
    if add_column_if_missing(engine, "users", "current_org_id", "INTEGER"):
        changes += 1

    # ── projects: org_id ──
    if add_column_if_missing(engine, "projects", "org_id", "INTEGER"):
        changes += 1

    # ── customers: org_id ──
    if add_column_if_missing(engine, "customers", "org_id", "INTEGER"):
        changes += 1

    # ── saved_proposals: org_id ──
    if add_column_if_missing(engine, "saved_proposals", "org_id", "INTEGER"):
        changes += 1

    # ── company_settings: org_id ──
    if add_column_if_missing(engine, "company_settings", "org_id", "INTEGER"):
        changes += 1

    # ── material_templates: org_id + is_global ──
    if add_column_if_missing(engine, "material_templates", "org_id", "INTEGER"):
        changes += 1
    if add_column_if_missing(engine, "material_templates", "is_global", "BOOLEAN", False):
        changes += 1

    # ── cost_database_items: org_id + is_global ──
    if add_column_if_missing(engine, "cost_database_items", "org_id", "INTEGER"):
        changes += 1
    if add_column_if_missing(engine, "cost_database_items", "is_global", "BOOLEAN", False):
        changes += 1

    if changes:
        print(f"[migrations] Applied {changes} migration(s).")
    else:
        print("[migrations] No pending migrations.")

    # ── Backfill existing data into default org ──
    backfill_existing_data(engine)


def backfill_existing_data(engine: Engine):
    """
    If there are existing users but no organizations, create a default org
    and assign all existing data to it. Safe to re-run.
    """
    if not table_exists(engine, "organizations"):
        return

    from database import SessionLocal
    db = SessionLocal()
    try:
        from models import Organization, OrganizationMember, User, Project, Customer, CompanySettings, SavedProposal
        from conditions_models import MaterialTemplate, CostDatabaseItem

        # Only backfill if: users exist but no orgs exist
        user_count = db.query(User).count()
        org_count = db.query(Organization).count()

        if user_count == 0 or org_count > 0:
            return

        print("[migrations] Backfilling existing data into default organization...")

        # Create default org
        org = Organization(name="Roof Experts")
        db.add(org)
        db.flush()

        # Assign all users to this org
        for user in db.query(User).all():
            user.current_org_id = org.id
            member = OrganizationMember(
                org_id=org.id,
                user_id=user.id,
                role=user.role or "estimator"
            )
            db.add(member)

        # Make first user the owner
        first_member = db.query(OrganizationMember).filter(
            OrganizationMember.org_id == org.id
        ).first()
        if first_member:
            first_member.role = "owner"

        # Set org_id on all existing data
        db.query(Project).filter(Project.org_id == None).update(
            {Project.org_id: org.id}, synchronize_session=False
        )
        db.query(Customer).filter(Customer.org_id == None).update(
            {Customer.org_id: org.id}, synchronize_session=False
        )
        db.query(SavedProposal).filter(SavedProposal.org_id == None).update(
            {SavedProposal.org_id: org.id}, synchronize_session=False
        )
        db.query(CompanySettings).filter(CompanySettings.org_id == None).update(
            {CompanySettings.org_id: org.id}, synchronize_session=False
        )

        # Mark existing templates and cost items as global seed data
        db.query(MaterialTemplate).filter(MaterialTemplate.org_id == None).update(
            {MaterialTemplate.is_global: True}, synchronize_session=False
        )
        db.query(CostDatabaseItem).filter(CostDatabaseItem.org_id == None).update(
            {CostDatabaseItem.is_global: True}, synchronize_session=False
        )

        db.commit()
        print(f"[migrations] Backfill complete. Created org '{org.name}' (id={org.id}) with {user_count} user(s).")

    except Exception as e:
        db.rollback()
        print(f"[migrations] Backfill error: {e}")
    finally:
        db.close()
