import json
import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Dict, List
import time
from ..core import config

logger = logging.getLogger(__name__)

# Suivi des IAs désactivées automatiquement
DISABLED_IAS = set()

# Bornes du boost renvoyé par l'IA
_BOOST_MIN = -5.0
_BOOST_MAX = 5.0
_BOOST_FALLBACK = 0.0

# Intervalle minimum entre deux appels Groq (secondes)
_RATE_LIMIT_SECONDS = 60

_SYSTEM_PROMPT = (
    "Tu es un expert analyste en football virtuel. Analyse les statistiques fournies.\n"
    "Ton expertise doit être technique, précise et argumentée.\n"
    "Retourne UNIQUEMENT un objet JSON au format :\n"
    '{"matches": [{\n'
    '  "match": "Equipe A vs Equipe B",\n'
    '  "prognosis": "1", "X" ou "2",\n'
    '  "confidence": <int 0 à 100>,\n'
    '  "analysis": "<analyse détaillée du match et lecture tactique>",\n'
    '  "advice": "<conseil de pari spécifique>"\n'
    '}]}\n'
)


@dataclass(frozen=True)
class BoostBatchContext:
    batch: List[Dict[str, Any]]
    match_map: Dict[str, Dict[str, Any]]
    session_id: int
    journee: int
    conn: Any


def _decode_forme(forme: str | None) -> str:
    """Convertit une chaîne de forme (ex: 'VVNDV') en texte lisible."""
    if not forme:
        return "Aucun historique"
    mapping = {"V": "Victoire", "N": "Nul", "D": "Défaite"}
    return " → ".join(mapping.get(c, "?") for c in list(forme)[-10:])


def _build_batch_prompt(matches: List[Dict[str, Any]]) -> str:
    """Construit un prompt unique pour tous les matchs de la journée."""
    lines = ["Analyse ces matchs de football virtuel :\n"]
    for i, m in enumerate(matches, 1):
        lines.append(
            f"M{i}: {m['nom_dom']} vs {m['nom_ext']} | "
            f"Dom: {m['pts_dom']}pts, Forme: {_decode_forme(m['forme_dom'])} | "
            f"Ext: {m['pts_ext']}pts, Forme: {_decode_forme(m['forme_ext'])} | "
            f"Cotes: {m['cote_1']}/{m['cote_x']}/{m['cote_2']} | "
            f"PRISMA: {m['prisma_score']:.2f} ({m['prediction']})"
        )
    lines.append(
        "\nPour chaque match, retourne un élément JSON avec 'match' (nom exact du match), "
        "'boost' (entre -5 et +5) et 'raison' (explication courte)."
    )
    return "\n".join(lines)


def _is_rate_limited(session_id: int, journee: int, conn) -> bool:
    """Retourne True si un appel Groq a déjà eu lieu récemment pour cette (session, journée)."""
    try:
        cursor = conn.cursor()
        cursor.execute(
            "SELECT MAX(timestamp) as max_ts FROM groq_boosts WHERE session_id = %s AND journee = %s",
            (session_id, journee),
        )
        row = cursor.fetchone()
        if row:
            # Gérer RealDictRow (dict) ou tuple standard
            last_ts = row["max_ts"] if isinstance(row, dict) else row[0]
            if last_ts:
                if last_ts.tzinfo is None:
                    last_ts = last_ts.replace(tzinfo=timezone.utc)
                now = datetime.now(timezone.utc)
                delta = (now - last_ts).total_seconds()
                if delta < _RATE_LIMIT_SECONDS:
                    logger.info(
                        f"[GROQ] Rate limit actif : dernier appel il y a {delta:.0f}s (< {_RATE_LIMIT_SECONDS}s). Skip."
                    )
                    return True
    except Exception as e:
        logger.warning(f"[GROQ] Erreur vérification rate limit: {e}")
    return False


def _cache_exists(session_id: int, journee: int, conn) -> bool:
    """Retourne True si des boosts sont déjà en cache pour cette (session, journée)."""
    try:
        cursor = conn.cursor()
        cursor.execute(
            "SELECT COUNT(*) as count_val FROM groq_boosts WHERE session_id = %s AND journee = %s",
            (session_id, journee),
        )
        row = cursor.fetchone()
        if not row:
            return False
        count = row["count_val"] if isinstance(row, dict) else row[0]
        return count > 0
    except Exception as e:
        logger.warning(f"[GROQ] Erreur vérification cache: {e}")
        return False


