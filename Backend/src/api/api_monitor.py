import time
import random
import logging
import sys
import os
from typing import Optional, Dict
from datetime import datetime
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../..')))
from src.api.api_client import get_recent_results, get_ranking, get_upcoming_matches
from src.api.results_filter import extract_results_minimal
from src.api.matches_filter import extract_matches_with_local_ids
from src.api.db_integration import insert_api_ranking, insert_api_results, insert_api_matches
from src.core.database import get_db_connection
from src.core.session_manager import get_active_session, update_session_day
from src.core.console import console, print_info, print_success, print_error, print_warning, print_step, create_panel, create_table, print_verbose
import threading
from src.zeus.training.self_improvement import trigger_zeus_improvement
from src.analysis.intelligence import vider_cache_intelligence
logger = logging.getLogger(__name__)
MONITOR_CONFIG = {
    "POLL_INTERVAL": 5,
    "MAX_RETRIES": 3,
    "RETRY_DELAY": 10,
    "LOG_ACTIVITY": True,
}
def get_max_journee_in_db() -> int:
    try:
        with get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT MAX(m.journee)
                FROM matches m
                JOIN sessions s ON s.id = m.session_id
                WHERE s.status = 'ACTIVE'
            """)
            result = cursor.fetchone()[0]
            return result if result else 0
    except Exception as e:
        logger.error(f"Erreur lors de la recuperation de la journee max : {e}")
        return 0
def get_max_journee_from_api() -> Optional[int]:
    try:
        results_raw = get_recent_results(skip=0, take=2)
        results_filtered = extract_results_minimal(results_raw)
        if results_filtered:
            max_journee = max(r["roundNumber"] for r in results_filtered)
            return max_journee
        return None
    except Exception as e:
        logger.error(f"Erreur lors de la recuperation journee API : {e}")
        return None
def get_journee_from_cotes() -> Optional[int]:
    try:
        matches_raw = get_upcoming_matches()
        matches_filtered = extract_matches_with_local_ids(matches_raw, limit=10)
        if matches_filtered:
            valid_rounds = [m.get("roundNumber") for m in matches_filtered if m.get("roundNumber") is not None]
            if valid_rounds:
                return min(valid_rounds)
        return None
    except Exception as e:
        logger.error(f"Erreur lors de la recuperation journee depuis cotes : {e}")
        return None
def collect_full_data(journee: int) -> bool:
    active_session = get_active_session()
    session_id = active_session['id']
    current_day = active_session['current_day']
    logger.info(f"[COLLECTE] Session {session_id} | Jour {current_day} | Journee Reelle {journee}")
    console.print()
    console.rule(f"[bold green]COLLECTE J{journee} (Session {session_id})[/]")
    console.print()
    success = True
    print_step("Recuperation des resultats")
    try:
        results_raw = get_recent_results(skip=0, take=4)
        results_filtered = extract_results_minimal(results_raw)
        if results_filtered:
            count, validated = insert_api_results(results_filtered, session_id=session_id)
            print_success(f"{count} resultats unifies (+{validated} valides)")
        else:
            print_warning("Aucun resultat recupere")
            success = False
    except Exception as e:
        print_error(f"Erreur resultats : {e}")
        success = False
    time.sleep(random.uniform(0.5, 1.5))
    print_step("Recuperation du classement")
    try:
        ranking_data = get_ranking()
        if ranking_data:
            count = insert_api_ranking(ranking_data, session_id=session_id)
            print_success(f"{count} equipes inserees")
        else:
            success = False
    except Exception as e:
        print_error(f"Erreur classement : {e}")
        success = False
    time.sleep(random.uniform(0.5, 1.5))
    print_step(f"Recuperation des cotes pour J{journee + 1}")
    try:
        matches_raw = get_upcoming_matches()
        matches_filtered = extract_matches_with_local_ids(matches_raw, limit=10)
        if matches_filtered:
            count = insert_api_matches(matches_filtered, session_id=session_id)
            print_success(f"{count} matchs avec cotes inseres")
        else:
            print_warning(f"Aucune cote disponible pour J{journee + 1} - Normal en fin de saison")
    except Exception as e:
        print_error(f"Erreur cotes : {e}")
    if success:
        new_state = update_session_day(session_id, journee)
        if new_state['id'] != session_id:
            console.rule("[bold magenta]TRANSITION DE SESSION EFFECTUEE (37 JOURS ATTEINTS)[/]")
            print_success(f"Nouvelle session active : {new_state['id']}")
            threading.Thread(target=trigger_zeus_improvement, daemon=True).start()
        # Vider le cache pour que le prochain cycle d'IA utilise les données fraîches
        vider_cache_intelligence()
    console.print()
    return success
def start_monitoring(callback_on_new_journee=None, verbose=True):
    logger.info("[MONITOR] Demarrage de la surveillance API")
    console.print()
    console.print(create_panel(
        "Mode: Detection automatique nouvelles journees\n" +
        f"Intervalle: {MONITOR_CONFIG['POLL_INTERVAL']}s",
        title="SURVEILLANCE API ACTIVEE",
        style="green"
    ))
    last_journee_db = get_max_journee_in_db()
    logger.info(f"[MONITOR] Journee initiale en BDD : J{last_journee_db}")
    print_verbose(f"Journee actuelle en BDD : J{last_journee_db}")
    print_verbose("Surveillance en cours... (CTRL+C pour arreter)")
    console.print()
    consecutive_errors = 0
    try:
        while True:
            try:
                api_journee = get_max_journee_from_api()
                if api_journee == 38:
                    logger.info("[MONITOR] Exception J38 détectée sur l'API. Ignoration complète.")
                    api_journee = None
                journee_cotes = None
                if api_journee is None:
                    journee_cotes = get_journee_from_cotes()
                    if last_journee_db != 1:
                        logger.info(f"[MONITOR] Session neuve ou remise à zéro (Résultats API vides). Vérification des cotes : J{journee_cotes}")
                if api_journee is None and journee_cotes is None:
                    consecutive_errors += 1
                    wait_time = min(MONITOR_CONFIG['RETRY_DELAY'] * (2 ** (consecutive_errors - 1)), 300)
                    logger.warning(f"[MONITOR] Impossible de recuperer journee API (Erreur {consecutive_errors}). Nouvelle tentative dans {wait_time}s")
                    print_warning(f"Erreur connexion API ({consecutive_errors}). Attente {wait_time}s...")
                    time.sleep(wait_time)
                    continue
                consecutive_errors = 0
                if journee_cotes == 1 and (last_journee_db >= 37 or last_journee_db == 0):
                    logger.info(f"[MONITOR] Début de cycle détecté (J1).")
                    console.print()
                    console.rule("[bold magenta]TRANSITION DE SESSION[/]")
                    active_session = get_active_session()
                    new_session = update_session_day(active_session['id'], 38 if last_journee_db >= 37 else 1)
                    session_id = new_session['id']
                    print_info("Lancement du cycle d'amélioration ZEUS en arrière-plan...")
                    threading.Thread(target=trigger_zeus_improvement, args=(None,), daemon=True).start()
                    print_step("Collecte des cotes pour J1")
                    try:
                        matches_raw = get_upcoming_matches()
                        matches_filtered = extract_matches_with_local_ids(matches_raw, limit=2)
                        if matches_filtered:
                            count = insert_api_matches(matches_filtered, session_id=session_id)
                            print_success(f"{count} matchs insérés pour la nouvelle session {session_id}")
                            last_journee_db = 1
                            if callback_on_new_journee:
                                callback_on_new_journee(1)
                        else:
                            print_warning("Aucune cote recuperee pour J1")
                    except Exception as e:
                        print_error(f"Erreur cotes J1 : {e}")
                    continue
                if api_journee is not None and api_journee > last_journee_db:
                    logger.info(f"[MONITOR] Nouvelle journee detectee : J{api_journee} (BDD: J{last_journee_db})")
                    console.print()
                    console.rule(f"[bold green]ALERTE : Nouvelle journee detectee ![/]")
                    print_info(f"BDD : J{last_journee_db} -> API : J{api_journee}")
                    success = collect_full_data(api_journee)
                    if success:
                        last_journee_db = api_journee
                        logger.info(f"[MONITOR] Reference mise a jour : J{last_journee_db}")
                        if callback_on_new_journee:
                            try:
                                logger.info(f"[MONITOR] Appel callback utilisateur pour J{api_journee}")
                                callback_on_new_journee(api_journee)
                            except Exception as e:
                                logger.error(f"[MONITOR] Erreur dans callback utilisateur : {e}")
                                print_error(f"Erreur dans callback : {e}")
                    else:
                        logger.warning(f"[MONITOR] Collecte incomplete pour J{api_journee}, nouvelle tentative au prochain cycle")
                        print_warning(f"Collecte incomplete, nouvelle tentative dans {MONITOR_CONFIG['POLL_INTERVAL']}s")
                elif verbose and MONITOR_CONFIG["LOG_ACTIVITY"]:
                    timestamp = datetime.now().strftime("%H:%M:%S")
                    print_verbose(f"Surveillance... (BDD: J{last_journee_db}, API: J{api_journee})")
                base_interval = MONITOR_CONFIG['POLL_INTERVAL']
                jitter = base_interval * 0.4
                sleep_time = random.uniform(base_interval - jitter, base_interval + jitter)
                time.sleep(sleep_time)
            except KeyboardInterrupt:
                raise
            except Exception as e:
                logger.error(f"[MONITOR] Erreur dans boucle surveillance : {e}", exc_info=True)
                print_error(f"Erreur surveillance : {e}")
                consecutive_errors += 1
                if consecutive_errors >= MONITOR_CONFIG['MAX_RETRIES']:
                    logger.error("[MONITOR] Trop d'erreurs, arret surveillance")
                    break
                time.sleep(MONITOR_CONFIG['RETRY_DELAY'])
    except KeyboardInterrupt:
        console.print()
        console.rule("[bold red]STOP[/]")
        print_warning("Arret surveillance (utilisateur)")
        logger.info("[MONITOR] Arret surveillance par utilisateur")
    finally:
        logger.info(f"[MONITOR] Fin surveillance - Derniere journee: J{last_journee_db}")
