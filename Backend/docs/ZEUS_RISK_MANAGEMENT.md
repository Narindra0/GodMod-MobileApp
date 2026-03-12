# 🛡️ GESTION DES RISQUES ZEUS (v2.0)

Ce document détaille le système de gestion des risques et des mises implémenté pour l'agent ZEUS.

---

## 💰 Nouvelles Règles de Mise

Le système a migré d'un mécanisme basé sur des pourcentages vers un système de **valeurs fixes en Ariary (Ar)** pour plus de prévisibilité et de stabilité.

### Configuration du Capital
- **Bankroll Initial** : 20 000 Ar
- **Mise Minimale** : 1 000 Ar
- **Seuil de Banqueroute** : 1 000 Ar (ZEUS s'arrête si le capital descend en dessous)

### Espace d'Actions (Mises Fixes)
| Action ID | Type de Pari | Montant (Ar) |
|-----------|--------------|--------------|
| 0         | Abstention   | 0            |
| 1 - 3     | Prudence     | 1 000        |
| 4 - 6     | Prudence+    | 1 500        |
| 7 - 9     | Conviction   | 2 000        |
| 10 - 12   | Conviction+  | 2 500        |

---

## 🧮 Algorithme de Calcul du Risque

Le `RiskManager` valide chaque tentative de mise selon les règles suivantes :

1.  **Validation du Minimum** : Toute mise inférieure à 1 000 Ar est systématiquement rejetée.
2.  **Calcul du Plafond de Risque** :
    ```python
    Mise_Max = Capital_Actuel - Seuil_Banqueroute (1000)
    ```
3.  **Arbitrage de Mise** :
    - Si `Mise_Demandée <= Mise_Max`, la mise est acceptée telle quelle.
    - Si `Mise_Demandée > Mise_Max` mais `Mise_Max >= 1000`, la mise est plafonnée à `Mise_Max`.
    - Si `Mise_Max < 1000`, toute mise est rejetée et l'agent est forcé à l'abstention.

---

## 📈 Monitoring du Bankroll

### Niveaux d'Alerte
Le système surveille le capital en temps réel et génère des alertes :
- **Critique (Bankroll < 5 000 Ar)** : Alerte orange. ZEUS approche d'une zone dangereuse.
- **Danger (Bankroll < 1 000 Ar)** : Alerte rouge. Suspension immédiate des activités.

### Rapport de Performance et Risque
Un rapport détaillé est généré via `generer_rapport_risque()` incluant :
- **Drawdown Max** : Pourcentage de perte depuis le point le plus haut.
- **Niveau de Risque** : Évaluation qualitative (FAIBLE, MODÉRÉ, ÉLEVÉ).
- **Profit/Perte** : Net financier depuis le début de la session.
- **Taux de Banqueroute** : Statut binaire de faillite.

---

## 🧪 Procédures de Test

Les règles de gestion des risques sont couvertes par des tests unitaires automatisés dans `tests/test_zeus_risk_management.py`.

Pour exécuter les tests :
```bash
python tests/test_zeus_risk_management.py
```

---

## 📁 Architecture des Fichiers

- `src/zeus/utils/risk_manager.py` : Cœur de la logique de risque.
- `src/zeus/environment/betting_env.py` : Intégration dans l'environnement RL.
- `tests/test_zeus_risk_management.py` : Validation de l'intégrité financière.
