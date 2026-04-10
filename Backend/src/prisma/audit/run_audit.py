"""
PRISMA Intelligence++ - Script d'initialisation et d'audit
Script principal pour lancer l'audit statistique et configurer le nouveau système.
"""

import logging
import sys
import os

# Ajouter le path du projet
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from src.core.db.database import get_db_connection
from prisma.audit.generator_audit import run_audit_report

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


def run_initial_audit():
    """Exécute l'audit statistique initial du système."""
    logger.info("=" * 80)
    logger.info("PRISMA INTELLIGENCE++ - AUDIT STATISTIQUE INITIAL")
    logger.info("=" * 80)
    
    try:
        with get_db_connection() as conn:
            # Exécuter l'audit complet
            report = run_audit_report(
                conn, 
                output_path='audit_results.json'
            )
            
            # Afficher le rapport
            print("\n" + report)
            
            logger.info("=" * 80)
            logger.info("Audit terminé avec succès!")
            logger.info("Résultats sauvegardés dans: audit_results.json")
            logger.info("=" * 80)
            
            return True
            
    except Exception as e:
        logger.error(f"Erreur lors de l'audit: {e}", exc_info=True)
        return False


def check_system_status():
    """Vérifie le statut du système PRISMA."""
    logger.info("Vérification du statut du système...")
    
    try:
        from prisma.models import xgboost_model, catboost_model, lightgbm_model, ensemble
        
        status = {
            'xgboost_ready': xgboost_model.is_model_ready(),
            'catboost_ready': catboost_model.is_model_ready(),
            'lightgbm_ready': lightgbm_model.is_model_ready(),
        }
        
        # Obtenir info ensemble
        ensemble_info = ensemble.get_ensemble_info()
        
        logger.info("=" * 60)
        logger.info("STATUT DU SYSTÈME PRISMA")
        logger.info("=" * 60)
        
        for model, ready in status.items():
            status_icon = "✅" if ready else "❌"
            logger.info(f"{status_icon} {model.upper()}: {'Prêt' if ready else 'Non entraîné'}")
        
        logger.info(f"Ensemble actif: {'Oui' if ensemble_info.get('ensemble_active') else 'Non'}")
        logger.info(f"Meta-learner: {'Actif' if ensemble_info.get('meta_learner_active') else 'Inactif'}")
        logger.info("=" * 60)
        
        return status
        
    except Exception as e:
        logger.error(f"Erreur vérification statut: {e}")
        return {}


def print_next_steps():
    """Affiche les prochaines étapes recommandées."""
    print("""
╔══════════════════════════════════════════════════════════════════════════╗
║                     PROCHAINES ÉTAPES RECOMMANDÉES                        ║
╠══════════════════════════════════════════════════════════════════════════╣
║                                                                          ║
║  1. ANALYSER LE RAPPORT D'AUDIT                                          ║
║     → Vérifier la corrélation cotes/résultats                            ║
║     → Identifier les features candidates HIGH priority                   ║
║                                                                          ║
║  2. ENTRAÎNER LES MODÈLES                                                ║
║     → Lancer l'entraînement de l'ensemble (XGB + CAT + LGB)             ║
║     → Le meta-learner sera automatiquement entraîné                    ║
║                                                                          ║
║  3. TESTER LE SYSTÈME                                                    ║
║     → Vérifier que tous les modèles sont prêts                          ║
║     → Tester quelques prédictions avec le nouveau système               ║
║                                                                          ║
╚══════════════════════════════════════════════════════════════════════════╝

Commandes utiles:
  - Audit:     python -m prisma.run_audit
  - Training:  (depuis le code) ensemble.train_ensemble(conn)
  - Status:    python -m prisma.run_audit --status
""")


if __name__ == "__main__":
    import argparse
    
    parser = argparse.ArgumentParser(description="PRISMA Intelligence++ - Audit et initialisation")
    parser.add_argument('--status', action='store_true', help='Vérifier le statut du système')
    parser.add_argument('--audit-only', action='store_true', help='Exécuter uniquement l\'audit')
    
    args = parser.parse_args()
    
    if args.status:
        check_system_status()
    elif args.audit_only:
        run_initial_audit()
    else:
        # Exécution par défaut: audit + statut + prochaines étapes
        run_initial_audit()
        print("\n")
        check_system_status()
        print_next_steps()
