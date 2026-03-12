# 🏛️ MODULE ZEUS

## Agent de Reinforcement Learning pour Paris Optimisés

ZEUS est le cerveau décisionnel autonome de l'infrastructure GODMOD, utilisant l'apprentissage par renforcement (PPO) pour optimiser une stratégie de paris sur la Ligue Virtuelle.

---

## 🎯 Objectifs

- **Survie du Capital**: Protection stricte contre la banqueroute (< 1 000 Ar = game over)
- **Maximisation des Gains**: Exploitation des inefficiences de marché détectées
- **Décisions Optimales**: 13 actions possibles (abstention + 12 types de paris)

---

## 📦 Installation

### 1. Installer les dépendances

```bash
pip install -r requirements.txt
```

Dépendances ZEUS spécifiques:
- `stable-baselines3>=2.0.0` - Algorithme PPO
- `gymnasium>=0.28.0` - Framework d'environnement RL
- `tensorboard>=2.12.0` - Visualisation de l'entraînement

### 2. Initialiser la base de données

```bash
python src/core/database.py
```

Cela crée les tables ZEUS: `sessions` et `historique_paris`.

---

## 🚀 Utilisation

### Entraînement

```bash
# Entraînement rapide (test)
python train_zeus.py --timesteps 100000

# Entraînement complet (production)
python train_zeus.py --timesteps 1000000 --version v1.0

# Avec paramètres personnalisés
python train_zeus.py \
    --timesteps 500000 \
    --learning-rate 0.0001 \
    --checkpoint-freq 25000 \
    --eval-freq 5000
```

**Suivre la progression** avec TensorBoard:
```bash
tensorboard --logdir ./logs/zeus/
```

### Évaluation

```bash
# Évaluer le meilleur modèle
python evaluate_zeus.py --model ./models/zeus/best/best_model

# Évaluer sur une période spécifique
python evaluate_zeus.py \
    --model ./models/zeus/zeus_final_v1.0 \
    --journee-debut 39 \
    --journee-fin 76

# Évaluer sur plusieurs épisodes
python evaluate_zeus.py \
    --model ./models/zeus/best/best_model \
    --episodes 5
```

---

## 🏗️ Architecture

### Observation Space

Vecteur de 8 features normalisées [0, 1]:
- Différence de classement (position relative)
- Différence de points
- Momentum domicile (forme sur 5 derniers matchs)
- Momentum extérieur
- Probabilité implicite victoire domicile (1/cote_1)
- Probabilité implicite match nul (1/cote_x)
- Probabilité implicite victoire extérieur (1/cote_2)
- Avantage domicile (constant: 0.55)

### Action Space

13 actions discrètes:

| ID | Type | Mise (% capital) |
|----|------|------------------|
| 0 | Abstention | 0% |
| 1-3 | Prudence (1/N/2) | 5% |
| 4-6 | Prudence+ (1/N/2) | 7% |
| 7-9 | Conviction (1/N/2) | 8% |
| 10-12 | Conviction+ (1/N/2) | 10% |

**Règles de validation**:
- Mise minimale: 1 000 Ar
- Mise maximale: 10% du capital actuel
- Si capital < 1 000 Ar → Banqueroute (pénalité terminale de -10 000)

### Reward Function

```python
if pari_gagné:
    reward = profit_net  # Mise × (Cote - 1)
    score_zeus += 1
else:
    reward = -mise × 1.5  # Pénalité asymétrique
    score_zeus -= 1
    
if capital < 1000:
    reward -= 10_000  # Pénalité de banqueroute
```

---

## 📊 Métriques de Performance

| Métrique | Formule | Objectif Cible |
|----------|---------|----------------|
| **ROI** | (Capital Final - 20k) / 20k × 100 | > 15% |
| **Win Rate** | Paris Gagnés / Total Paris | > 55% |
| **Sharpe Ratio** | Rendement Moyen / Volatilité | > 1.5 |
| **Max Drawdown** | Min(Capital) - Peak Capital | < 30% |
| **Taux Abstention** | Abstentions / Matches | 20-40% |

---

## 🗄️ Base de Données

### Table `sessions`

Tracking des sessions d'entraînement et d'évaluation:
- `session_id` (PK)
- `timestamp_debut`, `timestamp_fin`
- `capital_initial`, `capital_final`
- `profit_total`
- `type_session` ('TRAINING', 'EVALUATION', 'PRODUCTION')
- `score_zeus` (compteur +1/-1)
- `version_ia`

