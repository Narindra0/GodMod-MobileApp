"""
Systeme de surveillance continue de l'API
Detecte automatiquement les nouvelles journees et declenche les collectes

Version: 2.1
Date: Janvier 2025
"""

import time
import random
import logging
import sys
import os
from typing import Optional, Dict

# Ajouter le chemin du projet
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../..')))

from src.api.api_client import get_recent_results, get_ranking, get_upcoming_matches
from src.api.results_filter import extract_results_minimal
from src.api.matches_filter import extract_matches_with_local_ids
from src.api.db_integration import insert_api_ranking, insert_api_results, insert_api_matches
from src.core.database import get_db_connection
from src.core.session_manager import get_active_session, update_session_day
from src.core.console import console, print_info, print_success, print_error, print_warning, print_step, create_panel, create_table
import threading
from src.zeus.training.self_improvement import trigger_zeus_improvement



logger = logging.getLogger(__name__)

# ==================== CONFIGURATION ====================

MONITOR_CONFIG = {
    "POLL_INTERVAL": 5,            # Verifier toutes les 5 secondes (Mise a jour "Live")
    "MAX_RETRIES": 3,              # Nombre de tentatives si erreur
    "RETRY_DELAY": 10,             # Delai entre tentatives (secondes)
    "LOG_ACTIVITY": True,          # Logger l'activite
}

# ==================== FONCTIONS HELPER ====================

def get_max_journee_in_db() -> int:
    """
    Recupere la derniere journee presente en base de donnees
    
    Returns:
        Numero de la derniere journee (0 si vide)
    """
    try:
        with get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT MAX(journee) FROM matches")
            result = cursor.fetchone()[0]
            return result if result else 0
    except Exception as e:
        logger.error(f"Erreur lors de la recuperation de la journee max : {e}")
        return 0


def get_max_journee_from_api() -> Optional[int]:
    """
    Recupere la derniere journee disponible sur l'API.
    """
    try:
        # Recuperer les 2 dernieres journees pour etre sur
        results_raw = get_recent_results(skip=0, take=2)
        results_filtered = extract_results_minimal(results_raw)
        
        if results_filtered:
            # Trouver la journee max
            max_journee = max(r["roundNumber"] for r in results_filtered)
            return max_journee
        
        return None
    except Exception as e:
        logger.error(f"Erreur lors de la recuperation journee API : {e}")
        return None


def get_journee_from_cotes() -> Optional[int]:
    """
    Recupere la premiere journee disponible dans les cotes (pour detecter nouvelle saison)
    
    Returns:
        Numero de la journee dans les cotes ou None si erreur
    """
    try:
        matches_raw = get_upcoming_matches()
        # On prend ~une journee complete pour etre robuste face aux matchs reportes
        matches_filtered = extract_matches_with_local_ids(matches_raw, limit=10)
        
        if matches_filtered:
            # On cherche la plus petite journee dans les matchs a venir
            # pour correctement identifier le debut de la nouvelle saison (J1)
            valid_rounds = [m.get("roundNumber") for m in matches_filtered if m.get("roundNumber") is not None]
            if valid_rounds:
                return min(valid_rounds)
        
        return None
    except Exception as e:
        logger.error(f"Erreur lors de la recuperation journee depuis cotes : {e}")
        return None


def collect_full_data(journee: int) -> bool:
    """
    Collecte complete des donnees pour une nouvelle journee detectee.
    Lie automatiquement les donnees a la session active.
    """
    active_session = get_active_session()
    session_id = active_session['id']
    current_day = active_session['current_day']

    logger.info(f"[COLLECTE] Session {session_id} | Jour {current_day} | Journee Reelle {journee}")
    console.print()
    console.rule(f"[bold green]COLLECTE J{journee} (Session {session_id})[/]")
    console.print()
    
    success = True
    
    # 1. Recuperer les resultats
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

    # 2. Recuperer le classement
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

    # 3. Recuperer les cotes pour J+1
    print_step(f"Recuperation des cotes pour J{journee + 1}")
    try:
        matches_raw = get_upcoming_matches()
        matches_filtered = extract_matches_with_local_ids(matches_raw, limit=2)
        if matches_filtered:
            count = insert_api_matches(matches_filtered, session_id=session_id)
            print_success(f"{count} matchs avec cotes inseres")
        else:
            print_warning(f"Aucune cote disponible pour J{journee + 1} - Normal en fin de saison")
    except Exception as e:
        print_error(f"Erreur cotes : {e}")
    
    if success:
        # Mettre à jour le jour de la session pour correspondre à la journée traitée
        new_state = update_session_day(session_id, journee)
        if new_state['id'] != session_id:
            console.rule("[bold magenta]TRANSITION DE SESSION EFFECTUEE (37 JOURS ATTEINTS)[/]")
            print_success(f"Nouvelle session active : {new_state['id']}")
            # Optionnel: Déclencher entraînement ZEUS lors de la transition
            threading.Thread(target=trigger_zeus_improvement, daemon=True).start()

    console.print()
    return success


# ==================== BOUCLE DE SURVEILLANCE ====================

