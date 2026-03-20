import os
import sqlite3

try:
    # Exécution attendue depuis le dossier Backend/
    from src.core import config

    _default_db_path = config.DB_NAME
except Exception:
    # Fallback minimal si le module n'est pas importable
    _default_db_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "data", "godmod_database.db"))

db_path = os.getenv("DB_PATH", _default_db_path)

if not os.path.exists(db_path):
    print(f"Error: Database not found at {db_path}")
    exit(1)

conn = sqlite3.connect(db_path)
cursor = conn.cursor()

cursor.execute("SELECT name FROM sqlite_master WHERE type='table'")
tables = [t[0] for t in cursor.fetchall()]

for table in tables:
    print(f"\n--- Table: {table} ---")
    cursor.execute(f"PRAGMA table_info({table})")
    columns = cursor.fetchall()
    for c in columns:
        print(f"Col {c[0]}: {c[1]} ({c[2]}) | NotNull: {c[3]} | Default: {c[4]} | PK: {c[5]}")

conn.close()
