import logging
import threading
import time

import os
import sys

# Détection Headless (Hugging Face / Docker) pour désactiver keyboard qui plante sans clavier
def _check_keyboard():
    if os.environ.get("HEADLESS") == "true" or not sys.stdin.isatty():
        return False
    try:
        import keyboard
        return True
    except (ImportError, Exception):
        return False

KEYBOARD_AVAILABLE = _check_keyboard()
from dotenv import load_dotenv

from src.analysis import ai_booster, intelligence
from src.api.api_monitor import start_monitoring
from src.api.server import start_api_server
from src.core import config, database
from src.core.console import (
    Panel,
    Text,
    console,
    create_panel,
    create_table,
    is_verbose,
    print_error,
    print_info,
    print_step,
    print_success,
    print_verbose,
    print_warning,
    set_verbose_mode,
)

from src.core.logging_setup import setup_app_logging
setup_app_logging()
logger = logging.getLogger(__name__)

load_dotenv()


def callback_predictions_ia(journee: int):
    console.print()
    console.print(create_panel(f"[bold]ANALYSE INTELLIGENTE - J{journee}[/]", style="magenta"))
    
    # Initialisation sécurisée pour éviter UnboundLocalError
    br_zeus = 0
    br_prisma = 0
    
    try:
        print_step("Validation des predictions precedentes")
        intelligence.mettre_a_jour_scoring()
        print_success("Score IA mis a jour avec les derniers resultats")
        
        # --- MISE À JOUR MATRICE DE FORCE ---
        print_step("Mise à jour matrice de force relative")
        try:
            from src.prisma.team_strength_matrix import update_strength_matrix
            from src.core.session_manager import get_active_session
            with database.get_db_connection(write=True) as conn:
                session = get_active_session(conn)
                if session:
                    update_strength_matrix(conn, session['id'], journee - 1)  # Journée précédente complétée
                    print_success("Matrice de force mise à jour")
        except Exception as e:
            logger.warning(f"Erreur mise à jour matrice: {e}")
        
        journee_prediction = journee + 1
        if journee_prediction < config.JOURNEE_DEPART_PREDICTION:
            print_info(f"J{journee_prediction} < J{config.JOURNEE_DEPART_PREDICTION} (seuil de demarrage)")
            console.print("[dim]Collecte des donnees uniquement. Pas de predictions.[/]")
            return
        print_step(f"Generation predictions pour J{journee_prediction}")
        # --- Vérification Toggle IA ---
        ai_enabled = True
        try:
            with database.get_db_connection() as conn_check:
                with conn_check.cursor() as cur_check:
                    cur_check.execute("SELECT value_int FROM prisma_config WHERE key = 'ai_enabled'")
                    row_ai = cur_check.fetchone()
                    if row_ai:
                        ai_enabled = bool(row_ai["value_int"])
        except Exception as e:
            logger.warning(f"Erreur check AI toggle: {e}")

        if ai_enabled:
            # --- Nouveau Système d'Audit Stratégique ---
            # Au lieu de toutes les 6h, on audite à des étapes clés
            if journee in [12, 24, 37]:
                ranges = {12: (1, 12), 24: (13, 24), 37: (1, 36)}
                start_j, end_j = ranges[journee]
                print_info(f"   [IA-BOOSTER] Déclenchement audit stratégique : J{start_j} à J{end_j}")
                try:
                    active_session = intelligence.get_cached_active_session()
                    if active_session:
                        ai_booster.perform_cycle_audit_async(journee, active_session['id'], start_j, end_j)
                except Exception as e:
                    logger.error(f"Erreur déclenchement audit J{journee}: {e}")
            
            print_verbose(f"   [IA-BOOSTER] Journée {journee} - Analyse en cours")
        else:
            print_warning("Analyse IA Booster DESACTIVEE par utilisateur")

        if config.USE_SELECTION_AMELIOREE:
            print_verbose("   [dim][SHIELD] Mode: PRISMA Complete (Phase 3 - 7 facteurs)[/]")
            selections_prisma = intelligence.selectionner_meilleurs_matchs_ameliore(journee_prediction)
        else:
            print_verbose("   [dim][SHIELD] Mode: PRISMA Standard[/]")
            selections_prisma = intelligence.selectionner_meilleurs_matchs(journee_prediction)
        print_verbose("   [dim][BANK] Mode: ZEUS RL (Autonomous Agent)[/]")
        selections_zeus = intelligence.obtenir_predictions_zeus_journee(journee_prediction)
        prisma_map = {f"{s['equipe_dom']} vs {s['equipe_ext']}": s for s in selections_prisma}
        bankroll = config.DEFAULT_BANKROLL  # Bankroll par defaut

        # Récupération immédiate des soldes réels pour affichage et diagnostic
        with database.get_db_connection() as conn:
            from src.core.zeus_finance import get_zeus_bankroll
            from src.core.prisma_finance import get_prisma_bankroll
            
            br_zeus = get_zeus_bankroll(conn=conn)
            br_prisma = get_prisma_bankroll()

        if selections_prisma:
            table_prisma = create_table(
                ["Match", "Pred.", "Base"],
                title=f"PRISMA x GEMINI - ANALYSE J{journee_prediction}",
            )
            for p in selections_prisma:
                table_prisma.add_row(
                    f"{p['equipe_dom']} vs {p['equipe_ext']}",
                    f"[bold]{p['prediction']}[/]",
                    f"{p['score_base']:.1f}",
                )
            console.print(table_prisma)

            # --- Affichage du Pari Combiné (Combo) ---
            try:
                active_session = intelligence.get_cached_active_session()
                with database.get_db_connection() as conn:
                    cursor = conn.cursor()
                    cursor.execute(
                        """
                        SELECT id, cote_totale, mise_ar
                        FROM pari_multiple
                        WHERE session_id = %s AND journee = %s
                        ORDER BY id DESC LIMIT 1""",
                        (active_session["id"], journee_prediction),
                    )
                    combo = cursor.fetchone()
                    if combo:
                        gain_pot = int(combo["mise_ar"] * combo["cote_totale"])
                        combo_text = f"[bold white]Matches:[/] {len(selections_prisma[:config.MAX_COMBINED_MATCHES])}  "
                        combo_text += f"[bold white]Cote:[/] [bold yellow]{combo['cote_totale']:.2f}[/]  "
                        combo_text += f"[bold white]Mise:[/] {combo['mise_ar']:,} Ar  "
                        combo_text += f"[bold white]Gain Potentiel:[/] [bold green]{gain_pot:,} Ar[/]"
                        console.print(create_panel(combo_text, title="🔥 PARI COMBINÉ PRISMA", style="orange3"))
            except Exception as e:
                logger.warning(f"Impossible d'afficher le combo : {e}")

        if selections_zeus:
            print_success(f"Analyses ZEUS terminees pour J{journee_prediction}")
            table = create_table(
                ["Match", "PRISMA Conf.", "ZEUS Decision", "Mise (Ar)"],
                title=f"GODMOD x ZEUS - STRATEGIE J{journee_prediction}",
            )
            for z_sel in selections_zeus:
                match_name = f"{z_sel['equipe_dom']} vs {z_sel['equipe_ext']}"
                p_sel = prisma_map.get(match_name)
                if p_sel:
                    fiabilite = p_sel.get("fiabilite", 0)
                    fiab_str = f"{fiabilite:.1f}%"
                    pred_type = p_sel.get("prediction", "?")
                    fiab_str = (
                        f"[bold green]{pred_type} ({fiab_str})[/]"
                        if fiabilite >= 75
                        else f"[green]{pred_type} ({fiab_str})[/]"
                    )
                else:
                    fiab_str = "[dim]N/A (Rejet)[/]"
                decision_zeus = z_sel["decision_formatee"]
                mise_str = f"{z_sel['mise_ar']:,} Ar" if z_sel["pari_type"] != "Aucun" else "-"
                table.add_row(match_name, fiab_str, decision_zeus, mise_str)
            console.print(table)
            console.print(f"   [bold white]Portefeuille [green]ZEUS[/]   :[/][bold green] {br_zeus:,} Ar[/]")
            console.print(f"   [bold white]Portefeuille [magenta]PRISMA[/] :[/][bold magenta] {br_prisma:,} Ar[/]")
        else:
            print_warning(f"Aucune analyse ZEUS disponible pour J{journee_prediction}")

        from src.core.prisma_finance import is_prisma_stop_loss_active

        if is_prisma_stop_loss_active() or br_zeus < config.BANKROLL_STOP_LOSS:
            console.print()
            console.print(
                create_panel(
                    f"[bold red]MODE RECHERCHE DE FONDS[/]\n[white]Bankroll sous le seuil critique de "
                    f"{config.BANKROLL_STOP_LOSS} Ar.\n"
                    f"Toutes les prises de paris sont automatiquement bloquées pour protéger le capital.[/]",
                    title="[WARN] STOP-LOSS ACTIF",
                    style="red",
                )
            )

    except Exception as e:
        logger.error(f"Erreur dans callback IA : {e}", exc_info=True)
        console.print_exception()
    console.print()
    print_info(f"CYCLE J{journee} TERMINE - En attente de J{journee+1}...")



