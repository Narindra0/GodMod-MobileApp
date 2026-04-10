"""
Importe les données JSON exportées de Neon vers une DB PostgreSQL locale
Usage: python scripts/import_json_to_db.py <chemin_vers_fichier_json>

Prérequis:
- PostgreSQL installé localement
- Base de données créée: createdb godmod_local
- Fichier JSON exporté depuis Neon
"""

import sys
import os
import json
import argparse
from pathlib import Path

# Ajouter le répertoire parent au path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from src.core.db.database import get_db_connection, initialiser_db


def load_json_data(filepath):
    """Charge les données depuis un fichier JSON"""
    print(f"📂 Chargement de {filepath}...")
    
    with open(filepath, 'r', encoding='utf-8') as f:
        data = json.load(f)
    
    print(f"✅ {len(data)} lignes chargées")
    return data


def import_equipes(cursor, data):
    """Importe les équipes"""
    print("\n⚽ Import des équipes...")
    count = 0
    
    for item in data:
        try:
            cursor.execute("""
                INSERT INTO equipes (id, nom, logo_url, ligue)
                VALUES (%s, %s, %s, %s)
                ON CONFLICT (id) DO UPDATE SET
                    nom = EXCLUDED.nom,
                    logo_url = EXCLUDED.logo_url,
                    ligue = EXCLUDED.ligue
            """, (
                item.get('id'),
                item.get('nom'),
                item.get('logo_url'),
                item.get('ligue', 'Ligue 1')
            ))
            count += 1
        except Exception as e:
            print(f"   ⚠️  Erreur équipe {item.get('id')}: {e}")
    
    print(f"✅ {count} équipes importées")


def import_sessions(cursor, data):
    """Importe les sessions"""
    print("\n📅 Import des sessions...")
    count = 0
    
    for item in data:
        try:
            cursor.execute("""
                INSERT INTO sessions (
                    id, saison, ligue, capital_initial, bankroll,
                    score_zeus, score_prisma, dette_zeus, total_emprunte_zeus,
                    stop_loss_override, current_day
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (id) DO UPDATE SET
                    saison = EXCLUDED.saison,
                    ligue = EXCLUDED.ligue,
                    capital_initial = EXCLUDED.capital_initial,
                    bankroll = EXCLUDED.bankroll,
                    score_zeus = EXCLUDED.score_zeus,
                    score_prisma = EXCLUDED.score_prisma,
                    dette_zeus = EXCLUDED.dette_zeus,
                    total_emprunte_zeus = EXCLUDED.total_emprunte_zeus,
                    stop_loss_override = EXCLUDED.stop_loss_override,
                    current_day = EXCLUDED.current_day
            """, (
                item.get('id'),
                item.get('saison', '2024-2025'),
                item.get('ligue', 'Ligue 1'),
                item.get('capital_initial', 50000),
                item.get('bankroll', 50000),
                item.get('score_zeus', 0),
                item.get('score_prisma', 200),
                item.get('dette_zeus', 0),
                item.get('total_emprunte_zeus', 0),
                item.get('stop_loss_override', False),
                item.get('current_day', item.get('journee', 1))
            ))
            count += 1
        except Exception as e:
            print(f"   ⚠️  Erreur session {item.get('id')}: {e}")
    
    print(f"✅ {count} sessions importées")


def import_matches(cursor, data):
    """Importe les matchs"""
    print("\n⚽ Import des matchs...")
    count = 0
    errors = 0
    
    for item in data:
        try:
            cursor.execute("""
                INSERT INTO matches (
                    id, session_id, journee, equipe_dom_id, equipe_ext_id,
                    cote_1, cote_x, cote_2, cote_1x, cote_12, cote_x2,
                    score_dom, score_ext, status
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (id) DO UPDATE SET
                    cote_1 = EXCLUDED.cote_1,
                    cote_x = EXCLUDED.cote_x,
                    cote_2 = EXCLUDED.cote_2,
                    score_dom = EXCLUDED.score_dom,
                    score_ext = EXCLUDED.score_ext,
                    status = EXCLUDED.status
            """, (
                item.get('id'),
                item.get('session_id'),
                item.get('journee'),
                item.get('equipe_dom_id'),
                item.get('equipe_ext_id'),
                item.get('cote_1'),
                item.get('cote_x'),
                item.get('cote_2'),
                item.get('cote_1x'),
                item.get('cote_12'),
                item.get('cote_x2'),
                item.get('score_dom'),
                item.get('score_ext'),
                item.get('status', 'A_VENIR')
            ))
            count += 1
        except Exception as e:
            errors += 1
            if errors <= 5:  # Limite l'affichage des erreurs
                print(f"   ⚠️  Erreur match {item.get('id')}: {e}")
    
    print(f"✅ {count} matchs importés ({errors} erreurs)")


