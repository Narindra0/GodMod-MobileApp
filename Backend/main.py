"""
Systeme GODMOD V2 - Main Script
Mode: API Monitor (Optimise)

Ce script est le point d'entree principal de l'application.
Il utilise le module de surveillance API pour detecter automatiquement 
les nouvelles journees et lancer les analyses.

Version: 2.1
Date: Janvier 2025
"""

import logging
import sys
import os
import time

# Configuration du logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Import des modules du projet
from src.core import config
from src.core import database
from src.analysis import intelligence
from src.api.api_monitor import start_monitoring
from src.core.console import console, print_step, print_success, print_error, print_info, print_warning, create_panel, create_table, Text, Panel

def callback_predictions_ia(journee: int):
    """
    Callback appele automatiquement quand une nouvelle journee est detectee.
    Execute apres la collecte complete des donnees (Resultats + Classement + Cotes).
    
    Args:
        journee: Numero de la journee qui vient d'etre collectee (ex: J15)
    """
    console.print()
    console.print(create_panel(f"[bold]ANALYSE INTELLIGENTE - J{journee}[/]", style="magenta"))
    
    try:
        # 1. Mise a jour du scoring IA (validation des predictions precedentes)
        print_step("Validation des predictions precedentes")
        intelligence.mettre_a_jour_scoring()
        print_success("Score IA mis a jour avec les derniers resultats")
        
        # 2. Determiner la prochaine journee a predire
        journee_prediction = journee + 1
        
        # 3. Verifier si on a atteint le debut des predictions (J10 par defaut)
        if journee_prediction < config.JOURNEE_DEPART_PREDICTION:
            print_info(f"J{journee_prediction} < J{config.JOURNEE_DEPART_PREDICTION} (seuil de demarrage)")
            console.print("[dim]Collecte des donnees uniquement. Pas de predictions.[/]")
            return
        
        # 4. Generation des predictions PRISMA
        print_step(f"Generation predictions pour J{journee_prediction}")
        
        # Choix du mode selon configuration
        if config.USE_SELECTION_AMELIOREE:
            console.print("   [dim]🛡️ Mode: PRISMA Complete (Phase 3 - 7 facteurs)[/]")
            selections_prisma = intelligence.selectionner_meilleurs_matchs_ameliore(journee_prediction)
        else:
            console.print("   [dim]🛡️ Mode: PRISMA Standard[/]")
            selections_prisma = intelligence.selectionner_meilleurs_matchs(journee_prediction)
        
        # 5. Generation des predictions ZEUS
        console.print("   [dim]🏛️ Mode: ZEUS RL (Autonomous Agent)[/]")
        selections_zeus = intelligence.obtenir_predictions_zeus_journee(journee_prediction)
        
        # 6. Affichage des resultats unifies
        # Créer un dictionnaire pour accès rapide par match
        prisma_map = {f"{s['equipe_dom']} vs {s['equipe_ext']}": s for s in selections_prisma}
        
        if selections_zeus:
            print_success(f"Analyses terminees pour J{journee_prediction}")
            
            table = create_table(["Match", "PRISMA Conf.", "ZEUS Decision", "Mise (Ar)"], title=f"GODMOD x ZEUS - STRATEGIE J{journee_prediction}")
            
            for z_sel in selections_zeus:
                match_name = f"{z_sel['equipe_dom']} vs {z_sel['equipe_ext']}"
                p_sel = prisma_map.get(match_name)
                
                # PRISMA Confidence
                if p_sel:
                    fiabilite = p_sel.get('fiabilite', 0)
                    fiab_str = f"{fiabilite:.1f}%"
                    pred_type = p_sel.get('prediction', '?')
                    fiab_str = f"[bold green]{pred_type} ({fiab_str})[/]" if fiabilite >= 75 else f"[green]{pred_type} ({fiab_str})[/]"
                else:
                    fiab_str = "[dim]N/A (Rejet)[/]"
                
                # ZEUS Decision
                decision_zeus = z_sel['decision_formatee']
                mise_str = f"{z_sel['mise_ar']:,} Ar" if z_sel['pari_type'] != 'Aucun' else "-"
                
                table.add_row(
                    match_name,
                    fiab_str,
                    decision_zeus,
                    mise_str
                )
            
            console.print(table)
            
            # Affichage du bankroll estimé de ZEUS
            with database.get_db_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("SELECT bankroll_apres FROM historique_paris WHERE strategie = 'ZEUS' ORDER BY id_pari DESC LIMIT 1")
                row = cursor.fetchone()
                bankroll = row[0] if row else 20000
                console.print(f"   [bold white]Bankroll ZEUS estimé :[/] [bold green]{bankroll:,} Ar[/]")
        else:
            print_warning(f"Aucune analyse ZEUS disponible pour J{journee_prediction}")
        
    except Exception as e:
        logger.error(f"Erreur dans callback IA : {e}", exc_info=True)
        console.print_exception()
    
    console.print()
    print_info(f"CYCLE J{journee} TERMINE - En attente de J{journee+1}...")


def main():
    """
    Fonction principale
    """
    # Imports already done at top level

    # 1. Start Banner
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
    
    # 2. Initialisation BDD
    print_step("Initialisation du systeme")
    console.print("[dim]Verification de la connexion base de donnees...[/]")
    
    try:
        database.initialiser_db()
        print_success("Base de donnees connectee et synchronisee")
    except Exception as e:
        logger.error(f"Erreur initialisation BDD : {e}", exc_info=True)
        print_error(f"Echec critique BDD : {e}")
        return

    # 3. Lancement de la surveillance
    console.print()
    print_step("Demarrage du cycle de surveillance")
    print_info("Laissez cette fenetre ouverte pour le traitement automatique")
    console.print(Panel("🚀 En attente de nouvelles donnees...", style="blue", width=50))
    
    try:
        # Cette fonction contient une boucle infinie qui surveille l'API
        # Elle appellera 'callback_predictions_ia' a chaque nouvelle journee
        start_monitoring(
            callback_on_new_journee=callback_predictions_ia,
            verbose=False  # On gere l'affichage nous-meme maintenant
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
