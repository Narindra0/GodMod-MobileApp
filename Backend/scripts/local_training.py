"""
Script d'entraînement PRISMA en local
Usage: python scripts/local_training.py [--force] [--steps train,validate,feedback]

Ce script :
1. Se connecte à la base de données (Neon ou locale)
2. Lance l'entraînement complet des modèles PRISMA
3. Affiche la progression en temps réel
4. Sauvegarde les modèles entraînés
"""

import sys
import os
import argparse
import time
import json
from datetime import datetime

# Ajouter le répertoire parent au path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from src.core.database import get_db_connection
from src.core.session_manager import get_active_session
from src.prisma.orchestrator import PrismaIntelligenceOrchestrator
from src.prisma.training_status import status_manager


def print_progress():
    """Affiche la progression actuelle de l'entraînement"""
    status = status_manager.get_status()
    print(f"\n{'='*60}")
    print(f"Status: {'🟢 ENTRAÎNEMENT' if status['is_training'] else '🔴 STOP'}")
    print(f"Progression: {status['progress']}%")
    print(f"Étape: {status['step_description']}")
    print(f"\nModèles:")
    for model, data in status['models_progress'].items():
        emoji = {'training': '⏳', 'completed': '✅', 'pending': '⏸️', 'failed': '❌'}.get(data['status'], '❓')
        acc = f" (CV: {data['accuracy']*100:.2f}%)" if data['accuracy'] > 0 else ""
        print(f"  {emoji} {model.upper()}: {data['progress']}% - {data['status']}{acc}")
    
    if status['logs']:
        print(f"\nDerniers logs:")
        for log in status['logs'][-5:]:
            print(f"  {log}")
    print(f"{'='*60}\n")


def monitor_training():
    """Surveille l'entraînement jusqu'à la fin"""
    print("📊 Surveillance de l'entraînement...")
    last_progress = -1
    
    while True:
        status = status_manager.get_status()
        
        # Afficher si changement de progression
        if status['progress'] != last_progress:
            print_progress()
            last_progress = status['progress']
        
        # Vérifier si terminé
        if not status['is_training'] and status['progress'] >= 100:
            print("\n🎉 ENTRAÎNEMENT TERMINÉ !")
            print_progress()
            break
        
        # Vérifier si erreur
        if not status['is_training'] and status['progress'] == 0:
            print("\n⚠️ L'entraînement semble avoir échoué ou ne pas avoir démarré")
            print_progress()
            break
        
        time.sleep(2)


def run_local_training(force=True, steps=None, monitor=True):
    """
    Lance l'entraînement PRISMA en local
    
    Args:
        force: Force l'entraînement même si pas de trigger
        steps: Liste des étapes ['train', 'validate', 'feedback'] ou None pour toutes
        monitor: Si True, surveille l'entraînement en temps réel
    
    Returns:
        dict: Résultats de l'entraînement
    """
    print("🚀 Démarrage de l'entraînement PRISMA en local")
    print(f"⏰ {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"⚙️  Force: {force}, Steps: {steps or 'toutes'}")
    print()
    
    try:
        # Vérifier la connexion DB
        print("📡 Connexion à la base de données...")
        with get_db_connection() as conn:
            session = get_active_session(conn)
            if not session:
                print("❌ Erreur: Aucune session active trouvée!")
                return {'error': 'no_active_session'}
            
            print(f"✅ Session active: ID={session['id']}, Journée={session.get('current_day', 'N/A')}")
            print()
        
        # Lancer l'entraînement
        print("🏋️  Lancement de l'entraînement...")
        print("-" * 60)
        
        with get_db_connection(write=True) as conn:
            orchestrator = PrismaIntelligenceOrchestrator(conn, force_training=force)
            
            if monitor:
                # Lancer le monitoring dans un thread séparé
                import threading
                monitor_thread = threading.Thread(target=monitor_training, daemon=True)
                monitor_thread.start()
            
            # Lancer le pipeline
            results = orchestrator.run_full_pipeline(steps=steps)
            
            if monitor:
                # Attendre la fin du monitoring
                monitor_thread.join(timeout=5)
        
        print("\n" + "=" * 60)
        print("📊 RÉSULTATS:")
        print(json.dumps(results, indent=2, default=str))
        print("=" * 60)
        
        return results
        
    except Exception as e:
        print(f"\n❌ Erreur critique: {e}")
        import traceback
        traceback.print_exc()
        return {'error': str(e)}


def export_models_info():
    """Exporte les informations des modèles entraînés"""
    print("\n📦 Informations des modèles:")
    
    models_dir = os.path.join(os.path.dirname(__file__), '..', 'models', 'prisma')
    
    for model_file in ['xgboost_model.json', 'xgboost_metadata.json', 
                       'catboost_model.cbm', 'catboost_metadata.json']:
        path = os.path.join(models_dir, model_file)
        if os.path.exists(path):
            size = os.path.getsize(path)
            print(f"  ✅ {model_file}: {size:,} bytes")
            
            # Afficher métadonnées si JSON
            if model_file.endswith('_metadata.json'):
                try:
                    with open(path, 'r') as f:
                        meta = json.load(f)
                        if 'cv_accuracy' in meta:
                            print(f"     └─ CV Accuracy: {meta['cv_accuracy']*100:.2f}%")
                        if 'last_training_session' in meta:
                            print(f"     └─ Session: {meta['last_training_session']}")
                except:
                    pass
        else:
            print(f"  ❌ {model_file}: Introuvable")


def main():
    parser = argparse.ArgumentParser(description='Entraînement PRISMA en local')
    parser.add_argument('--force', action='store_true', 
                        help='Force l\'entraînement même sans trigger')
    parser.add_argument('--steps', type=str, default='train,validate,feedback',
                        help='Étapes à exécuter (défaut: train,validate,feedback)')
    parser.add_argument('--no-monitor', action='store_true',
                        help='Désactive la surveillance en temps réel')
    parser.add_argument('--info-only', action='store_true',
                        help='Affiche uniquement les infos des modèles existants')
    
    args = parser.parse_args()
    
    if args.info_only:
        export_models_info()
        return
    
    # Parser les étapes
    steps = args.steps.split(',') if args.steps else None
    
    # Lancer l'entraînement
    results = run_local_training(
        force=args.force,
        steps=steps,
        monitor=not args.no_monitor
    )
    
    # Exporter les infos des modèles
    export_models_info()
    
    # Sauvegarder les résultats
    results_file = f"training_results_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
    with open(results_file, 'w') as f:
        json.dump(results, f, indent=2, default=str)
    print(f"\n💾 Résultats sauvegardés dans: {results_file}")


if __name__ == '__main__':
    main()