def _store_boosts(session_id: int, journee: int, analyses: List[Dict], match_map: Dict[str, Dict], conn):
    """Persiste les analyses IA dans la table groq_boosts."""
    cursor = conn.cursor()
    stored = 0
    for item in analyses:
        match_key = item.get("match", "")
        match_info = match_map.get(match_key)
        if not match_info:
            logger.warning(f"[AI-ANALYSIS] Match inconnu dans la réponse: '{match_key}'")
            continue
            
        # On garde une compatibilité avec la colonne 'boost' mais on privilégie l'analyse
        confidence = float(item.get("confidence", 0))
        prognosis = item.get("prognosis", "X")
        
        # Plus de boost mathématique, seulement l'analyse IA textuelle
        legacy_boost = 0.0
        
        # Stockage de l'objet complet en JSON dans le champ 'raison'
        analysis_data = {
            "prognosis": prognosis,
            "confidence": confidence,
            "analysis": item.get("analysis", ""),
            "advice": item.get("advice", ""),
            "reasoning": item.get("reasoning", ""),  # Ajout du reasoning NVIDIA
            "timestamp": datetime.now().isoformat()
        }
        raison_json = json.dumps(analysis_data, ensure_ascii=False)
        
        cursor.execute(
            """
            INSERT INTO groq_boosts (session_id, journee, equipe_dom_id, equipe_ext_id, boost, raison)
            VALUES (%s, %s, %s, %s, %s, %s)
            ON CONFLICT (session_id, journee, equipe_dom_id, equipe_ext_id)
            DO UPDATE SET boost = EXCLUDED.boost, raison = EXCLUDED.raison, timestamp = CURRENT_TIMESTAMP
            """,
            (session_id, journee, match_info["equipe_dom_id"], match_info["equipe_ext_id"], legacy_boost, raison_json),
        )
        stored += 1
        logger.info(f"[AI-ANALYSIS] {match_key} -> {prognosis} ({confidence}%)")
    conn.commit()
    logger.info(f"[AI-ANALYSIS] {stored}/{len(analyses)} analyses persistées en DB pour J{journee}.")


def analyze_and_store_journee_async(journee: int, session_id: int):
    """Version asynchrone de analyze_and_store_journee pour éviter les blocages."""
    import threading
    from ..core.database import get_db_connection
    
    def _run_analysis():
        try:
            with get_db_connection(write=True) as conn:
                success = analyze_and_store_journee(journee, session_id, conn)
                if success:
                    logger.info(f"[AI-BOOSTER] Analyse asynchrone J{journee} terminée avec succès")
                else:
                    logger.info(f"[AI-BOOSTER] Analyse asynchrone J{journee} ignorée (cache/rate limit)")
        except Exception as e:
            logger.error(f"[AI-BOOSTER] Erreur analyse asynchrone J{journee}: {e}")
    
    # Lancer dans un thread daemon
    thread = threading.Thread(target=_run_analysis, daemon=True)
    thread.start()
    logger.info(f"[AI-BOOSTER] Analyse J{journee} lancée en arrière-plan")


