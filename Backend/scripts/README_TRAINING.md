# Guide d'entraînement local PRISMA

## Workflow recommandé

### 1. Exporter les données de Neon (si pas déjà fait)

```bash
# Option A: Export via pg_dump (recommandé)
pg_dump "postgresql://user:pass@ep-xxxxx.neon.tech/dbname" > backup_neon.sql

# Option B: Tu as déjà exporté en JSON depuis l'interface Neon
# Les fichiers JSON sont dans le dossier `data/`
```

### 2. Configurer la base de données locale

Option A: **Utiliser Neon directement** (plus simple)
- Le `.env` est déjà configuré pour Neon
- Pas besoin de changer quoi que ce soit

Option B: **Créer une DB PostgreSQL locale** (plus rapide)
```bash
# Créer la base de données
createdb godmod_local

# Modifier .env temporairement
DATABASE_URL=postgresql://localhost:5432/godmod_local
```

### 3. Importer les données (si DB locale)

```bash
# Si tu as un backup SQL
psql godmod_local < backup_neon.sql

# Si tu as des fichiers JSON, utiliser le script d'import
python scripts/import_json_to_db.py data/*.json
```

### 4. Lancer l'entraînement

```bash
# Entraînement complet avec surveillance
python scripts/local_training.py --force

# Entraînement sans surveillance (plus rapide)
python scripts/local_training.py --force --no-monitor

# Entraînement avec étapes spécifiques
python scripts/local_training.py --force --steps train,validate

# Voir les infos des modèles existants
python scripts/local_training.py --info-only
```

### 5. Vérifier les modèles entraînés

```bash
# Liste les modèles et leurs métadonnées
python scripts/local_training.py --info-only
```

Fichiers générés dans `models/prisma/`:
- `xgboost_model.json` (~2.4MB) - Modèle XGBoost
- `xgboost_metadata.json` - Métadonnées (accuracy, features, etc.)
- `catboost_model.cbm` (~1.1MB) - Modèle CatBoost  
- `catboost_metadata.json` - Métadonnées

### 6. Uploader vers Hugging Face Spaces

```bash
# Upload automatique avec rebuild
python scripts/upload_models_hf.py

# Upload sans rebuild
python scripts/upload_models_hf.py --no-rebuild

# Vérifier sans uploader
python scripts/upload_models_hf.py --dry-run
```

### 7. Workflow complet en une commande

```bash
# Entraîner + uploader
python scripts/local_training.py --force && python scripts/upload_models_hf.py
```

---

## Dépannage

### "No active session found"
La base de données est vide ou la session n'existe pas. Importe d'abord les données.

### "is_training reste à false"
L'entraînement peut prendre du temps à démarrer. Attends 1-2 minutes et vérifie les logs.

### Timeout sur HF Spaces
C'est normal, l'entraînement ML prend plusieurs minutes. Utilise l'entraînement local à la place.

### Modèles trop gros pour git
Les modèles sont automatiquement trackés avec Git LFS. Vérifie avec:
```bash
git lfs track
```

---

## Monitoring pendant l'entraînement

Le script affiche automatiquement:
- Progression globale (%)
- Status de chaque modèle (XGBoost, CatBoost, LightGBM)
- Logs en temps réel
- Résultats finaux (accuracy, etc.)

Pour voir le dashboard visuel après upload:
```
https://jacknotdaniel-godmod-backend.hf.space/prisma/dashboard
```