def toggle_verbose_mode():
    """Bascule entre mode simple and mode complet"""
    current_verbose = is_verbose()
    new_verbose = not current_verbose

    set_verbose_mode(new_verbose)
    config.VERBOSE_MODE = new_verbose

    if new_verbose:
        logging.getLogger().setLevel(logging.INFO)
        console.print()
        console.print(
            create_panel("[bold green]Mode Complet (Verbose) ACTIVÉ[/]", title="[V] MODE CHANGÉ", style="green")
        )
    else:
        logging.getLogger().setLevel(logging.WARNING)
        console.print()
        console.print(create_panel("[bold yellow]Mode simple activé[/]", title="[V] MODE CHANGÉ", style="yellow"))


def listen_for_commands():
    """Écoute les touches 'v' et 'x' pour les actions du système (si disponible)"""
    if not KEYBOARD_AVAILABLE:
        return

    while True:
        try:
            import keyboard
            if keyboard.is_pressed("v"):
                toggle_verbose_mode()
                time.sleep(1)  # Éviter les déclenchements multiples
            elif keyboard.is_pressed("x"):
                # Forcer le mode simple avec 'x'
                if is_verbose():
                    set_verbose_mode(False)
                    config.VERBOSE_MODE = False
                    console.print(
                        create_panel("[bold yellow]Mode simple activé[/]", title="[X] MODE SIMPLE", style="yellow")
                    )
                time.sleep(1)  # Éviter les déclenchements multiples
        except KeyboardInterrupt:
            break
        except Exception:
            time.sleep(0.5)
        time.sleep(0.1)