### Table `historique_paris`

Archive de chaque décision de pari:
- `id_pari` (PK)
- `session_id` (FK → sessions)
- `match_id` (FK → matches_global)
- `journee`, `type_pari`, `mise_ar`
- `resultat` (1=gagné, 0=perdu, NULL=abstention)
- `profit_net`, `bankroll_apres`
- `action_id` (0-12)

---

## 🔧 Configuration PPO

Hyperparamètres optimisés:
```python
learning_rate = 3e-4
n_steps = 2048
batch_size = 64
n_epochs = 10
gamma = 0.99          # Discount factor
gae_lambda = 0.95
clip_range = 0.2
ent_coef = 0.01       # Faible = plus d'exploitation
vf_coef = 0.5
```

Architecture du réseau:
- Policy network: `[128, 128]`
- Value network: `[128, 128]`

---

## 📁 Structure du Module

```
src/zeus/
├── __init__.py
├── environment/
│   ├── betting_env.py      # Environnement Gymnasium
│   ├── observation.py      # Extraction de features
│   └── reward.py           # Calcul des récompenses
├── models/
│   └── ppo_agent.py        # Configuration PPO
├── database/
│   └── queries.py          # Requêtes SQL temporelles
├── training/
│   └── trainer.py          # Pipeline d'entraînement
└── utils/
    └── metrics.py          # Métriques de performance
```

---

## ⚠️ Points Critiques

### Isolation Temporelle

**CRUCIAL**: Éviter le data leakage!

```python
# ✅ CORRECT: Snapshot AVANT le match
classement = get_classement_snapshot(journee_actuelle, conn)
# Requête: WHERE journee < journee_actuelle

# ❌ INTERDIT: Inclut les données du match actuel
classement = get_classement_snapshot(journee_actuelle, conn)
# Requête: WHERE journee <= journee_actuelle  # LEAK!
```

### Overfitting

- **Walk-forward validation**: Train sur saisons 1-N, test sur N+1
- **Early stopping**: Basé sur performance de l'environnement d'évaluation
- **Regularization**: L2 implicite via PPO clip range

---

## 📈 Workflow Complet

1. **Préparation**:
   ```bash
   # S'assurer que les tables classement_global et matches_global sont remplies
   # avec des données historiques TERMINE
   ```

2. **Entraînement**:
   ```bash
   python train_zeus.py --timesteps 1000000
   ```

3. **Monitoring**:
   ```bash
   tensorboard --logdir ./logs/zeus/
   # Ouvrir http://localhost:6006
   ```

4. **Évaluation**:
   ```bash
   python evaluate_zeus.py --model ./models/zeus/best/best_model
   ```

5. **Analyse des résultats**:
   - Consulter la table `sessions` pour les résultats globaux
   - Consulter `historique_paris` pour analyser chaque décision
   - Utiliser les métriques affichées dans le rapport

---

## 🎓 Comprendre PPO

**Proximal Policy Optimization** est un algorithme de policy gradient qui:
- Optimise la politique (stratégie) de manière stable
- Utilise un "clip" pour éviter des updates trop agressives
- Balance exploration vs exploitation via le coefficient d'entropie
- Apprend une value function pour estimer les récompenses futures

**Pourquoi PPO pour ZEUS?**
- Stable et robuste (pas de catastrophic forgetting)
- Sample-efficient (réutilise les expériences)
- Fonctionne bien avec des espaces d'action discrets
- Prouvé sur des environnements similaires (trading, betting)

---

## 🐛 Debugging

### Problème: L'agent ne fait que s'abstenir

**Solution**: Réduire `ent_coef` pour encourager l'exploitation, ou augmenter la récompense d'abstention (actuellement -0.1).

### Problème: Banqueroute fréquente

**Solution**: 
- Augmenter la pénalité asymétrique (actuellement 1.5x)
- Réduire les pourcentages de mise dans `ACTION_SPACE_CONFIG`

### Problème: Pas de données historiques

**Solution**: S'assurer que `matches_global` contient des matchs avec `status='TERMINE'` et que `classement_global` est rempli.

---

## 📚 Références

- [Stable-Baselines3 Documentation](https://stable-baselines3.readthedocs.io/)
- [Gymnasium Documentation](https://gymnasium.farama.org/)
- [PPO Paper (Schulman et al., 2017)](https://arxiv.org/abs/1707.06347)

---

## 📝 License

Propriété de GODMOD Team - Usage interne uniquement.
