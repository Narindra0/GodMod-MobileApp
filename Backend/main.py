import logging
import sys
import os
import time
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)
from src.core import config
from src.core import database
from src.analysis import intelligence
from src.api.api_monitor import start_monitoring
from src.core.console import console, print_step, print_success, print_error, print_info, print_warning, create_panel, create_table, Text, Panel
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
            console.print("   [dim]🛡️ Mode: PRISMA Complete (Phase 3 - 7 facteurs)[/]")
            selections_prisma = intelligence.selectionner_meilleurs_matchs_ameliore(journee_prediction)
        else:
            console.print("   [dim]🛡️ Mode: PRISMA Standard[/]")
            selections_prisma = intelligence.selectionner_meilleurs_matchs(journee_prediction)
        console.print("   [dim]🏛️ Mode: ZEUS RL (Autonomous Agent)[/]")
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
                title="⚠️ STOP-LOSS ACTIF",
                style="red"
            ))
            
    except Exception as e:
        logger.error(f"Erreur dans callback IA : {e}", exc_info=True)
        console.print_exception()
    console.print()
    print_info(f"CYCLE J{journee} TERMINE - En attente de J{journee+1}...")
def main():
    api_port = int(os.getenv("API_PORT", "8000"))
    api_host = os.getenv("API_HOST", "127.0.0.1")
    welcome_text = Text()
    welcome_text.append("GODMOD V2 - SYSTEME AUTONOME (API)\n", style="bold gold3")
    welcome_text.append("Mode: Surveillance API Temps Reel\n", style="white")
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
    console.print(Panel("🚀 En attente de nouvelles donnees...", style="blue", width=50))
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
