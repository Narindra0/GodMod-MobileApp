⚡ Référence des Spécifications UX Approfondies - GODMOD Mobile

Ce document constitue la charte fonctionnelle et ergonomique complète du "Intelligence Center" pour les Paris Virtuels. Il définit non seulement les composants, mais aussi la logique d'interaction et les objectifs de performance utilisateur.

1. Structure Globale et Navigation

Header (Barre Supérieure contextuelle)

Le header agit comme le centre de contrôle de la session utilisateur.

Architecture du contenu :

Titre Dynamique : Adaptation immédiate selon l'écran (ex: "Intelligence Center", "Archives ZEUS").

Identité Utilisateur : Avatar circulaire avec bordure colorée indiquant le niveau de compte ou le prestige.

Badge de Connectivité : Indicateur de latence en temps réel. Vert (Optimal), Orange (Lent), Rouge (Déconnecté).

Synchronisation : Affichage de l'heure exacte (ex: "MAJ à 14:02:45").

Comportements Avancés :

Un appui long sur le badge de statut peut forcer un "Hard Refresh" (vidage du cache local).

Le tap sur l'avatar déclenche une transition par glissement latéral pour accéder aux préférences de compte.

Bottom Navigation (L'Ancrage Tactile)

Conçue pour une utilisation à une seule main (zone de confort du pouce).

Les Quatre Piliers :

Accueil (Live Deck) : Vue globale et alertes immédiates.

Prédictions (Algorithm Log) : Le flux détaillé des décisions de l'IA.

Classement (League Context) : Données macro sur les performances des équipes.

Paramètres (Core Engine) : Accès aux entrailles du système ZEUS.

Visualisation & Feedback : L'onglet actif utilise une couleur d'accentuation (branding) et une légère élévation visuelle. Un retour haptique léger est recommandé lors du changement d'onglet.

Éléments de Feedback & Notifications

Notifications Toast (Système d'Alerte) : * Utilisation pour les confirmations d'actions (ex: "Paramètres sauvegardés") ou les alertes réseau.

Interactivité : Les toasts d'erreur critiques incluent un bouton "Détails" ou "Réessayer".

Loader Global (Expérience de Patience) :

Phase 1 : Animation de logo (Pulse) pour les chargements de plus de 500ms.

Phase 2 : Texte descriptif qui change cycliquement pour rassurer l'utilisateur (ex: "Analyse des probabilités...", "Compilation des scores...").

2. Bibliothèque de Composants Détallée

Cartes de Données (Data Containers)

Carte de Statistique (Metric Card) :

Hiérarchie : Le chiffre principal doit être lisible à une distance de 50cm.

Analyse de Tendance : La variation (ex: +2.4%) est accompagnée d'une micro-icône (flèche vers le haut/bas). Si la variation est nulle, le badge devient gris neutre.

Carte de Match (Prediction Card) :

Détails Techniques : Affiche le logo des équipes, l'indice de confiance de l'IA (0-100%) et le type de pari (ex: "Over 2.5", "Victoire D").

États de Résultat : En cas de succès, une bordure subtile verte "Glow" est appliquée. En cas d'échec, la carte devient légèrement translucide pour hiérarchiser les réussites.

Carte de Classement (Standings) :

Indicateur de forme : Pastilles de couleurs (W=Vert, D=Gris, L=Rouge) cliquables pour voir les scores de ces matchs passés.

Contrôles & Entrées (Input Strategy)

Boutons d'Action :

Primaire : Largeur totale ou importante, couleur pleine. Utilisé pour les actions de validation.

Secondaire : Style "Ghost" (bordure seule). Utilisé pour les actions d'annulation ou secondaires.

Intelligence Toggles & Sliders :

Toggle "Full Intelligence" : Déclenche une animation de scan visuel sur tout l'écran lors de l'activation.

Slider de Rafraîchissement : Graduation tactile avec paliers (ex: 5s, 15s, 30s, 1min). Chaque palier est accompagné d'un "clic" haptique.

3. Architecture des Écrans Clés

3.1. Dashboard : Le Centre de Commandement

L'objectif est de fournir une vision à 360° en moins de 3 secondes.

Zone Focus : Carrousel horizontal des "Top Opportunités" détectées par ZEUS.

Visualisation de Données : Graphique en aires (Area Chart) pour le profit cumulé, permettant un défilement horizontal (Scroll) pour remonter dans le temps sur les 24 dernières heures.

Quick Actions : Bouton flottant (FAB) optionnel pour un rafraîchissement instantané des probabilités.

3.2. History : Le Registre de Performance

Conçu pour l'audit et l'analyse post-match.

Filtrage Avancé : Menu rétractable permettant de filtrer par ligue, par plage de cotes (ex: 1.50 - 2.10) et par statut de validation.

Performance : Utilisation du "Lazy Loading" pour garantir que le défilement de l'historique reste fluide même après des milliers d'entrées.

3.3. League : Analyse Contextuelle

Fournit le "Pourquoi" derrière les prédictions de l'IA.

Dual View : Bascule rapide via un Segmented Control (Classement / Résultats récents).

Détails Équipes : Au clic sur une équipe, affichage d'une "BottomSheet" (panneau inférieur) montrant les statistiques offensives et défensives spécifiques à la version virtuelle.

3.4. Configuration : Personnalisation de l'IA

Le cerveau du système.

Mode "Dark/Light" : Option de forçage ou de suivi du système.

Seuils de Sécurité : Configuration des limites de notification pour ne recevoir des alertes que sur les prédictions avec une confiance supérieure à X%.

4. Guide des États et Comportements Tactiles

Le design doit répondre à la règle des "7 États" pour garantir une interface vivante et robuste :

Défaut : Composant prêt à l'interaction.

Pressé (Pressed) : Réduction légère de l'échelle (scale: 0.98) pour simuler une pression physique.

Chargement (Skeleton) : Remplacement du texte par des formes grises pulsantes pour maintenir la structure de la page.

Succès (Success) : Feedback positif avec icône de validation (Checkmark).

Erreur (Error) : Vibration du composant (Shake animation) et message explicatif textuel.

Désactivé (Disabled) : Opacité à 40% et suppression des événements de clic.

Vide (Empty State) : Lorsqu'aucune donnée n'est disponible, affichage d'une illustration minimaliste et d'un bouton d'action (ex: "Lancer l'analyse").