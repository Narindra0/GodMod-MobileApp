
import sqlite3
import datetime
import os

def get_db_schem_info(db_path):
    """
    Extrait les métadonnées complètes d'une base de données SQLite.
    """
    if not os.path.exists(db_path):
        raise FileNotFoundError(f"La base de données n'a pas été trouvée à l'emplacement : {db_path}")

    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    # Récupérer la liste des tables
    cursor.execute("SELECT name FROM sqlite_master WHERE type='table';")
    tables = [table[0] for table in cursor.fetchall()]

    schem_info = {}

    for table_name in tables:
        if table_name.startswith('sqlite_'):
            continue

        schem_info[table_name] = {
            'name': table_name,
            'columns': [],
            'constraints': [],
            'indexes': [],
            'sql': "",
            'row_count': 0
        }

        # Obtenir le SQL de création de la table
        cursor.execute(f"SELECT sql FROM sqlite_master WHERE type='table' AND name='{table_name}';")
        sql_create = cursor.fetchone()
        if sql_create:
            schem_info[table_name]['sql'] = sql_create[0]

        # Obtenir les informations sur les colonnes
        cursor.execute(f"PRAGMA table_info('{table_name}');")
        columns_info = cursor.fetchall()
        for col in columns_info:
            col_info = {
                'name': col[1],
                'type': col[2],
                'not_null': bool(col[3]),
                'default_value': col[4],
                'is_pk': bool(col[5])
            }
            schem_info[table_name]['columns'].append(col_info)

        # Obtenir les contraintes de clé étrangère
        cursor.execute(f"PRAGMA foreign_key_list('{table_name}');")
        foreign_keys = cursor.fetchall()
        for fk in foreign_keys:
            schem_info[table_name]['constraints'].append(
                f"FOREIGN KEY ({fk[3]}) REFERENCES {fk[2]}({fk[4]}) ON DELETE {fk[6]} ON UPDATE {fk[5]}"
            )

        # Obtenir les index
        cursor.execute(f"PRAGMA index_list('{table_name}');")
        indexes_info = cursor.fetchall()
        for index in indexes_info:
            index_name = index[1]
            cursor.execute(f"PRAGMA index_info('{index_name}');")
            index_cols = [info[2] for info in cursor.fetchall()]
            schem_info[table_name]['indexes'].append({
                'name': index_name,
                'unique': bool(index[2]),
                'columns': index_cols
            })

        # Compter les enregistrements
        cursor.execute(f"SELECT COUNT(*) FROM {table_name};")
        row_count = cursor.fetchone()
        if row_count:
            schem_info[table_name]['row_count'] = row_count[0]

    conn.close()
    return schem_info

def generate_sql_file(schem_info, output_path):
    """
    Génère un fichier .sql contenant les instructions SHOW CREATE TABLE.
    """
    timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = os.path.join(output_path, f"schema_audit_{timestamp}.sql")
    
    with open(filename, 'w', encoding='utf-8') as f:
        f.write(f"-- Audit du schéma de la base de données - {timestamp}\n\n")
        for table_name, info in schem_info.items():
            f.write(f"-- Structure de la table : {table_name}\n")
            f.write(f"{info['sql']};\n\n")
    return filename