def start_monitoring(callback_on_new_journee=None, verbose=True):
    """
    Demarre la surveillance continue de l'API
    
    Args:
        callback_on_new_journee: Fonction optionnelle a appeler apres collecte
        verbose: Afficher les messages de surveillance
        
    Example:
        def my_callback(journee):
            print(f"Nouvelle journee {journee} traitee !")
            # Lancer predictions IA, etc.
        
        start_monitoring(callback_on_new_journee=my_callback)
    """
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
    print_info(f"Journee actuelle en BDD : J{last_journee_db}")
    print_info("Surveillance en cours... (CTRL+C pour arreter)")
    console.print()
    
    consecutive_errors = 0
    
    try:
        while True:
            try:
                # 1. Vérifier l'API pour les derniers résultats (Indique la progression du championnat)
                api_journee = get_max_journee_from_api()
                
                # --- EXCEPTION J38 ---
                # Si l'API retourne J38, on l'ignore complètement (Décision métier)
                if api_journee == 38:
                    logger.info("[MONITOR] Exception J38 détectée sur l'API. Ignoration complète.")
                    api_journee = None # On force à None pour ne pas déclencher de collecte
                
                # --- LOGIQUE DE DÉMARRAGE DE SESSION ---
                # Si api_journee est None, c'est NORMAL au début d'une session (aucun match joué)
                # On bascule sur les cotes pour détecter si J1 est prête
                journee_cotes = None
                if api_journee is None:
                    journee_cotes = get_journee_from_cotes()
                    
                    # On ne logue que si on n'est pas déjà à J1 en base (évite le spam)
                    if last_journee_db != 1:
                        logger.info(f"[MONITOR] Session neuve ou remise à zéro (Résultats API vides). Vérification des cotes : J{journee_cotes}")
                    
                if api_journee is None and journee_cotes is None:
                    # Rien du tout sur l'API (Maintenance ou fin de cycle complète)
                    consecutive_errors += 1
                    
                    # Backoff exponentiel : 10s, 20s, 40s, 80s... max 5min (300s)
                    wait_time = min(MONITOR_CONFIG['RETRY_DELAY'] * (2 ** (consecutive_errors - 1)), 300)
                    
                    logger.warning(f"[MONITOR] Impossible de recuperer journee API (Erreur {consecutive_errors}). Nouvelle tentative dans {wait_time}s")
                    print_warning(f"Erreur connexion API ({consecutive_errors}). Attente {wait_time}s...")
                    
                    # On ne break plus jamais la boucle, on attend juste plus longtemps
                    time.sleep(wait_time)
                    continue

                
                # Reset compteur erreurs si succes
                consecutive_errors = 0
                
                # 2. Nouvelle Saison (Transition de session automatique)
                # Si on détecte J1, on s'assure que le session_manager traite la transition
                if journee_cotes == 1 and (last_journee_db >= 37 or last_journee_db == 0):
                    logger.info(f"[MONITOR] Début de cycle détecté (J1).")
                    console.print()
                    console.rule("[bold magenta]TRANSITION DE SESSION[/]")
                    
                    # Récupérer la session active (en crée une si besoin)
                    active_session = get_active_session()
                    
                    # Déclencher la transition si on était en fin de saison (J37+)
                    # Si last_journee_db est 37 ou 38, update_session_day(..., 38+) créera une nouvelle session
                    new_session = update_session_day(active_session['id'], 38 if last_journee_db >= 37 else 1)
                    session_id = new_session['id']
                    
                    # D. Lancer reentrainement ZEUS en arriere-plan
                    print_info("Lancement du cycle d'amélioration ZEUS en arrière-plan...")
                    threading.Thread(target=trigger_zeus_improvement, args=(None,), daemon=True).start()
                    
                    # C. Collecter J1
                    print_step("Collecte des cotes pour J1")
                    try:
                        matches_raw = get_upcoming_matches()
                        matches_filtered = extract_matches_with_local_ids(matches_raw, limit=2)
                        
                        if matches_filtered:
                            # Utiliser explicitement le session_id de la nouvelle session
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
                
                # Comparer avec BDD (seulement si l'API a retourne une journee)
                if api_journee is not None and api_journee > last_journee_db:
                    # NOUVELLE JOURNEE DETECTEE !
                    logger.info(f"[MONITOR] Nouvelle journee detectee : J{api_journee} (BDD: J{last_journee_db})")
                    console.print()
                    console.rule(f"[bold green]ALERTE : Nouvelle journee detectee ![/]")
                    print_info(f"BDD : J{last_journee_db} -> API : J{api_journee}")
                    
                    # Collecte complete
                    success = collect_full_data(api_journee)
                    
                    if success:
                        # Mettre a jour notre reference
                        last_journee_db = api_journee
                        logger.info(f"[MONITOR] Reference mise a jour : J{last_journee_db}")
                        
                        # Appeler le callback si fourni
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
                    # Message de surveillance
                    timestamp = datetime.now().strftime("%H:%M:%S")
                    console.print(f"[{timestamp}] [dim]Surveillance... (BDD: J{last_journee_db}, API: J{api_journee})[/]", end='\r')
                
                # Attendre avant prochain check (Jitter: +/- 40% de l'intervalle -> 3s a 7s)
                base_interval = MONITOR_CONFIG['POLL_INTERVAL']
                jitter = base_interval * 0.4
                sleep_time = random.uniform(base_interval - jitter, base_interval + jitter)
                
                if verbose:
                     # Petit hack visuel pour le timer
                     pass 
                     
                time.sleep(sleep_time)
                
            except KeyboardInterrupt:
                raise  # Propager pour sortir proprement
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


# ==================== TEST ====================

if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )
    
    # Callback de test
    def callback_test(journee):
        print(f"\n[CALLBACK] Nouvelle journee {journee} traitee !")
        print(f"[CALLBACK] Vous pouvez maintenant lancer les predictions IA...")
    
    # Demarrer la surveillance
    start_monitoring(callback_on_new_journee=callback_test, verbose=True)