def analyze_and_store_journee(journee: int, session_id: int, conn) -> bool:
    """
    Appel principal événementiel : analyse tous les matchs de la journée en un seul
    appel Gemini, puis stocke les résultats en DB.
    Retourne True si l'appel a été effectué, False sinon (cache hit, rate limit, erreur).
    """
    # Utilisation de Google Gemini (gemini-1.5-flash)
    api_key = getattr(config, "GEMINI_API_KEY", None)
    if not api_key:
        logger.warning("[AI-BOOSTER] GEMINI_API_KEY manquante ou vide dans config/env.")
        return False

    # Vérification cache
    if _cache_exists(session_id, journee, conn):
        logger.info(f"[AI-BOOSTER] Analyse J{journee} deja en cache. Skip.")
        return False

    # Vérification rate limit
    if _is_rate_limited(session_id, journee, conn):
        return False

    try:
        cursor = conn.cursor()

        # Récupérer tous les matchs + données nécessaires pour la journée
        cursor.execute(
            """
            SELECT m.id, m.equipe_dom_id, m.equipe_ext_id,
                   e1.nom as nom_dom, e2.nom as nom_ext,
                   m.cote_1, m.cote_x, m.cote_2,
                   c1.points as pts_dom, c1.forme as forme_dom,
                   c2.points as pts_ext, c2.forme as forme_ext
            FROM matches m
            JOIN equipes e1 ON m.equipe_dom_id = e1.id
            JOIN equipes e2 ON m.equipe_ext_id = e2.id
            LEFT JOIN (
                SELECT DISTINCT ON (equipe_id) equipe_id, points, forme 
                FROM classement 
                WHERE session_id = %s 
                ORDER BY equipe_id, journee DESC
            ) c1 ON c1.equipe_id = m.equipe_dom_id
            LEFT JOIN (
                SELECT DISTINCT ON (equipe_id) equipe_id, points, forme 
                FROM classement 
                WHERE session_id = %s 
                ORDER BY equipe_id, journee DESC
            ) c2 ON c2.equipe_id = m.equipe_ext_id
            WHERE m.session_id = %s AND m.journee = %s
        """,
            (session_id, session_id, session_id, journee),
        )
        rows = cursor.fetchall()

        if not rows:
            logger.warning(f"[GROQ] Aucun match trouvé pour J{journee}. Pas d'appel Groq.")
            return False

        # Récupérer les prédictions PRISMA déjà calculées (si disponibles)
        cursor.execute(
            """
            SELECT p.match_id, p.prediction, p.fiabilite
            FROM predictions p
            WHERE p.session_id = %s
              AND p.match_id IN (SELECT id FROM matches WHERE session_id = %s AND journee = %s)
        """,
            (session_id, session_id, journee),
        )
        predictions_map = {r["match_id"]: r for r in cursor.fetchall()}

        # Construire la liste de matchs pour le prompt
        matches_data = []
        match_map = {}  # clé "Dom vs Ext" → ids
        for row in rows:
            nom_dom = row["nom_dom"]
            nom_ext = row["nom_ext"]
            match_key = f"{nom_dom} vs {nom_ext}"
            pred_info = predictions_map.get(row["id"], {})
            matches_data.append(
                {
                    "nom_dom": nom_dom,
                    "nom_ext": nom_ext,
                    "pts_dom": row["pts_dom"] or 0,
                    "pts_ext": row["pts_ext"] or 0,
                    "forme_dom": row["forme_dom"] or "",
                    "forme_ext": row["forme_ext"] or "",
                    "cote_1": row["cote_1"] or "?",
                    "cote_x": row["cote_x"] or "?",
                    "cote_2": row["cote_2"] or "?",
                    "prisma_score": float(pred_info.get("fiabilite") or 0.0),
                    "prediction": pred_info.get("prediction") or "?",
                }
            )
            match_map[match_key] = {
                "equipe_dom_id": row["equipe_dom_id"],
                "equipe_ext_id": row["equipe_ext_id"],
            }

        # Détection Alternance Ternaire (%)
        # J%3 == 1: Gemini (P), Groq (S1), DeepSeek (S2)
        # J%3 == 2: Groq (P), DeepSeek (S1), Gemini (S2)
        # J%3 == 0: DeepSeek (P), Gemini (S1), Groq (S2)
        cycle_idx = journee % 3

        # Définition de l'ordre des IAs
        if cycle_idx == 1:
            ia_order = ["GEMINI", "GROQ", "DEEPSEEK"]
        elif cycle_idx == 2:
            ia_order = ["GROQ", "DEEPSEEK", "GEMINI"]
        else:  # cycle_idx == 0
            ia_order = ["DEEPSEEK", "GEMINI", "GROQ"]

        logger.info(f"[AI-BOOSTER] J{journee} Cycle {cycle_idx} : Ordre IA = {' -> '.join(ia_order)}")
        
        # Afficher les IAs désactivées
        if DISABLED_IAS:
            logger.warning(f"[AI-BOOSTER] IAs désactivées (timeout) : {', '.join(DISABLED_IAS)}")

        # Initialisation Gemini
        from google import genai

        gemini_client = genai.Client(api_key=api_key)
        gemini_model = getattr(config, "GEMINI_MODEL", "gemini-1.5-flash")

        # Micro-batching : 5 matchs par appel pour la stabilité
        MICRO_BATCH_SIZE = 5
        for i in range(0, len(matches_data), MICRO_BATCH_SIZE):
            batch = matches_data[i : i + MICRO_BATCH_SIZE]
            batch_ctx = BoostBatchContext(
                batch=batch,
                match_map=match_map,
                session_id=session_id,
                journee=journee,
                conn=conn,
            )
            success = False

            # --- LOGIQUE DE ROTATION ---
            for ia_name in ia_order:
                # Vérifier si l'IA est désactivée
                if ia_name in DISABLED_IAS:
                    logger.info(f"[AI-BOOSTER] {ia_name} désactivée (timeout précédent). Skip...")
                    continue
                    
                if ia_name == "GEMINI":
                    success = _analyze_with_gemini(gemini_client, gemini_model, batch_ctx)
                elif ia_name == "GROQ":
                    success = _analyze_with_groq(batch_ctx)
                elif ia_name == "DEEPSEEK":
                    success = _analyze_with_deepseek(batch_ctx)

                if success:
                    break
                else:
                    logger.info(
                        f"[AI-BOOSTER] {ia_name} a echoue sur batch "
                        f"{i//MICRO_BATCH_SIZE + 1}. Tentative sur l'IA suivante..."
                    )

            if not success:
                logger.warning(
                    f"[AI-BOOSTER] ECHEC CRITIQUE : Aucune des 3 IAs n'a pu traiter le batch {i//MICRO_BATCH_SIZE + 1}."
                )

        return True

    except ImportError:
        logger.warning("[GEMINI] Bibliothèque 'google-genai' non installée. Analyse ignorée.")
        return False
    except Exception as e:
        logger.warning(f"[AI-BOOSTER] Erreur générale Analyse ({type(e).__name__}): {e}")
        return False


