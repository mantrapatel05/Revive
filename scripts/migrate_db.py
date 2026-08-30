"""Execute PostgreSQL migrations for REVIVE.

Applies schema.sql against PostgreSQL using ADMIN_DATABASE_URL credentials.
Can be executed directly via `python scripts/migrate_db.py` or `make db-migrate`.
"""
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import psycopg2
from app.config import ADMIN_DATABASE_URL

def migrate(url: str | None = None) -> None:
    db_url = url or ADMIN_DATABASE_URL or os.getenv("ADMIN_DATABASE_URL")
    if not db_url:
        print("ERROR: ADMIN_DATABASE_URL is not set.")
        sys.exit(1)

    schema_file = ROOT / "schema.sql"
    if not schema_file.exists():
        print(f"ERROR: Schema file not found at {schema_file}")
        sys.exit(1)

    sql = schema_file.read_text(encoding="utf-8")
    masked_url = db_url
    if "@" in db_url:
        prefix, host = db_url.split("@", 1)
        user_part = prefix.split("://", 1)[-1].split(":", 1)[0]
        masked_url = f"postgresql://{user_part}:********@{host}"

    print(f"Connecting to database: {masked_url}")
    conn = psycopg2.connect(db_url)
    conn.autocommit = True
    with conn.cursor() as cur:
        print("Executing schema.sql...")
        cur.execute(sql)
    conn.close()
    print("Database migration completed successfully.")

if __name__ == "__main__":
    target = sys.argv[1] if len(sys.argv) > 1 else None
    migrate(target)
