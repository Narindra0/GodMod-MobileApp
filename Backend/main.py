import logging
import sys
import os
import time
import threading
import keyboard
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)
from src.core import config
from src.core import database
from src.analysis import intelligence
from src.api.api_monitor import start_monitoring
from src.core.console import console, print_step, print_success, print_error, print_info, print_warning, create_panel, create_table, Text, Panel, set_verbose_mode, is_verbose, print_verbose
from src.api.server import start_api_server
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
        if config.USE_SELECTION_AMELIOREE:
            print_verbose("   [dim][SHIELD] Mode: PRISMA Complete (Phase 3 - 7 facteurs)[/]")
            selections_prisma = intelligence.selectionner_meilleurs_matchs_ameliore(journee_prediction)
        else:
            print_verbose("   [dim][SHIELD] Mode: PRISMA Standard[/]")
            selections_prisma = intelligence.selectionner_meilleurs_matchs(journee_prediction)
        print_verbose("   [dim][BANK] Mode: ZEUS RL (Autonomous Agent)[/]")
        selections_zeus = intelligence.obtenir_predictions_zeus_journee(journee_prediction)
        prisma_map = {f"{s['equipe_dom']} vs {s['equipe_ext']}": s for s in selections_prisma}
        
        # Initialiser bankroll par défaut
        bankroll = 20000
        
        if selections_zeus:
            print_success(f"Analyses terminees pour J{journee_prediction}")
            table = create_table(["Match", "PRISMA Conf.", "ZEUS Decision", "Mise (Ar)"], title=f"GODMOD x ZEUS - STRATEGIE J{journee_prediction}")
            for z_sel in selections_zeus:
                match_name = f"{z_sel['equipe_dom']} vs {z_sel['equipe_ext']}"
                p_sel = prisma_map.get(match_name)
                if p_sel:
                    fiabilite = p_sel.get('fiabilite', 0)
                    fiab_str = f"{fiabilite:.1f}%"
                    pred_type = p_sel.get('prediction', '?')
                    fiab_str = f"[bold green]{pred_type} ({fiab_str})[/]" if fiabilite >= 75 else f"[green]{pred_type} ({fiab_str})[/]"
                else:
                    fiab_str = "[dim]N/A (Rejet)[/]"
                decision_zeus = z_sel['decision_formatee']
                mise_str = f"{z_sel['mise_ar']:,} Ar" if z_sel['pari_type'] != 'Aucun' else "-"
                table.add_row(
                    match_name,
                    fiab_str,
                    decision_zeus,
                    mise_str
                )
            console.print(table)
            with database.get_db_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("SELECT bankroll_apres FROM historique_paris WHERE strategie = 'ZEUS' ORDER BY id_pari DESC LIMIT 1")
                row = cursor.fetchone()
                bankroll = row[0] if row else 20000
                console.print(f"   [bold white]Bankroll ZEUS estimé :[/] [bold green]{bankroll:,} Ar[/]")
        else:
            print_warning(f"Aucune analyse ZEUS disponible pour J{journee_prediction}")
            
        from src.core.prisma_finance import is_prisma_stop_loss_active
        if is_prisma_stop_loss_active() or bankroll < config.BANKROLL_STOP_LOSS:
            console.print()
            console.print(create_panel(
                f"[bold red]MODE RECHERCHE DE FONDS[/]\n[white]Bankroll sous le seuil critique de {config.BANKROLL_STOP_LOSS} Ar.\nToutes les prises de paris sont automatiquement bloquées pour protéger le capital.[/]",
                title="[WARN] STOP-LOSS ACTIF",
                style="red"
            ))
            
    except Exception as e:
        logger.error(f"Erreur dans callback IA : {e}", exc_info=True)
        console.print_exception()
    console.print()
    print_info(f"CYCLE J{journee} TERMINE - En attente de J{journee+1}...")