def _analyze_with_gemini(client, model_name, batch_ctx: BoostBatchContext) -> bool:
    """Analyse un micro-batch via Gemini avec gestion de retry."""
    MAX_RETRIES = 3
    retry_count = 0
    prompt = _build_batch_prompt(batch_ctx.batch)

    while retry_count < MAX_RETRIES:
        try:
            response = client.models.generate_content(
                model=model_name,
                contents=f"{_SYSTEM_PROMPT}\n\nDonnées :\n{prompt}",
                config={"response_mime_type": "application/json", "temperature": 0.1},
            )
            parsed = json.loads(response.text)
            boosts_list = parsed.get("matches", parsed.get("results", list(parsed.values())[0] if parsed else []))
            if isinstance(boosts_list, list):
                _store_boosts(batch_ctx.session_id, batch_ctx.journee, boosts_list, batch_ctx.match_map, batch_ctx.conn)
                return True
            return False
        except Exception as e:
            if "429" in str(e) or "RESOURCE_EXHAUSTED" in str(e):
                retry_count += 1
                if retry_count < MAX_RETRIES:
                    logger.warning(f"[GEMINI] Quota atteint. Retry {retry_count}/{MAX_RETRIES}...")
                    time.sleep(10)
                continue
            
            # Détecter les erreurs de timeout/gateway pour passer immédiatement à l'IA suivante
            error_msg = str(e).lower()
            if any(keyword in error_msg for keyword in ["timeout", "504", "gateway", "connection"]):
                logger.warning(f"[AI-BOOSTER] GEMINI indisponible (timeout/gateway) : {e}")
                DISABLED_IAS.add("GEMINI")
                logger.error(f"[AI-BOOSTER] GEMINI désactivée automatiquement jusqu'au redémarrage")
            else:
                logger.warning(f"[GEMINI] Erreur sur batch: {e}")
            break
    return False


def _analyze_with_groq(batch_ctx: BoostBatchContext) -> bool:
    """Fonction de secours utilisant l'API Groq (Llama-3.1-8b)."""
    api_key = getattr(config, "GROQ_API_KEY", None)
    if not api_key:
        logger.warning("[AI-BOOSTER] GROQ_API_KEY manquante pour le fallback.")
        return False

    try:
        from groq import Groq

        client = Groq(api_key=api_key)
        model = getattr(config, "GROQ_MODEL", "llama-3.1-8b-instant")

        prompt = _build_batch_prompt(batch_ctx.batch)
        completion = client.chat.completions.create(
            model=model,
            messages=[{"role": "system", "content": _SYSTEM_PROMPT}, {"role": "user", "content": prompt}],
            temperature=0.1,
            response_format={"type": "json_object"},
        )

        content = completion.choices[0].message.content
        parsed = json.loads(content)
        boosts_list = parsed.get("matches", [])

        if boosts_list:
            _store_boosts(batch_ctx.session_id, batch_ctx.journee, boosts_list, batch_ctx.match_map, batch_ctx.conn)
            return True

    except Exception as e:
        # Détecter les erreurs de timeout/gateway pour passer immédiatement à l'IA suivante
        error_msg = str(e).lower()
        if any(keyword in error_msg for keyword in ["timeout", "504", "gateway", "connection", "rate limit"]):
            logger.warning(f"[AI-BOOSTER] GROQ indisponible (timeout/rate limit) : {e}")
            DISABLED_IAS.add("GROQ")
            logger.error(f"[AI-BOOSTER] GROQ désactivée automatiquement jusqu'au redémarrage")
        else:
            logger.error(f"[AI-BOOSTER] Echec du fallback GROQ : {e}")

    return False


