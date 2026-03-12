-- Audit du schéma de la base de données - 20260311_121721

-- Structure de la table : equipes
CREATE TABLE equipes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            nom TEXT UNIQUE NOT NULL
        );

-- Structure de la table : resultats
CREATE TABLE resultats (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            journee INTEGER NOT NULL,
            equipe_dom_id INTEGER NOT NULL,
            equipe_ext_id INTEGER NOT NULL,
            score_dom INTEGER,  -- Peut être NULL avant le match
            score_ext INTEGER,  -- Peut être NULL avant le match
            FOREIGN KEY (equipe_dom_id) REFERENCES equipes(id),
            FOREIGN KEY (equipe_ext_id) REFERENCES equipes(id),
            UNIQUE(journee, equipe_dom_id, equipe_ext_id)
        );

-- Structure de la table : cotes
CREATE TABLE cotes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            journee INTEGER NOT NULL,
            equipe_dom_id INTEGER NOT NULL,
            equipe_ext_id INTEGER NOT NULL,
            cote_1 DECIMAL(5,2),
            cote_x DECIMAL(5,2),
            cote_2 DECIMAL(5,2),
            FOREIGN KEY (equipe_dom_id) REFERENCES equipes(id),
            FOREIGN KEY (equipe_ext_id) REFERENCES equipes(id),
            UNIQUE(journee, equipe_dom_id, equipe_ext_id)
        );

-- Structure de la table : classement
CREATE TABLE classement (
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

-- Structure de la table : predictions
CREATE TABLE predictions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            journee INTEGER NOT NULL,
            equipe_dom_id INTEGER NOT NULL,
            equipe_ext_id INTEGER NOT NULL,
            prediction TEXT NOT NULL,
            resultat TEXT,
            fiabilite DECIMAL(5,2),
            succes INTEGER, -- 1 (Vrai) ou 0 (Faux), NULL si pas encore joué
            points_gagnes INTEGER,
            FOREIGN KEY (equipe_dom_id) REFERENCES equipes(id),
            FOREIGN KEY (equipe_ext_id) REFERENCES equipes(id)
        );

-- Structure de la table : score_ia
CREATE TABLE score_ia (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            score DECIMAL(10,2) DEFAULT 100.00,
            predictions_total INTEGER DEFAULT 0,
            predictions_reussies INTEGER DEFAULT 0,
            pause_until INTEGER DEFAULT 0,
            session_archived INTEGER DEFAULT 0,
            derniere_maj TEXT
        );

-- Structure de la table : classement_global
CREATE TABLE classement_global (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            journee INTEGER NOT NULL,
            position INTEGER,
            equipe_id INTEGER NOT NULL,
            points INTEGER NOT NULL,
            forme TEXT,
            FOREIGN KEY (equipe_id) REFERENCES equipes(id)
        );

-- Structure de la table : matches_global
CREATE TABLE matches_global (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            journee INTEGER NOT NULL,
            equipe_dom_id INTEGER NOT NULL,
            equipe_ext_id INTEGER NOT NULL,
            cote_1 DECIMAL(5,2),
            cote_x DECIMAL(5,2),
            cote_2 DECIMAL(5,2),
            status TEXT, -- 'A_VENIR', 'TERMINE'
            score_dom INTEGER,
            score_ext INTEGER,
            FOREIGN KEY (equipe_dom_id) REFERENCES equipes(id),
            FOREIGN KEY (equipe_ext_id) REFERENCES equipes(id)
        );

-- Structure de la table : sessions
CREATE TABLE sessions (
            session_id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp_debut TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            timestamp_fin TIMESTAMP,
            capital_initial INTEGER DEFAULT 20000,
            capital_final INTEGER,
            nombre_journees INTEGER DEFAULT 38,
            version_ia TEXT,
            profit_total INTEGER,
            type_session TEXT CHECK(type_session IN ('TRAINING', 'EVALUATION', 'PRODUCTION')),
            score_zeus INTEGER DEFAULT 0
        );

-- Structure de la table : historique_paris
CREATE TABLE historique_paris (
            id_pari INTEGER PRIMARY KEY AUTOINCREMENT,
            session_id INTEGER NOT NULL,
            match_id INTEGER NOT NULL,
            journee INTEGER NOT NULL,
            type_pari TEXT CHECK(type_pari IN ('1', 'N', '2', 'Aucun')),
            mise_ar INTEGER,
            pourcentage_bankroll REAL,
            cote_jouee REAL,
            resultat INTEGER,  -- 1 (Gagné), 0 (Perdu), NULL (Abstention/En attente)
            profit_net INTEGER,
            bankroll_apres INTEGER NOT NULL,
            timestamp_pari TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            probabilite_implicite REAL,
            action_id INTEGER,  -- L'action discrète choisie (0-12)
            FOREIGN KEY (session_id) REFERENCES sessions(session_id),
            FOREIGN KEY (match_id) REFERENCES matches_global(id)
        );