def setup_logging_mode():
    """Configure le mode simple par défaut and démarre l'écoute clavier si possible"""
    # Mode simple par défaut
    set_verbose_mode(False)
    config.VERBOSE_MODE = False
    logging.getLogger().setLevel(logging.WARNING)

    # Démarrer l'écoute des touches en arrière-plan (seulement si disponible)
    if KEYBOARD_AVAILABLE:
        listener_thread = threading.Thread(target=listen_for_commands, daemon=True)
        listener_thread.start()
        print_success("Mode Simple activé par défaut (appuyez sur 'v' pour basculer, 'x' pour mode simple)")
    else:
        print_info("Mode Headless détecté (Clavier non disponible)")


# L'audit automatique par thread a été remplacé par des déclencheurs
# basés sur les journées (J12, J24, J37) dans callback_predictions_ia.


def main():
    api_port = config.API_PORT
    api_host = config.API_HOST

    # Prompt for verbose mode before anything else
    setup_logging_mode()

    welcome_text = Text()
    welcome_text.append("GODMOD V2 - SYSTEME AUTONOME (API)\n", style="bold gold3")
    welcome_text.append("Mode: Surveillance API Temps Reel\n", style="white")
    if is_verbose():
        welcome_text.append("Affichage: Complet (Verbose)\n", style="dim cyan")
    else:
        welcome_text.append("Affichage: Simple\n", style="dim cyan")
    welcome_text.append("Intervalle: 15 secondes\n", style="dim white")
    welcome_text.append("Status: Detection automatique active", style="green")

    console.print(create_panel(welcome_text, title="GODMOD INTELLIGENCE", subtitle="v2.1", style="gold3"))
    print_step("Initialisation du systeme")
    print_info("Initialisation de la base de données...")
    print_info("Base de données: PostgreSQL")

    try:
        database.initialiser_db()
        print_success("Base de données initialisée avec succès")
    except Exception as e:
        print_error(f"Erreur initialisation DB: {e}")
        print_warning("Assurez-vous que PostgreSQL est running et que .env est configuré")
        return

    print_step("Validation des paris en attente (demarrage)")
    try:
        intelligence.mettre_a_jour_scoring()
        print_success("Paris en attente valides au demarrage")
        # Vérification rapide pour l'entraînement asynchrone
        if intelligence.check_training_needs():
            print_info("Entraînement ML requis, lancement en arrière-plan...")
    except Exception as e:
        logger.warning(f"Validation demarrage non bloquante : {e}")
    
    # Audit automatique activé par cycles de journées (J12, J24, J37)
    print_success("Système d'audit stratégique initialisé (J12, J24, J37)")
    
    print_step(f"Demarrage de l'API FastAPI sur {api_host}:{api_port}")
    start_api_server(api_host, api_port)
    print_success("API disponible pour le frontend mobile")
    console.print()
    print_step("Demarrage du cycle de surveillance")
    print_info("Laissez cette fenetre ouverte pour le traitement automatique")
    console.print(Panel("[START] En attente de nouvelles donnees...", style="blue", width=50))
    try:
        start_monitoring(callback_on_new_journee=callback_predictions_ia, verbose=False)
    except KeyboardInterrupt:
        console.print()
        print_warning("Arret du systeme demande par l'utilisateur")
        logger.info("Arret par utilisateur (KeyboardInterrupt)")
    except Exception as e:
        logger.error(f"Erreur non geree dans main : {e}", exc_info=True)
        print_error(f"Erreur critique du systeme : {e}")
    finally:
        console.print("[bold red][EXIT][/] Fermeture du programme.")
        time.sleep(1)


if __name__ == "__main__":
    main()