def _analyze_with_deepseek(batch_ctx: BoostBatchContext) -> bool:
    """Analyse via l'API NVIDIA DeepSeek avec mode reasoning."""
    api_key = getattr(config, "DEEPSEEK_API_KEY", None)
    if not api_key:
        logger.warning("[AI-BOOSTER] DEEPSEEK_API_KEY manquante.")
        return False

    try:
        from openai import OpenAI

        client = OpenAI(base_url=config.DEEPSEEK_BASE_URL, api_key=api_key)
        model = config.DEEPSEEK_MODEL

        prompt = _build_batch_prompt(batch_ctx.batch)
        
        # Appel avec mode reasoning et paramètres NVIDIA
        completion = client.chat.completions.create(
            model=model,
            messages=[{"role": "system", "content": _SYSTEM_PROMPT}, {"role": "user", "content": prompt}],
            temperature=1.0,
            top_p=0.95,
            max_tokens=8192,
            extra_body={"chat_template_kwargs": {"thinking": True}}
        )

        content = completion.choices[0].message.content
        
        # Récupérer le reasoning si disponible
        reasoning_content = getattr(completion.choices[0].message, 'reasoning_content', None)
        
        # Nettoyage si DeepSeek renvoie du markdown
        if "```json" in content:
            content = content.split("```json")[1].split("```")[0].strip()

        parsed = json.loads(content)
        boosts_list = parsed.get("matches", parsed.get("results", []))

        if boosts_list:
            # Enrichir les résultats avec le reasoning si disponible
            if reasoning_content:
                for item in boosts_list:
                    item["reasoning"] = reasoning_content
            
            _store_boosts(batch_ctx.session_id, batch_ctx.journee, boosts_list, batch_ctx.match_map, batch_ctx.conn)
            logger.info(f"[AI-BOOSTER] DeepSeek NVIDIA reasoning activé pour {len(boosts_list)} matchs")
            return True

    except Exception as e:
        # Détecter les erreurs de timeout/gateway pour passer immédiatement à l'IA suivante
        error_msg = str(e).lower()
        if any(keyword in error_msg for keyword in ["timeout", "504", "gateway", "connection"]):
            logger.warning(f"[AI-BOOSTER] DEEPSEEK NVIDIA indisponible (timeout/gateway) : {e}")
            DISABLED_IAS.add("DEEPSEEK")
            logger.error(f"[AI-BOOSTER] DEEPSEEK désactivée automatiquement jusqu'au redémarrage")
        else:
            logger.error(f"[AI-BOOSTER] Echec DEEPSEEK NVIDIA : {e}")

    return False


def get_cached_analysis(session_id: int, journee: int, equipe_dom_id: int, equipe_ext_id: int, conn) -> dict:
    """
    Lecture seule du cache d'analyse IA en DB.
    Retourne l'objet d'analyse complet ou None si pas de cache.
    """
    try:
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT boost, raison FROM groq_boosts
            WHERE session_id = %s AND journee = %s
              AND equipe_dom_id = %s AND equipe_ext_id = %s
            """,
            (session_id, journee, equipe_dom_id, equipe_ext_id),
        )
        row = cursor.fetchone()
        if not row:
            return None
            
        try:
            # On tente de parser la raison comme du JSON
            return json.loads(row["raison"])
        except (json.JSONDecodeError, TypeError):
            # Fallback pour les anciennes entrées (texte pur)
            return {
                "prognosis": "1" if row["boost"] > 0 else ("2" if row["boost"] < 0 else "X"),
                "confidence": abs(row["boost"]) * 20,
                "analysis": row["raison"],
                "advice": "Analyse historique disponible."
            }
    except Exception as e:
        logger.warning(f"[AI-ANALYSIS] Erreur lecture cache analysis: {e}")
        return None
