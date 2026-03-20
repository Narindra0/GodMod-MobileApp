import logging
import threading
import time

import keyboard
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

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

load_dotenv()


def callback_predictions_ia(journee: int):
    console.print()
    console.print(create_panel(f"[bold]ANALYSE INTELLIGENTE - J{journee}[/]", style="magenta"))
    try:
        print_step("Validation des predictions precedentes")
        intelligence.mettre_a_jour_scoring()
        print_success("Score IA mis a jour avec les derniers resultats")
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
            print_step("Analyse IA Booster (Gemini)")
            try:
                active_session = intelligence.get_cached_active_session()
                with database.get_db_connection(write=True) as conn_gen:
                    ai_ok = ai_booster.analyze_and_store_journee(journee_prediction, active_session["id"], conn_gen)
                if ai_ok:
                    print_success("Boosts IA calcules et mis en cache")
                else:
                    print_verbose("   [AI-BOOSTER] Cache deja present ou API ignoree")
            except Exception as ai_err:
                logger.warning(f"[AI-BOOSTER] Erreur batch non-bloquante : {ai_err}")
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

        if selections_prisma:
            table_prisma = create_table(
                ["Match", "Pred.", "Base", "IA Boost", "Final"],
                title=f"PRISMA x GEMINI - ANALYSE J{journee_prediction}",
            )
            for p in selections_prisma:
                boost = p.get("boost_ia", 0.0)
                boost_str = (
                    f"[bold green]{boost:+.1f}[/]"
                    if boost > 0
                    else f"[bold red]{boost:+.1f}[/]" if boost < 0 else "[dim]0.0[/]"
                )
                table_prisma.add_row(
                    f"{p['equipe_dom']} vs {p['equipe_ext']}",
                    f"[bold]{p['prediction']}[/]",
                    f"{p['score_base']:.1f}",
                    boost_str,
                    f"[bold cyan]{p['fiabilite']:.1f}[/]",
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
            with database.get_db_connection() as conn:
                cursor = conn.cursor()
                cursor.execute(
                    "SELECT bankroll_apres FROM historique_paris WHERE strategie = 'ZEUS' ORDER BY id_pari DESC LIMIT 1"
                )
                row = cursor.fetchone()
                bankroll = row["bankroll_apres"] if row else config.DEFAULT_BANKROLL
                console.print(f"   [bold white]Bankroll ZEUS estimé :[/] [bold green]{bankroll:,} Ar[/]")
        else:
            print_warning(f"Aucune analyse ZEUS disponible pour J{journee_prediction}")

        from src.core.prisma_finance import is_prisma_stop_loss_active

        if is_prisma_stop_loss_active() or bankroll < config.BANKROLL_STOP_LOSS:
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


def reset_database_api():
    """Version API de reset_database - utilisée par l'endpoint /admin/reset-data"""
    from src.core.database import get_db_connection

    try:
        with get_db_connection(write=True) as conn:
            cursor = conn.cursor()

            # Lister des tables à vider (dans le bon ordre pour respecter les foreign keys)
            tables_to_clear = [
                "pari_multiple_items",
                "pari_multiple",
                "historique_paris",
                "predictions",
                "classement",
                "matches",
                "sessions",
            ]

            deleted_counts = {}

            for table in tables_to_clear:
                # Compter avant suppression (PostgreSQL utilise des dictionnaires)
                cursor.execute("SELECT COUNT(*) FROM %s", (table,))
                result = cursor.fetchone()
                count_before = result["count"]

                # Supprimer toutes les données
                cursor.execute("DELETE FROM %s", (table,))

                deleted_counts[table] = count_before

            # Vérifier que la table equipes est intacte
            cursor.execute("SELECT COUNT(*) FROM equipes")
            equipes_result = cursor.fetchone()
            equipes_count = equipes_result["count"]

            conn.commit()

        total_deleted = sum(deleted_counts.values())

        logger.info(
            f"Base de données réinitialisée via API: {total_deleted} lignes supprimées, {equipes_count} équipes préservées"
        )

        return {
            "deleted_counts": deleted_counts,
            "total_deleted": total_deleted,
            "preserved_teams": equipes_count,
        }

    except Exception as e:
        logger.error(f"Erreur lors du reset API de la base de données: {e}", exc_info=True)
        raise


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
    """Écoute les touches 'v' et 'x' pour les actions du système"""
    while True:
        try:
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
            time.sleep(0.1)
        except Exception:
            time.sleep(0.1)
        time.sleep(0.1)


def setup_logging_mode():
    """Configure le mode simple par défaut and démarre l'écoute de la touche 'v'"""
    # Mode simple par défaut
    set_verbose_mode(False)
    config.VERBOSE_MODE = False
    logging.getLogger().setLevel(logging.WARNING)

    # Démarrer l'écoute des touches en arrière-plan
    listener_thread = threading.Thread(target=listen_for_commands, daemon=True)
    listener_thread.start()

    print_success("Mode Simple activé par défaut (appuyez sur 'v' pour basculer, 'x' pour mode simple)")


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
    except Exception as e:
        logger.warning(f"Validation demarrage non bloquante : {e}")
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
