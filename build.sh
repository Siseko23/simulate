#!/usr/bin/env bash
set -e

pip install -r requirements.txt

# Seed the database if it doesn't exist yet (first deploy)
if [ ! -f "freightflow.db" ]; then
  echo "🌱 First deploy — seeding database..."
  python seeds/seed.py
  echo "✅ Seed complete"
else
  echo "✅ Database already exists — running schema migration..."
fi

# Always run this: creates any new tables AND adds any new columns to
# existing tables (SQLite's create_all() only handles new tables, not
# new columns on tables that already exist — so we patch those by hand).
python - << 'PY'
import os, sys
sys.path.insert(0, os.getcwd())
os.environ.setdefault("FLASK_ENV", "production")
from app import create_app
from app.models import db
from sqlalchemy import text, inspect

app = create_app("production")
with app.app_context():
    db.create_all()
    print("✅ New tables created (if any)")

    inspector = inspect(db.engine)

    # ── Column migrations: (table, column, sql_type_with_default) ──
    column_migrations = [
        ("availability_slots", "is_blocked", "BOOLEAN DEFAULT 0"),
        ("availability_slots", "block_type", "VARCHAR(20)"),
        ("availability_slots", "reason",     "VARCHAR(200)"),
        ("bookings", "rating",         "INTEGER"),
        ("bookings", "rating_comment", "TEXT"),
        ("bookings", "rated_at",       "DATETIME"),
        ("supplier_profiles", "account_type", "VARCHAR(40) DEFAULT 'Current / Cheque'"),
        ("drivers", "pin", "VARCHAR(6) DEFAULT '0000'"),
        ("drivers", "assigned_vehicle_id", "INTEGER"),
        ("complaints", "dispute_amount", "FLOAT"),
        ("complaints", "assigned_agent_id", "INTEGER"),
        ("purchase_orders", "invoice_filename", "VARCHAR(200)"),
        ("purchase_orders", "invoice_uploaded_at", "DATETIME"),
    ]

    with db.engine.connect() as conn:
        for table, column, col_type in column_migrations:
            if table not in inspector.get_table_names():
                continue
            existing_cols = [c["name"] for c in inspector.get_columns(table)]
            if column not in existing_cols:
                conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {column} {col_type}"))
                print(f"✅ Added column {table}.{column}")
        conn.commit()


    # Backfill demo driver-to-vehicle pairings when the column was just added
    # or when an older seeded DB did not have default assignments.
    try:
        drivers = db.session.execute(text("SELECT id, supplier_id FROM drivers WHERE assigned_vehicle_id IS NULL ORDER BY id")).fetchall()
        for driver_id, supplier_id in drivers:
            vehicle = db.session.execute(text("""
                SELECT v.id FROM vehicles v
                WHERE v.supplier_id = :sid
                  AND v.id NOT IN (SELECT assigned_vehicle_id FROM drivers WHERE assigned_vehicle_id IS NOT NULL)
                ORDER BY v.id LIMIT 1
            """), {"sid": supplier_id}).fetchone()
            if vehicle:
                db.session.execute(text("UPDATE drivers SET assigned_vehicle_id = :vid WHERE id = :did"), {"vid": vehicle[0], "did": driver_id})
        db.session.commit()
        print("✅ Driver-to-vehicle pairings checked")
    except Exception as exc:
        db.session.rollback()
        print(f"⚠️ Driver-to-vehicle backfill skipped: {exc}")

    print("✅ Schema fully up to date")
PY
