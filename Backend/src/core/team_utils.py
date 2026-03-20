from .database import get_db_connection


def get_equipe_logo(equipe_id=None, equipe_nom=None):
    try:
        with get_db_connection() as conn:
            cursor = conn.cursor()
            if equipe_id:
                cursor.execute("SELECT logo_url FROM equipes WHERE id = %s", (equipe_id,))
            elif equipe_nom:
                cursor.execute("SELECT logo_url FROM equipes WHERE nom = %s", (equipe_nom,))
            else:
                return None
            result = cursor.fetchone()
            return result["logo_url"] if result and result["logo_url"] else None
    except Exception as e:
        print(f"Erreur lors de la récupération du logo: {e}")
        return None


def get_toutes_les_equipes_avec_logos():
    try:
        with get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT id, nom, logo_url FROM equipes ORDER BY nom")
            equipes = []
            for row in cursor.fetchall():
                equipes.append({"id": row["id"], "nom": row["nom"], "logo_url": row["logo_url"]})
            return equipes
    except Exception as e:
        print(f"Erreur lors de la récupération des équipes: {e}")
        return []


def get_match_with_logos(match_id):
    try:
        with get_db_connection() as conn:
            cursor = conn.cursor()
            query = """
            SELECT m.id, m.journee, m.score_dom, m.score_ext, m.status,
                   e1.id as dom_id, e1.nom as dom_nom, e1.logo_url as dom_logo,
                   e2.id as ext_id, e2.nom as ext_nom, e2.logo_url as ext_logo
            FROM matches m
            JOIN equipes e1 ON m.equipe_dom_id = e1.id
            JOIN equipes e2 ON m.equipe_ext_id = e2.id
            WHERE m.id = %s
            """
            cursor.execute(query, (match_id,))
            row = cursor.fetchone()
            if row:
                return {
                    "id": row["id"],
                    "journee": row["journee"],
                    "score_dom": row["score_dom"],
                    "score_ext": row["score_ext"],
                    "status": row["status"],
                    "equipe_dom": {"id": row["dom_id"], "nom": row["dom_nom"], "logo_url": row["dom_logo"]},
                    "equipe_ext": {"id": row["ext_id"], "nom": row["ext_nom"], "logo_url": row["ext_logo"]},
                }
            return None
    except Exception as e:
        print(f"Erreur lors de la récupération du match: {e}")
        return None
