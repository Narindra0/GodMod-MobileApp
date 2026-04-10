import json
import os
import sqlite3
from pathlib import Path

try:
    # Exécution attendue depuis le dossier Backend/
    from src.core.system import config

    DB_PATH = config.DB_NAME
except Exception:
    # Fallback si import impossible
    DB_PATH = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "data", "godmod_database.db"))

# Prisma.json est géré dans Backend/data/Prisma.json (même endroit que le runtime)
PRISMA_JSON = str((Path(__file__).resolve().parent.parent / "data" / "Prisma.json"))
RESTORE_BANKROLL = 25879
RESTORE_SCORE = 200


def repair():
    print("Starting repair...")
    try:
        data = {"bankroll": RESTORE_BANKROLL}
        with open(PRISMA_JSON, "w", encoding="utf-8") as f:
            json.dump(data, f)
        print(f"Successfully restored bankroll to {RESTORE_BANKROLL} in Prisma.json")
    except Exception as e:
        print(f"Error repairing bankroll: {e}")
    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        cursor.execute("UPDATE sessions SET score_prisma = ? WHERE status = 'ACTIVE'", (RESTORE_SCORE,))
        conn.commit()
        print(f"Successfully restored score_prisma to {RESTORE_SCORE} for active session")
        cursor.execute(
            "UPDATE pari_multiple SET resultat = 0, profit_net = 0, bankroll_apres = ? WHERE resultat IS NULL",
            (RESTORE_BANKROLL,),
        )
        conn.commit()
        print("Marked all pending multiple bets as processed (voided) to start fresh.")
        conn.close()
    except Exception as e:
        print(f"Error repairing database: {e}")


if __name__ == "__main__":
    repair()
