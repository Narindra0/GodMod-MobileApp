import psycopg2
import sys

URL = "postgresql://neondb_owner:npg_XFIOS9Yrn3TQ@ep-raspy-credit-amt5t8yu-pooler.c-5.us-east-1.aws.neon.tech/neondb?sslmode=require"

try:
    print(f"Tentative de connexion à Neon...")
    conn = psycopg2.connect(URL)
    print("✅ Connexion réussie !")
    conn.close()
except Exception as e:
    print(f"❌ Échec: {e}")
    sys.exit(1)
