from dataclasses import dataclass
from typing import Any, Dict, List, Optional
import logging

from src.core.session_manager import get_active_session

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class PariRecord:
    session_id: int
    prediction_id: int
    journee: int
    type_pari: str
    mise_ar: int
    pourcentage_bankroll: float
    cote_jouee: Optional[float]
    resultat: Optional[int]
    profit_net: Optional[int]
    bankroll_apres: int
    probabilite_implicite: Optional[float]
    action_id: int
    strategie: str = "ZEUS"


def _map_match_row(row) -> Dict:
    return {
        "id": row["id"],
        "journee": row["journee"],
        "equipe_dom_id": row["equipe_dom_id"],
        "equipe_ext_id": row["equipe_ext_id"],
        "equipe_dom_nom": row["equipe_dom_nom"],
        "equipe_ext_nom": row["equipe_ext_nom"],
        "cote_1": row["cote_1"],
        "cote_x": row["cote_x"],
        "cote_2": row["cote_2"],
        "score_dom": row["score_dom"],
        "score_ext": row["score_ext"],
        "status": row["status"],
    }


def get_matches_for_journee(journee: int, conn: Any, session_id: Optional[int] = None) -> List[Dict]:
    """
    Récupère les matches d'une journée pour une session donnée.
    Si session_id est None, on utilise la session ACTIVE (comportement historique).
    """
    if session_id is None:
        active_session = get_active_session()
        session_id = active_session["id"]
    query = """
        SELECT
            mg.id,
            mg.journee,
            mg.equipe_dom_id,
            mg.equipe_ext_id,
            e_dom.nom as equipe_dom_nom,
            e_ext.nom as equipe_ext_nom,
            mg.cote_1,
            mg.cote_x,
            mg.cote_2,
            mg.score_dom,
            mg.score_ext,
            mg.status
        FROM matches mg
        JOIN equipes e_dom ON mg.equipe_dom_id = e_dom.id
        JOIN equipes e_ext ON mg.equipe_ext_id = e_ext.id
        WHERE mg.journee = %s AND mg.session_id = %s
        ORDER BY mg.id
    """
    cursor = conn.cursor()
    cursor.execute(query, (journee, session_id))
    rows = cursor.fetchall()
    return [_map_match_row(row) for row in rows]


def create_session(capital_initial: int, type_session: str, version_ia: str, conn: Any) -> int:
    cursor = conn.cursor()
    cursor.execute("SELECT score_prisma FROM sessions WHERE status = 'ACTIVE' LIMIT 1")
    row = cursor.fetchone()
    prisma_to_use = row["score_prisma"] if row else 200
    cursor.execute(
        """
        INSERT INTO sessions (
            capital_initial,
            type_session,
            version_ia,
            score_zeus,
            score_prisma,
            status
        ) VALUES (%s, %s, %s, 0, %s, 'ACTIVE')
        RETURNING id
    """,
        (capital_initial, type_session, version_ia, prisma_to_use),
    )
    return cursor.fetchone()["id"]


def set_stop_loss_override(session_id: int, override: bool, conn: Any):
    cursor = conn.cursor()
    cursor.execute("UPDATE sessions SET stop_loss_override = %s WHERE id = %s", (override, session_id))
    # Ne pas committer ici : le context manager get_db_connection() s'en charge


def enregistrer_pari(record: PariRecord, conn: Any) -> int:
    cursor = conn.cursor()
    cursor.execute(
        """
        INSERT INTO historique_paris (
            session_id,
            prediction_id,
            journee,
            type_pari,
            mise_ar,
            pourcentage_bankroll,
            cote_jouee,
            resultat,
            profit_net,
            bankroll_apres,
            probabilite_implicite,
            action_id,
            strategie
        ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        RETURNING id_pari
    """,
        (
            record.session_id,
            record.prediction_id,
            record.journee,
            record.type_pari,
            record.mise_ar,
            record.pourcentage_bankroll,
            record.cote_jouee,
            record.resultat,
            record.profit_net,
            record.bankroll_apres,
            record.probabilite_implicite,
            record.action_id,
            record.strategie,
        ),
    )
    return cursor.fetchone()["id_pari"]


def finaliser_session(session_id: int, capital_final: int, profit_total: int, score_zeus: int, conn: Any):
    cursor = conn.cursor()
    cursor.execute(
        """
        UPDATE sessions
        SET timestamp_fin = CURRENT_TIMESTAMP,
            capital_final = %s,
            profit_total = %s,
            score_zeus = %s,
            status = 'CLOSED'
        WHERE id = %s
    """,
        (capital_final, profit_total, score_zeus, session_id),
    )
    conn.commit()


def get_available_seasons(conn: Any) -> List[int]:
    cursor = conn.cursor()
    cursor.execute(
        """
        SELECT DISTINCT journee
        FROM matches
        WHERE status = 'TERMINE'
        ORDER BY journee
    """
    )
    all_journees = [row["journee"] for row in cursor.fetchall()]
    seasons = []
    if all_journees:
        for j in all_journees:
            if (j - 1) % 38 == 0:
                seasons.append(j)
    return seasons


def get_last_training_metadata(conn: Any) -> Dict:
    cursor = conn.cursor()
    cursor.execute(
        """
        SELECT s.version_ia, MAX(m.journee) as max_j, s.id
        FROM sessions s
        LEFT JOIN matches m ON s.id = m.session_id
        WHERE s.type_session = 'TRAINING' AND s.timestamp_fin IS NOT NULL
        GROUP BY s.id
        ORDER BY s.id DESC
        LIMIT 1
    """
    )
    row = cursor.fetchone()
    if row:
        return {"version": row["version_ia"], "max_journee": row["max_j"] if row["max_j"] else 0, "id": row["id"]}
    return {"version": "v0", "max_journee": 0, "id": None}