def import_predictions(cursor, data):
    """Importe les prédictions"""
    print("\n🔮 Import des prédictions...")
    count = 0
    errors = 0
    
    for item in data:
        try:
            cursor.execute("""
                INSERT INTO predictions (
                    id, session_id, match_id, prediction, resultat,
                    fiabilite, succes, source, technical_details,
                    ai_analysis, ai_advice
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (id) DO UPDATE SET
                    prediction = EXCLUDED.prediction,
                    resultat = EXCLUDED.resultat,
                    fiabilite = EXCLUDED.fiabilite,
                    succes = EXCLUDED.succes,
                    technical_details = EXCLUDED.technical_details
            """, (
                item.get('id'),
                item.get('session_id'),
                item.get('match_id'),
                item.get('prediction'),
                item.get('resultat'),
                item.get('fiabilite'),
                item.get('succes'),
                item.get('source', 'PRISMA'),
                json.dumps(item.get('technical_details')) if item.get('technical_details') else None,
                item.get('ai_analysis'),
                item.get('ai_advice')
            ))
            count += 1
        except Exception as e:
            errors += 1
            if errors <= 5:
                print(f"   ⚠️  Erreur prediction {item.get('id')}: {e}")
    
    print(f"✅ {count} prédictions importées ({errors} erreurs)")


def import_classement(cursor, data):
    """Importe le classement"""
    print("\n📊 Import du classement...")
    count = 0
    
    for item in data:
        try:
            cursor.execute("""
                INSERT INTO classement (
                    id, session_id, journee, equipe_id, position,
                    points, forme, buts_pour, buts_contre
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (id) DO UPDATE SET
                    position = EXCLUDED.position,
                    points = EXCLUDED.points,
                    forme = EXCLUDED.forme,
                    buts_pour = EXCLUDED.buts_pour,
                    buts_contre = EXCLUDED.buts_contre
            """, (
                item.get('id'),
                item.get('session_id'),
                item.get('journee'),
                item.get('equipe_id'),
                item.get('position'),
                item.get('points'),
                item.get('forme'),
                item.get('buts_pour', 0),
                item.get('buts_contre', 0)
            ))
            count += 1
        except Exception as e:
            if count < 5:
                print(f"   ⚠️  Erreur classement {item.get('id')}: {e}")
    
    print(f"✅ {count} entrées classement importées")


def import_historique_paris(cursor, data):
    """Importe l'historique des paris"""
    print("\n💰 Import de l'historique des paris...")
    count = 0
    errors = 0
    
    for item in data:
        try:
            cursor.execute("""
                INSERT INTO historique_paris (
                    id_pari, session_id, prediction_id, journee, type_pari,
                    mise_ar, pourcentage_bankroll, cote_jouee, resultat,
                    profit_net, bankroll_apres, strategie, timestamp_pari
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (id_pari) DO UPDATE SET
                    resultat = EXCLUDED.resultat,
                    profit_net = EXCLUDED.profit_net,
                    bankroll_apres = EXCLUDED.bankroll_apres
            """, (
                item.get('id_pari'),
                item.get('session_id'),
                item.get('prediction_id'),
                item.get('journee'),
                item.get('type_pari'),
                item.get('mise_ar'),
                item.get('pourcentage_bankroll'),
                item.get('cote_jouee'),
                item.get('resultat'),
                item.get('profit_net'),
                item.get('bankroll_apres'),
                item.get('strategie', 'ZEUS'),
                item.get('timestamp_pari')
            ))
            count += 1
        except Exception as e:
            errors += 1
            if errors <= 5:
                print(f"   ⚠️  Erreur pari {item.get('id_pari')}: {e}")
    
    print(f"✅ {count} paris importés ({errors} erreurs)")