def generate_markdown_summary(schem_info, output_path):
    """
    Génère un tableau récapitulatif au format Markdown.
    """
    timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = os.path.join(output_path, f"schema_summary_{timestamp}.md")

    with open(filename, 'w', encoding='utf-8') as f:
        f.write(f"# Résumé du Schéma de la Base de Données - {timestamp}\n\n")
        
        for table_name, info in schem_info.items():
            f.write(f"## Table: `{table_name}`\n\n")
            f.write(f"- **Nombre d'enregistrements :** {info['row_count']}\n")
            f.write(f"- **Moteur de stockage :** SQLite (N/A)\n")
            f.write(f"- **Charset/Collation :** SQLite (UTF-8 par défaut)\n\n")
            
            f.write("### Colonnes\n")
            f.write("| Nom | Type | Contraintes | Clé Primaire |\n")
            f.write("|---|---|---|---|\n")
            for col in info['columns']:
                constraints = []
                if col['not_null']:
                    constraints.append("NOT NULL")
                if col['default_value'] is not None:
                    constraints.append(f"DEFAULT {col['default_value']}")
                
                f.write(f"| {col['name']} | {col['type']} | {', '.join(constraints)} | {'Oui' if col['is_pk'] else 'Non'} |\n")
            f.write("\n")

            if info['constraints']:
                f.write("### Contraintes de Clé Étrangère\n")
                for const in info['constraints']:
                    f.write(f"- `{const}`\n")
                f.write("\n")

            if info['indexes']:
                f.write("### Index\n")
                f.write("| Nom | Unique | Colonnes |\n")
                f.write("|---|---|---|\n")
                for index in info['indexes']:
                    f.write(f"| {index['name']} | {'Oui' if index['unique'] else 'Non'} | { ', '.join(index['columns'])} |\n")
                f.write("\n")
    return filename

def generate_mermaid_diagram(schem_info, output_path):
    """
    Génère un diagramme Entité-Relation au format Mermaid.
    """
    timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = os.path.join(output_path, f"er_diagram_{timestamp}.md")

    with open(filename, 'w', encoding='utf-8') as f:
        f.write(f"# Diagramme Entité-Relation - {timestamp}\n\n")
        f.write("```mermaid\n")
        f.write("erDiagram\n")
        
        # Définition des tables et colonnes
        for table_name, info in schem_info.items():
            f.write(f"    {table_name} {{\n")
            for col in info['columns']:
                pk = " PK" if col['is_pk'] else ""
                f.write(f"        {col['type']} {col['name']}{pk}\n")
            f.write("    }\n")

        # Définition des relations
        for table_name, info in schem_info.items():
            cursor = sqlite3.connect(DB_PATH).cursor()
            cursor.execute(f"PRAGMA foreign_key_list('{table_name}');")
            foreign_keys = cursor.fetchall()
            for fk in foreign_keys:
                from_table = table_name
                to_table = fk[2]
                from_col = fk[3]
                to_col = fk[4]
                
                # Déterminer la cardinalité (simplification)
                # Si la clé étrangère est aussi une clé primaire, c'est une relation 1..1
                # Sinon, on suppose une relation 1..N
                is_pk = any(col['name'] == from_col and col['is_pk'] for col in info['columns'])
                
                if is_pk:
                    rel = "|o--||" # one-to-one
                else:
                    rel = "|o--o{" # one-to-many

                f.write(f"    {from_table} {rel} {to_table} : \"{from_col} -> {to_col}\"\n")

        f.write("```\n")
    return filename


if __name__ == "__main__":
    DB_PATH = os.path.join(os.path.dirname(__file__), '..', 'data', 'godmod_v2.db')
    OUTPUT_DIR = os.path.join(os.path.dirname(__file__), '..', 'audits')

    if not os.path.exists(OUTPUT_DIR):
        os.makedirs(OUTPUT_DIR)

    print("🔍 Démarrage de l'audit de la base de données...")
    
    try:
        schema_data = get_db_schem_info(DB_PATH)
        print(f"✅ {len(schema_data)} tables trouvées et analysées.")

        # Génération des livrables
        sql_file = generate_sql_file(schema_data, OUTPUT_DIR)
        print(f"📄 Fichier SQL généré : {sql_file}")

        md_summary = generate_markdown_summary(schema_data, OUTPUT_DIR)
        print(f"📋 Résumé Markdown généré : {md_summary}")

        mermaid_file = generate_mermaid_diagram(schema_data, OUTPUT_DIR)
        print(f"📈 Diagramme Mermaid généré : {mermaid_file}")

        print("\n🎉 Audit terminé avec succès !")

    except Exception as e:
        print(f"❌ Une erreur est survenue : {e}")

