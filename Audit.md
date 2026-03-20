Rapport d'Audit de Code et de Sécurité

Date de l'analyse : 20 Mars 2026
Périmètre : Backend (Python) & Frontend (React/TypeScript)
Niveau d'expertise : Avancé / Architecte Logiciel

1. Résumé Exécutif

L'analyse statique du code révèle deux axes d'amélioration majeurs. Le score architectural est extrêmement faible (28/100), indiquant une dette technique importante qui va ralentir le développement futur et complexifier la maintenance. Plus critique encore, le volet sécurité affiche un score préoccupant (57/100) avec la présence de vulnérabilités majeures, dont des risques d'Injection SQL, nécessitant une intervention immédiate avant toute mise en production.

2. Analyse Architecturale (Auriel - Architecture)

Score : 28/100 | Problèmes identifiés : 130
Le code souffre de problèmes de maintenabilité, principalement dus à de mauvaises pratiques de codage et à du code généré/copié non optimisé.

2.1. Nombres Magiques (Magic Numbers)

Niveau de sévérité : Mineur / Informationnel (mais pollue la maintenabilité)
Description : L'utilisation de valeurs numériques codées en dur (ex: 16, 50, 900) au lieu de constantes nommées rend le code difficile à lire et complique les futures modifications. Une modification de cette valeur nécessitera une recherche et un remplacement fastidieux, avec un risque d'oubli.

Fichiers concernés :

Frontend (Valeur 16) : * Frontend/src/components/BetDetailModal.tsx (Lignes 92, 100)

Frontend/src/components/PredictionCard.tsx (Ligne 224)

Frontend/src/components/NextMatchCard.tsx (Lignes 174, 204)

Frontend/src/components/OfflineBanner.tsx (Ligne 18)

Frontend/src/components/StandingCard.tsx (Ligne 101)

Frontend/src/components/BorrowModal.tsx (Ligne 149)

Frontend/src/components/ResetModal.tsx (Ligne 152)

Frontend/src/theme/Theme.ts (Ligne 24)

Frontend & Backend (Valeur 50) :

Frontend/src/components/ComboPredictionCard.tsx (Lignes 85, 86)

Backend/main.py (Ligne 316)

Backend/tools/dashboard_ui.py (Ligne 40)

Backend/src/prisma/analyzers.py (Ligne 38)

Frontend (Valeur 900) :

Frontend/src/components/ResetModal.tsx (Ligne 149)

Recommandation : Créer un fichier constants.ts côté Frontend et un fichier config.py ou constants.py côté Backend pour centraliser ces valeurs (ex: DEFAULT_MARGIN = 16, MAX_ITEMS = 50).

2.2. Code Dupliqué (Copier-Coller)

