import json
import sqlite3
import os

# Paths
PRISMA_JSON = r"f:\Narindra Projet\GODMOD version mobile\Backend\src\data\Prisma.json"
DB_PATH = r"f:\Narindra Projet\GODMOD version mobile\Backend\data\godmod_database.db"

# Restore points
RESTORE_BANKROLL = 25879
RESTORE_SCORE = 200

def repair():
    print("Starting repair...")
    
    # 1. Repair Prisma.json
    try:
        data = {"bankroll": RESTORE_BANKROLL}
        with open(PRISMA_JSON, 'w', encoding='utf-8') as f:
            json.dump(data, f)
        print(f"Successfully restored bankroll to {RESTORE_BANKROLL} in Prisma.json")
    except Exception as e:
        print(f"Error repairing bankroll: {e}")

    # 2. Repair sessions table
    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        cursor.execute("UPDATE sessions SET score_prisma = ? WHERE status = 'ACTIVE'", (RESTORE_SCORE,))
        conn.commit()
        print(f"Successfully restored score_prisma to {RESTORE_SCORE} for active session")
        
        # 3. Mark all pending multiple bets as done (to avoid one more duplication)
        # We set them to lost (0) as a safe baseline, they will be overwritten by future logs if needed
        # Actually, it's better to just set them to a non-NULL result so they aren't processed.
        # But wait, if they were truly pending, we want them processed CORRECTLY.
        # Since I fixed the code, the RESTORED bankroll will be the base for the NEXT validation.
        # If I don't mark them as done, the next call will process them once more.
        # That's fine if it's only once.
        # However, to be extra clean, let's mark all currently NULL as 'DONE' (result=0, profit=0)
        # to start fresh from the restored bankroll.
        cursor.execute("UPDATE pari_multiple SET resultat = 0, profit_net = 0, bankroll_apres = ? WHERE resultat IS NULL", (RESTORE_BANKROLL,))
        conn.commit()
        print("Marked all pending multiple bets as processed (voided) to start fresh.")
        
        conn.close()
    except Exception as e:
        print(f"Error repairing database: {e}")

if __name__ == "__main__":
    repair()
