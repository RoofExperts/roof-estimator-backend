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


def add_column_if_missing(engine: Engine, table_name: str, column_name: str, column_type: str, default=None):
    """Add a column to a table if it doesn't already exist."""
    existing = get_existing_columns(engine, table_name)
    if column_name in existing:
        return False

    default_clause = ""
    if default is not None:
        if isinstance(default, str):
            default_clause = f" DEFAULT '{default}'"
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

    if changes:
        print(f"[migrations] Applied {changes} migration(s).")
    else:
        print("[migrations] No pending migrations.")
