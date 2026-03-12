
import sqlite3
import os

# Chemins vers les bases de données
OLD_DB_PATH = os.path.join(os.path.dirname(__file__), '..', 'data', 'godmod_v2.db')
NEW_DB_PATH = os.path.join(os.path.dirname(__file__), '..', 'data', 'godmod_v3.db')

# --- 1. Définition du Nouveau Schéma ---
def create_new_schema(conn):
    cursor = conn.cursor()
    
    # Table equipes (inchangée)
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS equipes (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        nom TEXT UNIQUE NOT NULL
    );
    """)

    # Table matches (fusion)
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS matches (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        journee INTEGER NOT NULL,
        equipe_dom_id INTEGER NOT NULL,
        equipe_ext_id INTEGER NOT NULL,
        cote_1 DECIMAL(5,2),
        cote_x DECIMAL(5,2),
        cote_2 DECIMAL(5,2),
        score_dom INTEGER,
        score_ext INTEGER,
        status TEXT CHECK(status IN ('A_VENIR', 'TERMINE')),
        FOREIGN KEY (equipe_dom_id) REFERENCES equipes(id),
        FOREIGN KEY (equipe_ext_id) REFERENCES equipes(id),
        UNIQUE(journee, equipe_dom_id, equipe_ext_id)
    );
    """)

    # Table classement (unique)
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS classement (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        journee INTEGER NOT NULL,
        equipe_id INTEGER NOT NULL,
        position INTEGER,
        points INTEGER NOT NULL,
        forme TEXT,
        buts_pour DECIMAL(4,2) DEFAULT 0,
        buts_contre DECIMAL(4,2) DEFAULT 0,
        FOREIGN KEY (equipe_id) REFERENCES equipes(id),
        UNIQUE(journee, equipe_id)
    );
    """)

    # Table predictions
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS predictions (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        match_id INTEGER NOT NULL,
        prediction TEXT NOT NULL,
        resultat TEXT, -- Ajout de la colonne manquante
        fiabilite DECIMAL(5,2),
        succes INTEGER, -- 1 (Vrai) ou 0 (Faux)
        FOREIGN KEY (match_id) REFERENCES matches(id)
    );
    """)

    # Table sessions
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS sessions (
        session_id INTEGER PRIMARY KEY AUTOINCREMENT,
        timestamp_debut TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        timestamp_fin TIMESTAMP,
        capital_initial INTEGER DEFAULT 20000,
        capital_final INTEGER,
        nombre_journees INTEGER DEFAULT 38,
        version_ia TEXT,
        profit_total INTEGER,
        type_session TEXT CHECK(type_session IN ('TRAINING', 'EVALUATION', 'PRODUCTION'))
    );
    """)

    # Table historique_paris
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS historique_paris (
        id_pari INTEGER PRIMARY KEY AUTOINCREMENT,
        session_id INTEGER NOT NULL,
        prediction_id INTEGER NOT NULL, -- Changé de match_id à prediction_id
        mise_ar INTEGER,
        pourcentage_bankroll REAL,
        cote_jouee REAL,
        resultat INTEGER,  -- 1 (Gagné), 0 (Perdu), NULL (Abstention/En attente)
        profit_net INTEGER,
        bankroll_apres INTEGER NOT NULL,
        timestamp_pari TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        action_id INTEGER,  -- L'action discrète choisie (0-12)
        FOREIGN KEY (session_id) REFERENCES sessions(session_id),
        FOREIGN KEY (prediction_id) REFERENCES predictions(id)
    );
    """)
    conn.commit()
    print("✅ Nouveau schéma créé avec succès.")