def import_prisma_config(cursor, data):
    """Importe la configuration PRISMA"""
    print("\n⚙️  Import de la configuration...")
    count = 0
    
    for item in data:
        try:
            cursor.execute("""
                INSERT INTO prisma_config (key, value_int, value_float, value_text)
                VALUES (%s, %s, %s, %s)
                ON CONFLICT (key) DO UPDATE SET
                    value_int = EXCLUDED.value_int,
                    value_float = EXCLUDED.value_float,
                    value_text = EXCLUDED.value_text,
                    last_update = CURRENT_TIMESTAMP
            """, (
                item.get('key'),
                item.get('value_int'),
                item.get('value_float'),
                item.get('value_text')
            ))
            count += 1
        except Exception as e:
            print(f"   ⚠️  Erreur config {item.get('key')}: {e}")
    
    print(f"✅ {count} configs importées")


def detect_table(data):
    """Détecte la table à partir des clés du premier élément"""
    if not data:
        return None
    
    sample = data[0]
    keys = set(sample.keys())
    
    if 'nom' in keys and 'logo_url' in keys:
        return 'equipes'
    elif 'saison' in keys or 'capital_initial' in keys:
        return 'sessions'
    elif 'cote_1' in keys and 'equipe_dom_id' in keys:
        return 'matches'
    elif 'prediction' in keys and 'fiabilite' in keys:
        return 'predictions'
    elif 'points' in keys and 'position' in keys:
        return 'classement'
    elif 'mise_ar' in keys and 'bankroll_apres' in keys:
        return 'historique_paris'
    elif 'key' in keys and 'value_int' in keys:
        return 'prisma_config'
    else:
        return None


def import_data(filepath, table_name=None):
    """Importe les données depuis un fichier JSON"""
    
    print(f"{'='*60}")
    print(f"📥 IMPORT JSON → PostgreSQL")
    print(f"{'='*60}")
    print(f"Fichier: {filepath}")
    
    # Charger les données
    data = load_json_data(filepath)
    
    if not data:
        print("❌ Aucune donnée à importer")
        return False
    
    # Détecter la table si non spécifiée
    if not table_name:
        table_name = detect_table(data)
        if table_name:
            print(f"🔍 Table détectée: {table_name}")
        else:
            print("❌ Impossible de détecter la table")
            print(f"   Clés trouvées: {list(data[0].keys())[:5]}")
            return False
    
    # Importer
    try:
        with get_db_connection(write=True) as conn:
            cursor = conn.cursor()
            
            # Dispatcher vers la bonne fonction
            importers = {
                'equipes': import_equipes,
                'sessions': import_sessions,
                'matches': import_matches,
                'predictions': import_predictions,
                'classement': import_classement,
                'historique_paris': import_historique_paris,
                'prisma_config': import_prisma_config,
            }
            
            if table_name in importers:
                importers[table_name](cursor, data)
            else:
                print(f"⚠️  Importeur non implémenté pour: {table_name}")
                return False
            
            conn.commit()
            print(f"\n✅ Import terminé avec succès!")
            return True
            
    except Exception as e:
        print(f"\n❌ Erreur lors de l'import: {e}")
        import traceback
        traceback.print_exc()
        return False


def main():
    parser = argparse.ArgumentParser(description='Importe les données JSON vers PostgreSQL')
    parser.add_argument('file', help='Chemin vers le fichier JSON')
    parser.add_argument('--table', '-t', help='Nom de la table (auto-détecté si non spécifié)')
    parser.add_argument('--init-db', action='store_true', help='Initialise la structure de la DB avant import')
    
    args = parser.parse_args()
    
    # Vérifier que le fichier existe
    if not os.path.exists(args.file):
        print(f"❌ Fichier introuvable: {args.file}")
        return 1
    
    # Initialiser la DB si demandé
    if args.init_db:
        print("🏗️  Initialisation de la base de données...")
        initialiser_db()
        print("✅ Structure créée\n")
    
    # Importer
    success = import_data(args.file, args.table)
    
    return 0 if success else 1


if __name__ == '__main__':
    sys.exit(main())
