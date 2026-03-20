import datetime
import os

import psycopg2
from src.core.database import PG_DATABASE, PG_HOST, get_db_connection


def get_db_schem_info():
    with get_db_connection() as conn:
        cursor = conn.cursor()

        # Lister toutes les tables du schéma public
        cursor.execute(
            """
            SELECT table_name
            FROM information_schema.tables
            WHERE table_schema = 'public' AND table_type = 'BASE TABLE'
        """
        )
        tables = [table["table_name"] for table in cursor.fetchall()]

        schem_info = {}
        for table_name in tables:
            schem_info[table_name] = {
                "name": table_name,
                "columns": [],
                "constraints": [],
                "indexes": [],
                "sql": f"CREATE TABLE {table_name} ( ... )",  # Simplifié car PG n'a pas sqlite_master.sql
                "row_count": 0,
            }

            # Colonnes
            cursor.execute(
                """
                SELECT column_name, data_type, is_nullable, column_default
                FROM information_schema.columns
                WHERE table_name = %s
                ORDER BY ordinal_position
            """,
                (table_name,),
            )
            columns_info = cursor.fetchall()
            for col in columns_info:
                col_info = {
                    "name": col["column_name"],
                    "type": col["data_type"],
                    "not_null": col["is_nullable"] == "NO",
                    "default_value": col["column_default"],
                    "is_pk": False,  # Sera mis à jour après
                }
                schem_info[table_name]["columns"].append(col_info)

            # Identifier la PK (simplifié)
            cursor.execute(
                """
                SELECT kcu.column_name
                FROM information_schema.table_constraints tc
                JOIN information_schema.key_column_usage kcu
                  ON tc.constraint_name = kcu.constraint_name
                WHERE tc.table_name = %s AND tc.constraint_type = 'PRIMARY KEY'
            """,
                (table_name,),
            )
            pk_result = cursor.fetchone()
            if pk_result:
                pk_col = pk_result["column_name"]
                for col in schem_info[table_name]["columns"]:
                    if col["name"] == pk_col:
                        col["is_pk"] = True

            # Foreign Keys
            cursor.execute(
                """
                SELECT
                    kcu.column_name,
                    ccu.table_name AS foreign_table_name,
                    ccu.column_name AS foreign_column_name
                FROM
                    information_schema.table_constraints AS tc
                    JOIN information_schema.key_column_usage AS kcu
                      ON tc.constraint_name = kcu.constraint_name
                    JOIN information_schema.constraint_column_usage AS ccu
                      ON ccu.constraint_name = tc.constraint_name
                WHERE tc.constraint_type = 'FOREIGN KEY' AND tc.table_name=%s
            """,
                (table_name,),
            )
            fks = cursor.fetchall()
            for fk in fks:
                schem_info[table_name]["constraints"].append(
                    f"FOREIGN KEY ({fk['column_name']}) REFERENCES "
                    f"{fk['foreign_table_name']}({fk['foreign_column_name']})"
                )

            # Row count
            cursor.execute("SELECT COUNT(*) FROM %s", (table_name,))
            row_count = cursor.fetchone()
            schem_info[table_name]["row_count"] = row_count["count"]

    return schem_info


def generate_sql_file(schem_info, output_path):
    timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = os.path.join(output_path, f"schema_audit_pg_{timestamp}.sql")
    with open(filename, "w", encoding="utf-8") as f:
        f.write("-- Audit du schéma PostgreSQL\n")
        f.write(f"-- Base de données: {PG_DATABASE} @ {PG_HOST}\n")
        f.write(f"-- Timestamp: {timestamp}\n\n")
        for table_name, info in schem_info.items():
            f.write(f"-- Table : {table_name} ({info['row_count']} lignes)\n")
            # Note: Le dump SQL complet nécessiterait pg_dump
            f.write(f"-- [Structure détaillée dans le résumé markdown]\n\n")
    return filename


def generate_markdown_summary(schem_info, output_path):
    timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = os.path.join(output_path, f"schema_summary_pg_{timestamp}.md")
    with open(filename, "w", encoding="utf-8") as f:
        f.write(f"# Résumé du Schéma PostgreSQL - {timestamp}\n\n")
        f.write(f"**Base de données :** `{PG_DATABASE}`\n\n")
        for table_name, info in schem_info.items():
            f.write(f"## Table: `{table_name}`\n\n")
            f.write(f"- **Nombre d'enregistrements :** {info['row_count']}\n\n")
            f.write("### Colonnes\n")
            f.write("| Nom | Type | NOT NULL | Défaut | PK |\n")
            f.write("|---|---|---|---|---|\n")
            for col in info["columns"]:
                f.write(
                    f"| {col['name']} | {col['type']} | "
                    f"{'Oui' if col['not_null'] else 'Non'} | `{col['default_value']}` | "
                    f"{'Oui' if col['is_pk'] else 'Non'} |\n"
                )
            f.write("\n")
            if info["constraints"]:
                f.write("### Contraintes\n")
                for const in info["constraints"]:
                    f.write(f"- `{const}`\n")
                f.write("\n")
    return filename


def generate_mermaid_diagram(schem_info, output_path):
    timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = os.path.join(output_path, f"er_diagram_pg_{timestamp}.md")
    with open(filename, "w", encoding="utf-8") as f:
        f.write(f"# Diagramme ER PostgreSQL - {timestamp}\n\n")
        f.write("```mermaid\n")
        f.write("erDiagram\n")
        for table_name, info in schem_info.items():
            f.write(f"    {table_name} {{\n")
            for col in info["columns"]:
                pk = " PK" if col["is_pk"] else ""
                # Nettoyer les types pour Mermaid
                m_type = col["type"].replace(" ", "_").replace('"', "")
                f.write(f"        {m_type} {col['name']}{pk}\n")
            f.write("    }\n")

        # Relations simplifiées basées sur les contraintes collectées
        for table_name, info in schem_info.items():
            for const in info["constraints"]:
                if "REFERENCES" in const:
                    # Parse simplified FK string: FOREIGN KEY (col) REFERENCES table(target_col)
                    try:
                        parts = const.split(" REFERENCES ")
                        target = parts[1].split("(")[0]
                        f.write(f'    {table_name} ||--o{{ {target} : "FK"\n')
                    except IndexError:
                        pass
        f.write("```\n")
    return filename


if __name__ == "__main__":
    OUTPUT_DIR = os.path.join(os.path.dirname(__file__), "..", "audits")
    if not os.path.exists(OUTPUT_DIR):
        os.makedirs(OUTPUT_DIR)

    print(f"🔍 Démarrage de l'audit PostgreSQL ({PG_DATABASE})...")
    try:
        schema_data = get_db_schem_info()
        print(f"✅ {len(schema_data)} tables analysées.")

        sql_file = generate_sql_file(schema_data, OUTPUT_DIR)
        print(f"📄 Fichier SQL généré : {sql_file}")

        md_summary = generate_markdown_summary(schema_data, OUTPUT_DIR)
        print(f"📋 Résumé Markdown généré : {md_summary}")

        mermaid_file = generate_mermaid_diagram(schema_data, OUTPUT_DIR)
        print(f"📈 Diagramme Mermaid généré : {mermaid_file}")

        print("\n🎉 Audit terminé avec succès !")
    except Exception as e:
        print(f"❌ Erreur lors de l'audit : {e}")
        import traceback

        traceback.print_exc()
