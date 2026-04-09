import psycopg2
import sys

# Test 1: Full URL provided by user
# Test 2: Standard URL (no pooler, just sslmode=require)
# Test 3: Minimal params (no pooler, no channel_binding)

URLS = [
    "postgresql://neondb_owner:npg_XFIOS9Yrn3TQ@ep-raspy-credit-amt5t8yu-pooler.c-5.us-east-1.aws.neon.tech/neondb?sslmode=require&channel_binding=require",
    "postgresql://neondb_owner:npg_XFIOS9Yrn3TQ@ep-raspy-credit-amt5t8yu.us-east-1.aws.neon.tech/neondb?sslmode=require"
]

for i, url in enumerate(URLS):
    print(f"Test #{i+1}: {url}")
    try:
        conn = psycopg2.connect(url, connect_timeout=10)
        print(f"✅ Succès pour Test #{i+1}")
        conn.close()
        break
    except Exception as e:
        print(f"❌ Échec pour Test #{i+1}: {e}")

print("Fin des tests.")