def get_completed_journees_count(conn: Any) -> int:
    session_id = get_active_session()["id"]
    cursor = conn.cursor()
    cursor.execute(
        "SELECT MAX(journee) as max_journee FROM matches WHERE status = 'TERMINE' AND session_id = %s", (session_id,)
    )
    row = cursor.fetchone()
    return row["max_journee"] if row and row["max_journee"] else 0


def check_new_season_available(conn: Any) -> bool:
    last_meta = get_last_training_metadata(conn)
    current_max = get_completed_journees_count(conn)
    return (current_max - last_meta["max_journee"]) >= 38


def valider_paris_zeus(conn: Any):
    active_session = get_active_session()
    session_id = active_session["id"]
    cursor = conn.cursor()
    query = """
        SELECT
            hp.id_pari,
            hp.prediction_id,
            hp.type_pari,
            hp.mise_ar,
            hp.cote_jouee,
            hp.session_id,
            hp.strategie,
            m.score_dom,
            m.score_ext,
            m.status
        FROM historique_paris hp
        JOIN predictions p ON hp.prediction_id = p.id
        JOIN matches m ON p.match_id = m.id
        WHERE hp.resultat IS NULL
        AND m.status = 'TERMINE'
        AND hp.session_id = %s
    """
    cursor.execute(query, (session_id,))
    paris_en_attente = cursor.fetchall()
    # Grouper par session et stratégie pour suivre les bankrolls séparément
    batches = {}
    for p in paris_en_attente:
        key = (p["session_id"], p.get("strategie", "ZEUS"))
        if key not in batches:
            batches[key] = []
        batches[key].append(p)

    for (sess_id, strat), p_sess in batches.items():
        # Utiliser maintenant le portefeuille GLOBAL pour chaque stratégie
        if strat == "ZEUS":
            from src.core.zeus_finance import get_zeus_bankroll
            current_bankroll = get_zeus_bankroll(conn=conn)
        else:
            from src.core.prisma_finance import get_prisma_bankroll
            current_bankroll = get_prisma_bankroll()
        for p in p_sess:
            is_win = False
            sd, se = p["score_dom"], p["score_ext"]
            if sd is None or se is None:
                continue
            recorded_type = p["type_pari"]
            resultat_reel = "1" if sd > se else ("2" if se > sd else "X")
            if recorded_type == "1" and sd > se:
                is_win = True
            elif recorded_type in ("X", "N") and sd == se:
                is_win = True
            elif recorded_type == "2" and se > sd:
                is_win = True
            if is_win:
                profit_net = int(p["mise_ar"] * (p["cote_jouee"] - 1))
                current_bankroll += int(p["mise_ar"] * p["cote_jouee"])
                resultat_val = 1
            else:
                profit_net = -p["mise_ar"]
                # current_bankroll reste inchangé car mise déjà déduite
                resultat_val = 0
            cursor.execute(
                """
                UPDATE historique_paris
                SET resultat = %s, profit_net = %s, bankroll_apres = %s
                WHERE id_pari = %s
            """,
                (resultat_val, profit_net, current_bankroll, p["id_pari"]),
            )
            cursor.execute(
                """
                UPDATE predictions
                SET succes = %s, resultat = %s
                WHERE id = %s
            """,
                (resultat_val, resultat_reel, p["prediction_id"]),
            )

            if strat == "ZEUS":
                from src.core.zeus_finance import update_zeus_bankroll
                update_zeus_bankroll(current_bankroll, conn=conn)

                delta_score = 1 if is_win else -1
                cursor.execute("UPDATE sessions SET score_zeus = score_zeus + %s WHERE id = %s", (delta_score, sess_id))

                # Gestion de la dette : Remboursement progressif (env. 10% par victoire)
                if is_win and profit_net > 0:
                    cursor.execute("SELECT dette_zeus, total_emprunte_zeus FROM sessions WHERE id = %s", (sess_id,))
                    sess_row = cursor.fetchone()
                    if sess_row and sess_row["dette_zeus"] > 0:
                        montant_dette = sess_row["dette_zeus"]
                        total_emprunte = sess_row["total_emprunte_zeus"]
                        # On rembourse environ 10% du total emprunté à chaque victoire, 
                        # plafonné par le profit et la dette restante
                        cible_remboursement = max(int(total_emprunte * 0.1), 100)  # Minimum 100 Ar pour avancer
                        remboursement = min(profit_net, montant_dette, cible_remboursement)

                        cursor.execute(
                            "UPDATE sessions SET dette_zeus = dette_zeus - %s WHERE id = %s", (remboursement, sess_id)
                        )
                        logger.info(f"ZEUS a remboursé progressivement {remboursement} Ar de sa dette.")
            else:
                # Fix: Mise à jour du bankroll PRISMA directement dans la même transaction
                # (update_prisma_bankroll ouvrait une 2e connexion → risque de deadlock)
                cursor.execute(
                    "INSERT INTO prisma_config (key, value_int, last_update) "
                    "VALUES ('bankroll_prisma', %s, CURRENT_TIMESTAMP) "
                    "ON CONFLICT (key) DO UPDATE SET value_int = EXCLUDED.value_int, last_update = CURRENT_TIMESTAMP",
                    (int(current_bankroll),)
                )
                delta_score = 5 if is_win else -8
                cursor.execute(
                    "UPDATE sessions SET score_prisma = score_prisma + %s WHERE id = %s", (delta_score, sess_id)
                )
    # Le context manager get_db_connection() commit automatiquement
    # Ne pas appeler conn.commit() ici pour éviter le double commit
    logger.info(f"{len(paris_en_attente)} paris simples validés.")
