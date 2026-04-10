"""
PRISMA Intelligence++ - Master Orchestrator
Script principal pour orchestrer tout le système amélioré.
Intègre audit, entraînement, validation, feedback et monitoring.
"""

import logging
import sys
import os
from datetime import datetime
from typing import Dict, List, Optional, Any

if __name__ == '__main__':
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from core.database import get_db_connection
from core.session_manager import get_active_session

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


class PrismaIntelligenceOrchestrator:
    """
    Orchestrateur principal du système PRISMA Intelligence++.
    Coordonne tous les modules pour une exécution fluide.
    """
    
    def __init__(self, conn, force_training: bool = False):
        self.conn = conn
        self.session = get_active_session(conn)
        self.session_id = self.session['id'] if self.session else None
        self.results = {}
        self.force_training = force_training
        
    def run_full_pipeline(self, steps: list = None) -> dict:
        """
        Exécute le pipeline complet PRISMA Intelligence++.
        
        Args:
            steps: Liste des étapes à exécuter ['audit', 'train', 'validate', 'feedback', 'monitor']
                  Si None, exécute toutes les étapes.
        
        Returns:
            Dict avec tous les résultats
        """
        if steps is None:
            steps = ['audit', 'train', 'validate', 'feedback', 'monitor']
        
        if not self.session_id:
            logger.error("❌ Aucune session active trouvée!")
            return {'error': 'no_active_session'}
        
        logger.info("=" * 80)
        logger.info("🚀 PRISMA INTELLIGENCE++ - FULL PIPELINE EXECUTION")
        logger.info(f"📅 Session: {self.session_id}, Journée: {self.session.get('current_day', 'N/A')}")
        logger.info(f"📋 Steps: {', '.join(steps)}")
        logger.info("=" * 80)
        
        start_time = datetime.now()
        
        # Étape 1: Audit
        if 'audit' in steps:
            self._run_audit()
        
        # Étape 2: Entraînement
        if 'train' in steps:
            self._run_training()
        
        # Étape 3: Validation
        if 'validate' in steps:
            self._run_validation()
        
        # Étape 4: Feedback
        if 'feedback' in steps:
            self._run_feedback()
        
        # Étape 5: Monitoring
        if 'monitor' in steps:
            self._run_monitoring()
        
        end_time = datetime.now()
        duration = (end_time - start_time).total_seconds()
        
        logger.info("=" * 80)
        logger.info(f"✅ PIPELINE TERMINÉ en {duration:.1f}s")
        logger.info("=" * 80)
        
        return self.results
    
    def _run_audit(self):
        """Exécute l'audit statistique."""
        logger.info("\n📊 ÉTAPE 1: AUDIT STATISTIQUE")
        logger.info("-" * 40)
        
        try:
            from prisma.generator_audit import run_audit_report
            report = run_audit_report(self.conn, 'audit_results.json')
            self.results[ 'audit' ] = { 'status': 'success' if report else 'failed' }
            logger.info("✅ Audit terminé")
        except Exception as e:
            logger.error(f"❌ Erreur audit: {e}")
            self.results[ 'audit' ] = { 'status': 'error', 'error': str(e) }

    def _run_training(self):
        """Exécute l'entraînement des modèles."""
        logger.info("\n🤖 ÉTAPE 2: ENTRAÎNEMENT DES MODÈLES (ENSEMBLE)")
        logger.info("-" * 40)
        
        try:
            from prisma.ensemble import train_ensemble
            # Forcer l'entraînement si demandé (ex: transition de session)
            success = train_ensemble(self.conn, force=self.force_training)
            self.results[ 'training' ] = { 'status': 'success' if success else 'failed' }
            if success:
                logger.info("✅ Entraînement terminé avec succès")
            else:
                logger.warning("⚠️ Entraînement terminé avec des avertissements")
        except Exception as e:
            logger.error(f"❌ Erreur entraînement: {e}")
            self.results[ 'training' ] = { 'status': 'error', 'error': str(e) }

    def _run_validation(self):
        """Exécute la validation (Back-test)."""
        logger.info("\n🧪 ÉTAPE 3: VALIDATION")
        logger.info("-" * 40)
        
        try:
            from prisma.validation_framework import run_validation_suite
            # Back-test sur les 2 dernières sessions
            val_results = run_validation_suite(self.conn, sessions_count=2)
            self.results[ 'validation' ] = { 'status': 'success' if val_results else 'failed' }
            logger.info("✅ Validation terminée")
        except Exception as e:
            logger.error(f"❌ Erreur validation: {e}")
            self.results[ 'validation' ] = { 'status': 'error', 'error': str(e) }

    def _run_feedback(self):
        """Exécute la boucle de feedback."""
        logger.info("\n🔄 ÉTAPE 4: FEEDBACK LOOP")
        logger.info("-" * 40)
        
        try:
            from prisma.feedback_loop import run_feedback_analysis
            feedback = run_feedback_analysis(self.conn, self.session_id)
            self.results[ 'feedback' ] = { 'status': 'success' if feedback else 'failed' }
            logger.info("✅ Feedback analysé")
        except Exception as e:
            logger.error(f"❌ Erreur feedback: {e}")
            self.results[ 'feedback' ] = { 'status': 'error', 'error': str(e) }

    def _run_monitoring(self):
        """Exécute le monitoring final."""
        logger.info("\n📈 ÉTAPE 5: MONITORING")
        logger.info("-" * 40)
        
        try:
            from prisma.monitoring import run_monitoring_check
            mon_results = run_monitoring_check(self.conn, self.session_id)
            self.results[ 'monitoring' ] = { 'status': 'success' if mon_results else 'failed' }
            logger.info("✅ Monitoring effectué")
        except Exception as e:
            logger.error(f"❌ Erreur monitoring: {e}")
            self.results[ 'monitoring' ] = { 'status': 'error', 'error': str(e) }

    def generate_final_report(self):
        """Génère un rapport textuel des résultats."""
        report = f"""
╔══════════════════════════════════════════════════════════════════╗
║         RAPPORT FINAL - PRISMA INTELLIGENCE++                    ║
║         {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}                              ║
╚══════════════════════════════════════════════════════════════════╝

📊 RÉSULTATS PAR ÉTAPE:
"""
        for step, res in self.results.items():
            status = "✅ success" if res['status'] == 'success' else f"❌ {res['status']}"
            report += f"  {status.upper()}: {step.upper()}\n"
            
        report += "\n🎯 PROCHAINES ACTIONS RECOMMANDÉES:\n"
        if all(res['status'] == 'success' for res in self.results.values()):
            report += "  • Système optimal - continuer surveillance\n"
        else:
            report += "  • Vérifier les logs pour les étapes en erreur\n"
            
        report += "\n═══════════════════════════════════════════════════════════════════\n"
        return report


def main_cli():
    import argparse
    parser = argparse.ArgumentParser(description='PRISMA Intelligence++ Orchestrator')
    parser.add_argument('--steps', nargs='+', choices=['audit', 'train', 'validate', 'feedback', 'monitor'],
                        help='Étapes spécifiques à exécuter')
    parser.add_argument('--verbose', action='store_true', help='Activer mode verbeux')
    
    args = parser.parse_args()
    
    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)
        
    try:
        with get_db_connection(write=True) as conn:
            orchestrator = PrismaIntelligenceOrchestrator(conn)
            results = orchestrator.run_full_pipeline(steps=args.steps)
            
            # Sauvegarder résultats
            with open('prisma_pipeline_results.json', 'w') as f:
                import json
                json.dump(results, f, indent=2, default=str)
                
            print(orchestrator.generate_final_report())
            
    except Exception as e:
        print(f"❌ Erreur critique: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main_cli()