# --- 2. Logique de Migration ---
def migrate_data(old_conn, new_conn):
    old_cursor = old_conn.cursor()
    new_cursor = new_conn.cursor()

    # equipes (copie simple)
    old_cursor.execute("SELECT * FROM equipes")
    new_cursor.executemany("INSERT INTO equipes VALUES (?, ?)", old_cursor.fetchall())
    print("Migrating equipes... OK")

    # matches (fusion de cotes, resultats, matches_global)
    # On utilise matches_global comme base
    old_cursor.execute("SELECT id, journee, equipe_dom_id, equipe_ext_id, cote_1, cote_x, cote_2, score_dom, score_ext, status FROM matches_global")
    matches_data = old_cursor.fetchall()
    new_cursor.executemany("INSERT INTO matches (id, journee, equipe_dom_id, equipe_ext_id, cote_1, cote_x, cote_2, score_dom, score_ext, status) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", matches_data)
    print("Migrating matches... OK")

    # classement (copie simple, on ignore classement_global)
    old_cursor.execute("SELECT id, journee, equipe_id, position, points, forme, buts_pour, buts_contre FROM classement")
    classement_data = old_cursor.fetchall()
    new_cursor.executemany("INSERT INTO classement VALUES (?, ?, ?, ?, ?, ?, ?, ?)", classement_data)
    print("Migrating classement... OK")

    # predictions (besoin de mapper l'ancien match_id au nouveau)
    # On suppose que la combinaison (journee, dom, ext) est unique
    old_cursor.execute("SELECT p.id, mg.id as match_id, p.prediction, p.resultat, p.fiabilite, p.succes FROM predictions p JOIN matches_global mg ON p.journee = mg.journee AND p.equipe_dom_id = mg.equipe_dom_id AND p.equipe_ext_id = mg.equipe_ext_id")
    predictions_data = old_cursor.fetchall()
    new_cursor.executemany("INSERT INTO predictions (id, match_id, prediction, resultat, fiabilite, succes) VALUES (?, ?, ?, ?, ?, ?)", predictions_data)
    print("Migrating predictions... OK")

    # sessions (copie simple, sans score_zeus)
    old_cursor.execute("SELECT session_id, timestamp_debut, timestamp_fin, capital_initial, capital_final, nombre_journees, version_ia, profit_total, type_session FROM sessions")
    sessions_data = old_cursor.fetchall()
    new_cursor.executemany("INSERT INTO sessions VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)", sessions_data)
    print("Migrating sessions... OK")

    # historique_paris (le plus complexe)
    # On doit retrouver le nouvel ID de prédiction
    old_cursor.execute("""
    SELECT hp.id_pari, hp.session_id, p.id as prediction_id, hp.mise_ar, hp.pourcentage_bankroll, hp.cote_jouee, hp.resultat, hp.profit_net, hp.bankroll_apres, hp.timestamp_pari, hp.action_id
    FROM historique_paris hp
    JOIN matches_global mg ON hp.match_id = mg.id
    JOIN predictions p ON mg.journee = p.journee AND mg.equipe_dom_id = p.equipe_dom_id AND mg.equipe_ext_id = p.equipe_ext_id
    """)
    historique_data = old_cursor.fetchall()
    new_cursor.executemany("INSERT INTO historique_paris VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", historique_data)
    print("Migrating historique_paris... OK")

    new_conn.commit()
    print("✅ Migration des données terminée.")


# --- Exécution Principale ---
if __name__ == "__main__":
    # Supprimer l'ancienne DB de migration si elle existe
    if os.path.exists(NEW_DB_PATH):
        os.remove(NEW_DB_PATH)
        print(f"Ancienne base de données '{NEW_DB_PATH}' supprimée.")

    # Connexion aux bases de données
    try:
        old_db_conn = sqlite3.connect(OLD_DB_PATH)
        new_db_conn = sqlite3.connect(NEW_DB_PATH)

        print("🚀 Démarrage de la migration...")
        
        # 1. Créer le nouveau schéma
        create_new_schema(new_db_conn)
        
        # 2. Migrer les données
        migrate_data(old_db_conn, new_db_conn)

        print("\n🎉 Migration terminée avec succès !")

    except sqlite3.Error as e:
        print(f"❌ Erreur SQLite : {e}")
    finally:
        if 'old_db_conn' in locals():
            old_db_conn.close()
        if 'new_db_conn' in locals():
            new_db_conn.close()