Niveau de sévérité : Avertissement (Violation du principe DRY - Don't Repeat Yourself)
Description : Des blocs de code identiques ont été détectés. Cela signifie que si un bug est présent dans ce bloc, il devra être corrigé à plusieurs endroits.

Fichiers concernés :

Backend/src/api/server.py : 3 blocs dupliqués détectés aux alentours de la ligne 278 (Lignes 203~278, 247~332, 249~334).

Recommandation : Extraire la logique commune dans une fonction utilitaire ou une classe parente et l'appeler aux différents endroits nécessaires.

2.3. Code Mort et Paramètres Inutilisés

Niveau de sévérité : Informationnel
Description : La présence de modules non importés et de paramètres de fonctions non utilisés alourdit la base de code inutilement. L'outil signale que ces paramètres pourraient être des résidus de code généré par IA.

Fichiers concernés :

Module Orphelin : Frontend/src/components/CategoryChip.tsx (Exporté mais jamais utilisé).

Paramètres inutilisés : * Backend/src/api/db_integration.py (Ligne 139)

Frontend/src/components/BorrowModal.tsx (Ligne 24)

Frontend/src/components/BottomNav.tsx (Ligne 35)

Recommandation : Supprimer le composant CategoryChip.tsx s'il n'est pas prévu pour un usage futur. Nettoyer les signatures de fonctions pour ne garder que les paramètres réellement exploités.

3. Analyse de Sécurité (Uriel - Sécurité)

Score : 57/100 | Problèmes identifiés : 3 (dont 1 CRITIQUE)
C'est le point de défaillance majeur de l'application. La présence d'une injection SQL compromet totalement l'intégrité de la base de données.

3.1. Vulnérabilité Critique : Injection SQL Potentielle

Niveau de sévérité : CRITIQUE (Urgence Absolue)
Description : L'utilisation de f-strings Python pour formater des requêtes SQL permet à un utilisateur malveillant d'injecter du code SQL arbitraire. Cela peut mener à la fuite de données sensibles (vol de base de données), la modification ou la suppression de données (drop tables).

Fichiers concernés :

Backend/scripts/db_audit.py (Ligne 84)

Backend/main.py (Ligne 179)

Recommandation experte : Bannir immédiatement l'utilisation des f-strings pour les requêtes SQL. Utiliser des requêtes paramétrées fournies par l'ORM ou le connecteur de base de données (ex: paramètres ? ou %s passés en arguments séparés de la fonction d'exécution SQL).

3.2. Algorithmes de Chiffrement Obsolètes

Niveau de sévérité : Avertissement / Élevé
Description : Des algorithmes de chiffrement dépréciés (probablement MD5, SHA1 ou des algorithmes de hachage non salés) sont utilisés. Ils sont vulnérables aux attaques par force brute ou par collision, ce qui met en péril la confidentialité des données (ex: mots de passe, tokens).

Fichiers concernés (Vaste impact) :

Backend / Core & DB :

Backend/src/core/init_data.py (Ligne 19)

Backend/src/core/database.py (Lignes 200, 233)

Backend/src/prisma/engine.py (Ligne 5)

Backend/src/api/server.py (Ligne 46)

Backend / IA & Training :

Backend/src/zeus/training/trainer.py (Ligne 60)

Backend/src/analysis/ai_booster.py (Ligne 214)

Backend/src/zeus/entrainement/train_zeus.py (Ligne 31)

Frontend :

Frontend/src/app/index.tsx (Ligne 213)

Recommandation experte : 1. Identifier l'algorithme exact incriminé.
2. Migrer vers des standards cryptographiques modernes et robustes : Argon2, bcrypt ou scrypt pour le hachage de mots de passe, et AES-256-GCM pour le chiffrement de données.
3. Côté Frontend, s'assurer que le chiffrement (s'il s'agit de stockage local) utilise les API cryptographiques natives du navigateur (Web Crypto API).

4. Plan d'Action (Roadmap de Résolution)

Voici la marche à suivre recommandée pour l'équipe de développement, par ordre de priorité :

HOTFIX (Jour 1) - Résolution de l'Injection SQL : Corriger main.py et db_audit.py. C'est le seul point bloquant qui peut compromettre le serveur dans l'immédiat. Utiliser des requêtes préparées/paramétrées.

Mise à niveau Cryptographique (Semaine 1) : Remplacer les algorithmes de hachage obsolètes dans les fichiers database.py, server.py et les fichiers d'entraînement zeus. Mettre en place un plan de migration pour les utilisateurs existants si les mots de passe sont touchés.

Refactoring de la Dette Technique (Semaines 2-3) :

Créer les fichiers de constantes globales et nettoyer les "Nombres Magiques" sur l'ensemble du Front et du Back.

Refactoriser la fonction dupliquée dans server.py (ligne 278).

Lancer une session de nettoyage du code mort (CategoryChip.tsx et paramètres de fonctions AI-generated).

Conclusion :
La base de code semble avoir été développée rapidement ou avec l'assistance d'IA sans phase rigoureuse de révision humaine (Code Review). La priorité absolue est de sécuriser le backend avant d'envisager l'ajout de nouvelles fonctionnalités.