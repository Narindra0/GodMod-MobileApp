
# Architecture de Stockage par Sessions (v4)

Ce document décrit la nouvelle architecture de stockage de GODMOD, où les données sont organisées par sessions distinctes.

## 1. Schéma de la Base de Données

Toutes les données clés sont désormais liées à une session spécifique via une clé étrangère `session_id`.

### Tables Clés

- **`sessions`** : Stocke les métadonnées de chaque session.
    - `id` : Identifiant unique.
    - `status` : 'ACTIVE' (actuellement en cours) ou 'CLOSED' (session terminée).
    - `current_day` : Compteur de jours interne (1 à 37).
    - `capital_initial` : Le bankroll de départ pour cette session.
    - `capital_final` : Le bankroll à la fin de la session.
- **`matches`**, **`classement`**, **`predictions`**, **`historique_paris`** : Contiennent une colonne `session_id` obligatoire.

## 2. Flux de Données et Cycle de Vie

### Initialisation
Au démarrage du système, le `session_manager` vérifie s'il existe une session `ACTIVE`. Si ce n'est pas le cas, il en crée une nouvelle (Session 1, Jour 1, Capital: 20000).

### Progression Quotidienne
À chaque nouvelle journée détectée par le moniteur :
1. Les données collectées (classement, matchs, cotes) sont enregistrées avec le `session_id` de la session active.
2. Le `current_day` de la session active est mis à jour.

### Transition Automatique (Jour 37)
Lorsqu'un jour supérieur à 37 est détecté :
1. La session active actuelle est marquée comme `CLOSED`.
2. Le capital final est récupéré du dernier pari enregistré dans `historique_paris`.
3. Une nouvelle session est créée avec le statut `ACTIVE` et le jour `1`.
4. Le capital initial de la nouvelle session est égal au capital final de la session précédente.

## 3. Avantages de cette Architecture

1.  **Traçabilité** : Vous pouvez désormais comparer les performances de ZEUS entre différentes périodes (sessions) sans que les données ne se mélangent.
2.  **Intégrité** : L'historique financier est préservé et lié précisément aux prédictions qui ont généré les gains ou pertes.
3.  **Isolation** : L'IA ne s'appuie que sur les données de la session actuelle, évitant ainsi toute pollution par des données obsolètes.
4.  **Automatisation** : Le basculement se fait sans intervention manuelle et sans perte de données.