def reset_database():
    """Vide toutes les tables de la base de données sauf la table equipes"""
    try:
        # Demander confirmation
        console.print()
        console.print(create_panel(
            "[bold red]⚠️  ATTENTION - RESET BASE DE DONNÉES ⚠️[/]\n\n"
            "[white]Cette action va supprimer TOUTES les données sauf les équipes :\n"
            "[dim]- Sessions, matchs, classements, predictions\n"
            "- Historique des paris, paris multiples\n\n"
            "[bold yellow]Cette action est IRRÉVERSIBLE ![/]\n\n"
            "[white]Pour confirmer, tapez : [bold green]RESET[/]\n"
            "Pour annuler, appuyez sur Entrée[/]",
            title="[R] CONFIRMATION REQUise",
            style="red"
        ))
        
        confirmation = input("Confirmer (RESET) : ").strip().upper()
        
        if confirmation != "RESET":
            console.print(create_panel(
                "[bold yellow]Opération ANNULÉE[/]",
                title="[R] RESET ANNULÉ",
                style="yellow"
            ))
            return
        
        # Exécuter le reset
        print_step("Réinitialisation de la base de données...")
        
        with database.get_db_connection(write=True) as conn:
            cursor = conn.cursor()
            
            # Lister des tables à vider (dans le bon ordre pour respecter les foreign keys)
            tables_to_clear = [
                'pari_multiple_items',
                'pari_multiple', 
                'historique_paris',
                'predictions',
                'classement',
                'matches',
                'sessions'
            ]
            
            deleted_counts = {}
            
            for table in tables_to_clear:
                # Compter avant suppression
                cursor.execute(f"SELECT COUNT(*) FROM {table}")
                count_before = cursor.fetchone()[0]
                
                # Supprimer toutes les données
                cursor.execute(f"DELETE FROM {table}")
                
                deleted_counts[table] = count_before
            
            # Vérifier que la table equipes est intacte
            cursor.execute("SELECT COUNT(*) FROM equipes")
            equipes_count = cursor.fetchone()[0]
            
            conn.commit()
        
        # Afficher le rapport
        console.print()
        console.print(create_panel(
            "[bold green]✅ Base de données réinitialisée avec succès ![/]",
            title="[R] RESET TERMINÉ",
            style="green"
        ))
        
        table = create_table(["Table", "Lignes supprimées"], title="Rapport de suppression")
        total_deleted = 0
        for table_name, count in deleted_counts.items():
            table.add_row(table_name, str(count))
            total_deleted += count
        
        table.add_row("equipes (préservées)", f"[bold green]{equipes_count}[/]")
        table.add_row("[bold]TOTAL[/]", f"[bold red]{total_deleted}[/]")
        
        console.print(table)
        console.print(f"[dim]📊 {total_deleted} lignes supprimées, {equipes_count} équipes préservées[/]")
        
        logger.info(f"Base de données réinitialisée: {total_deleted} lignes supprimées, {equipes_count} équipes préservées")
        
    except Exception as e:
        logger.error(f"Erreur lors du reset de la base de données: {e}", exc_info=True)
        console.print(create_panel(
            f"[bold red]❌ Erreur critique : {e}[/]",
            title="[R] ERREUR RESET",
            style="red"
        ))
        console.print_exception()

def toggle_verbose_mode():
    """Bascule entre mode simple et mode complet"""
    current_verbose = is_verbose()
    new_verbose = not current_verbose
    
    set_verbose_mode(new_verbose)
    config.VERBOSE_MODE = new_verbose
    
    if new_verbose:
        logging.getLogger().setLevel(logging.INFO)
        console.print()
        console.print(create_panel(
            "[bold green]Mode Complet (Verbose) ACTIVÉ[/]",
            title="[V] MODE CHANGÉ",
            style="green"
        ))
    else:
        logging.getLogger().setLevel(logging.WARNING)
        console.print()
        console.print(create_panel(
            "[bold yellow]Mode Simple ACTIVÉ[/]",
            title="[V] MODE CHANGÉ", 
            style="yellow"
        ))

def listen_for_toggle():
    """Écoute les touches 'v', 'x' et 'r' pour les actions du système"""
    while True:
        try:
            if keyboard.is_pressed('v'):
                toggle_verbose_mode()
                time.sleep(1)  # Éviter les déclenchements multiples
            elif keyboard.is_pressed('x'):
                # Forcer le mode simple avec 'x'
                if is_verbose():
                    set_verbose_mode(False)
                    config.VERBOSE_MODE = False
                    logging.getLogger().setLevel(logging.WARNING)
                    console.print()
                    console.print(create_panel(
                        "[bold yellow]Mode Simple ACTIVÉ[/]",
                        title="[X] MODE SIMPLE",
                        style="yellow"
                    ))
                time.sleep(1)  # Éviter les déclenchements multiples
            elif keyboard.is_pressed('r'):
                reset_database()
                time.sleep(2)  # Délai plus long pour éviter les déclenchements multiples
        except:
            break
        time.sleep(0.1)

def setup_logging_mode():
    """Configure le mode simple par défaut et démarre l'écoute de la touche 'v'"""
    # Mode simple par défaut
    set_verbose_mode(False)
    config.VERBOSE_MODE = False
    logging.getLogger().setLevel(logging.WARNING)
    
    # Démarrer l'écoute de la touche 'v' en arrière-plan
    listener_thread = threading.Thread(target=listen_for_toggle, daemon=True)
    listener_thread.start()
    
    print_success("Mode Simple activé par défaut (appuyez sur 'v' pour basculer, 'x' pour mode simple, 'r' pour reset DB)")

def main():
    api_port = int(os.getenv("API_PORT", "8000"))
    api_host = os.getenv("API_HOST", "127.0.0.1")
    
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
    
    console.print(create_panel(
        welcome_text, 
        title="GODMOD INTELLIGENCE", 
        subtitle="v2.1",
        style="gold3"
    ))
    print_step("Initialisation du systeme")
    console.print("[dim]Verification de la connexion base de donnees...[/]")
    try:
        database.initialiser_db()
        print_success("Base de donnees connectee et synchronisee")
    except Exception as e:
        logger.error(f"Erreur initialisation BDD : {e}", exc_info=True)
        print_error(f"Echec critique BDD : {e}")
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
        start_monitoring(
            callback_on_new_journee=callback_predictions_ia,
            verbose=False
        )
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
