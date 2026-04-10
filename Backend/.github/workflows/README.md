# GitHub Actions - PRISMA Training

## Configuration requise

Avant de lancer le workflow, configurez ces secrets dans votre repo GitHub :
(Settings > Secrets and variables > Actions > New repository secret)

### Secrets obligatoires

| Secret | Description | Exemple |
|--------|-------------|---------|
| `DATABASE_URL` | URL de connexion Neon PostgreSQL | `postgresql://user:pass@ep-xxxxx.neon.tech/dbname` |
| `HF_TOKEN` | Token HuggingFace avec perm write | `hf_xxxxx` |
| `HF_SPACE_ID` | ID du HF Space | `jacknotdaniel-godmod-backend` |

### Comment obtenir HF_TOKEN

1. Allez sur https://huggingface.co/settings/tokens
2. Créez un token avec scope `write`
3. Copiez la valeur dans `HF_TOKEN`

### Comment obtenir HF_SPACE_ID

C'est la partie de l'URL après `/spaces/` :
- URL: `https://huggingface.co/spaces/jacknotdaniel-godmod-backend`
- Space ID: `jacknotdaniel-godmod-backend`

## Lancement manuel

1. Allez sur l'onglet **Actions** du repo
2. Sélectionnez **Train PRISMA Models**
3. Cliquez **Run workflow**

## Planification automatique

Le workflow s'exécute automatiquement tous les jours à **2h UTC**.

Pour modifier le créneau, éditez `cron` dans le fichier YAML :
```yaml
schedule:
  - cron: '0 2 * * *'  # 2h UTC = minuit/minuit-1h Europe
```

## Monitoring

- Les logs sont visibles dans l'onglet Actions
- Les modèles sont uploadés comme artifacts (30 jours de rétention)
- Les modèles sont automatiquement pushés vers HF Spaces

## Dépannage

### "No active session found"
La base Neon n'a pas de session active. Créez-en une via l'app.

### "Push failed"
Vérifiez que `HF_TOKEN` a les permissions `write` et que `HF_SPACE_ID` est correct.

### Timeout pendant l'entraînement
Normal si >30 min. Augmentez `timeout-minutes` dans le YAML si nécessaire.
