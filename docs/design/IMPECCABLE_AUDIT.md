# Audit Impeccable — tableau de bord job-match

**Branche** `design/impeccable-pass` (depuis `origin/main` 7299229) · 2026-11-07 · **diagnostic
uniquement : aucune ligne de l'UI n'a été modifiée.** À valider avant toute correction.

Installation et choix d'outillage : [`IMPECCABLE_SETUP.md`](IMPECCABLE_SETUP.md). Contexte produit :
[`/PRODUCT.md`](../../PRODUCT.md) (écrit par `/impeccable init`). Système visuel :
[`DESIGN.md`](DESIGN.md) (complété, section finale « Product context and recorded drift »).

## 0. Méthode et provenance

| Étape | Ce qui a tourné | Notes |
|---|---|---|
| `/impeccable init` | `PRODUCT.md` à la racine | réponses d'entretien = ton brief (utilisateur unique, 3 tâches, desktop + mobile, AA) ; pas de question supplémentaire posée. `buildPath` non enregistré (écran applicatif : code-first d'office) ; live mode non configuré (exclu) |
| Captures | Playwright (Chromium 1243), seed de test `tests/unit/conftest.py` + payloads API des tests navigateur (`test_candidatures.py`, `test_stats.py`), horloge figée au 2026-10-20 09:00 UTC, `prefers-reduced-motion: reduce` pour des images stables | 6 vues × clair/sombre × 1440×900 / 390×844 = 24 captures de base ; 34 captures break-ui ; 3 à 200 % de zoom ; 1 de la divergence j/k (62 au total). Données de test uniquement (le 1er titre est la sonde XSS du seed, l'entreprise `Beta <b>Corp</b>` aussi : elles s'affichent comme du texte, c'est le comportement voulu) |
| `/impeccable critique` | **Assessment A** (revue design) dans un sous-agent isolé, sans accès aux sorties du détecteur ; **Assessment B** (détecteur) dans le contexte principal | ⚠️ *Run partiellement dégradé* : B a tourné dans le contexte principal **avant** A (A est resté isolé, mais la synthèse a vu B en premier). L'overlay navigateur de B (`live-server` + `detect.js` injecté) n'a **pas** été utilisé : il fait partie du mode live, exclu par la consigne |
| `/impeccable audit` | 5 dimensions techniques, score /20 | contrastes, cibles, débordements mesurés par script (calcul WCAG sur chaque nœud texte visible) en plus du détecteur |
| `npx impeccable detect` | statique sur `src/job_match/dashboard/assets`, puis **par URL** sur un serveur local de fixtures (`127.0.0.1:8765`, seed + API mockée), 6 vues × 1440/390 | 12 scans URL (thème du système headless = clair), 2 findings statiques |
| break-ui | données injectées à la frontière des fixtures (Hard Rule 2), pas de bascule « Demo / Worst case » dans l'UI (diagnostic uniquement) | titres très longs, 0 offre, 500 offres, entreprise inconnue, API du Worker en panne (= suivi indisponible), pas de score IA ; la panne de source France Travail est déjà dans le seed (exécution du 04/10) |

Captures : `docs/design/screenshots/impeccable/` — `<vue>-<1440|390>-<dark|light>.png`,
`breakui-<scénario>-<vue>-<1440|390>.png`, `zoom200-<vue>-1440.png`,
`offres-jk-divergence-1440-dark.png`. L'instantané de critique d'Impeccable (`.impeccable/critique/`,
gitignoré) n'a pas été écrit : ce rapport en tient lieu. Le serveur de fixtures a été arrêté.

Non testé : Safari/WebKit (safe-area, `100dvh`), lecteur d'écran réel, appareil tactile physique,
geste de swipe du Tri sous vrai toucher (émulation `has_touch` seulement), RTL (sans objet).

## 1. Synthèse

| Mesure | Résultat |
|---|---|
| `/impeccable audit` (technique) | **15/20 — Bon** (a11y 3, perf 3, theming 3, responsive 3, intégrité 3) |
| `/impeccable critique` (heuristiques de Nielsen, revue A) | **27/40 — Acceptable, haut de bande** |
| Problèmes | **45** : **3 P1**, 22 P2, 20 P3, aucun P0 |
| Détecteur | 2 findings statiques (tous deux voulus par le contrat), 8 règles en scan URL dont 6 confirmées |
| Débordement horizontal / erreurs console | 0 px sur 58 captures / 0 (hors 404 et 500 attendus des fixtures) |

**Les 3 P1, à corriger en premier :**
1. **O10** — Offres : `j`/`k` déplacent le focus mais pas la fiche ; `X`/`S`/`A` agissent sur une
   offre que la fiche ne montre pas.
2. **O1** — Offres, thème clair : scores des lignes traitées à 2,4–2,7:1 (échec AA sur la donnée
   principale de la ligne).
3. **C1** — Candidatures : quand le suivi ne charge pas, « 0 dossier suivi · 0 relance en
   retard » — un inconnu présenté comme un zéro.

**Le reste en une phrase :** la structure est propre au produit (relevé du score, inconnu dit
comme tel, panne de source expliquée), l'habillage ne l'est pas (surtitre-slogan en capitales sur
chaque vue, micro-libellés en capitales de 10 px, deux primaires, la même relance annoncée 4 à 5
fois), et les états limites mentent parfois (liste vide « rien collecté », « 0 % », clé brute en
titre, codes `not_relevant`).

## 2. Problèmes par vue

Légende — **Priorité** : P1 = échec WCAG AA ou affichage d'une information fausse/inventée ;
P2 = gêne réelle avec contournement ; P3 = finition. Aucun P0 (aucune tâche bloquée).
**Effort** : S < 1 h · M ≈ ½ journée · L > 1 jour. **Commande** : la commande Impeccable qui
corrigerait le problème (à lancer après ta validation).

### Tri (`#tri`)

| ID | Prio | Problème | Capture | Commande | Effort |
|---|---|---|---|---|---|
| T1 | P2 | **Titre de la carte non borné** : un titre long prend 7 lignes à 390 px et pousse le « Relevé du score » sous la ligne de flottaison ; la décision se prend alors sans le score visible. Borner à 3 lignes (titre complet dans la fiche, déjà à un clic) | `breakui-long-titles-tri-390.png` | `/impeccable harden` | S |
| T2 | P2 | **Viewport court** (téléphone en paysage, zoom 200 %) : barre du haut 56 px + en-tête de page (surtitre, titre 26 px, sous-titre) + progression + barre d'actions + tab bar 64 px → ≈ 100 px utiles pour la carte. L'en-tête de page devrait se replier sous ~600 px de haut | `zoom200-tri-1440.png` | `/impeccable adapt` | M |
| T3 | P2 | **Graduations du relevé** : « digest 60 » / « forte 70 » en 10 px, mot interne anglais « digest », 3,3:1 en clair. Dire « seuil d'envoi 60 » / « forte 70 » en 11 px AA | `tri-1440-light.png` | `/impeccable clarify` | S |
| T4 | P2 | **Suivi indisponible** : deux bandeaux empilés (ambre « Le suivi n'a pas pu être chargé » + gris « Le tri enregistre tes choix : il demande le tableau de bord hébergé ») ; le second donne une fausse cause (la page *est* hébergée, c'est l'API qui a échoué) et repousse la carte d'environ 170 px à 390 px | `breakui-api-down-tri-390.png` | `/impeccable harden` | S |
| T5 | P2 | **Écran « Tri terminé » collé en bas** de la zone (y ≈ 610–868 à 1440) avec un vide au-dessus : la fin du tri — le moment « peak-end » — paraît cassée | `breakui-empty-tri-1440.png` | `/impeccable layout` | S |
| T6 | P3 | **Ligne d'explication non reconnue ignorée en silence** : le seed utilise un ancien format (« +15 docker ») que `score.js` ne parse pas ; le relevé affiche alors « Point de départ 65 / Total 65 », ce qui est faux (le départ n'était pas 65). Les lignes du vrai scorer (« Matched preferred: docker (+15) ») sont reconnues ; le défaut est la retombée : dire « détail non lisible » plutôt qu'un point de départ inventé | `tri-1440-dark.png` | `/impeccable harden` | S |
| T7 | P2 | **Raison d'écart perdue** : l'étape « Pourquoi ? » se ferme seule après 8 s (`tri.js:266`) et n'est jamais proposée pour la dernière carte (`tri.js:300`, voulu). Les « Raisons d'écart » de Statistiques sont donc biaisées, et une action minutée pénalise un usage lent (WCAG 2.2.1) | — (vérifié dans le code) | `/impeccable harden` | S |

### Offres (`#offres`)

| ID | Prio | Problème | Capture | Commande | Effort |
|---|---|---|---|---|---|
| O1 | **P1** | **Contraste AA raté en thème clair** : les scores et libellés de bande des lignes déjà traitées (`.is-handled`, opacité 0,6 sur toute la cellule) tombent à 2,4–2,7:1 (`#6b9e8e` sur `#e8e5f6`, `#b69464` sur `#f9f9fb`). Le score est *la* donnée de la ligne. Atténuer le titre, pas le score, ou utiliser `--ink-2` au lieu d'une opacité | `offres-1440-light.png`, `offres-390-light.png` | `/impeccable polish` | S |
| O2 | P2 | **Deux boutons primaires** à ≥ 1280 px : « Trier les nouvelles » (en-tête) et « Candidature envoyée » / « Garder » (pied de fiche), plus « Bon match » plein violet dans « Ton avis ». DESIGN.md : un primaire par écran. Le primaire de la vue est l'action sur l'offre sélectionnée | `offres-1440-dark.png` | `/impeccable quieter` | S |
| O3 | P2 | **Cibles < 44 px à 390 px** : champ de recherche 36 px, boutons « Trier par » 36 px, « Trier les nouvelles » 40 px (DESIGN.md exige 44 px sous 768 px) | `offres-390-dark.png` | `/impeccable adapt` | S |
| O4 | P2 | **Liste vide qui affirme une cause fausse** : « Le run de ce matin n'a rien collecté » est un texte fixe (`list.js:474`) affiché même quand l'exécution a lu 533 offres ; la variante filtrée parle aussi du « run de ce matin » alors que les filtres portent sur toute la liste. Lire le dernier run (lues / éligibles) et le dire | `breakui-empty-offres-1440.png` | `/impeccable clarify` | S |
| O5 | P2 | **Titre de la fiche non borné** : 6 lignes à 26 px dans le panneau de 420 px ; « Adéquation 85/100 » et le pourquoi descendent sous le pli. Borner à 3 lignes + titre complet au survol / dépliable | `breakui-long-titles-offres-1440.png` | `/impeccable harden` | S |
| O6 | P2 | **0 offre** : la fiche vide montre « Sélectionne une offre… J et K parcourent la liste » alors qu'il n'y a rien ; « Trier les nouvelles » reste primaire et actif à 0 | `breakui-empty-offres-1440.png` | `/impeccable onboard` | S |
| O7 | P3 | **Monogrammes faux** : « B< » pour `Beta <b>Corp</b>`, « E1 » pour « Entreprise 17 » — initiales prises sur les caractères bruts. Prendre les lettres des deux premiers mots, sinon une icône | `offres-1440-dark.png`, `breakui-500-offres-offres-1440.png` | `/impeccable harden` | S |
| O8 | P3 | **Barre « Trier par » à 390 px** : défile horizontalement, « VILLE » coupé sans indice de défilement ; capitales espacées | `offres-390-dark.png` | `/impeccable adapt` | S |
| O9 | P3 | 500 offres : tout est rendu (14 000 nœuds, 33 ms par frappe). Suffisant aujourd'hui ; le commentaire `list.js` suppose « about 50 rows ». Rien à faire tant que la liste reste sous quelques centaines | `breakui-500-offres-offres-1440.png` | `/impeccable optimize` | M (si besoin) |
| O10 | **P1** | **Le curseur j/k et la fiche divergent** (vérifié en direct à 1440) : après `j j` le focus est sur « SRE confirmé » mais la ligne violette, la fiche et `?fiche=` restent sur la 1re offre jusqu'à `O`, alors que `X` / `S` / `A` agissent sur la ligne focalisée. Risque de marquer « Candidature envoyée » une offre qu'on ne lit pas. À ≥ 1280 px la fiche doit suivre le curseur (aucun appel réseau) | `offres-jk-divergence-1440-dark.png` (focus sur la ligne « SRE confirmé », fiche sur la 1re offre) | `/impeccable harden` | M |
| O11 | P2 | **Malus affiché comme un atout** sur le chemin de repli : une compétence de `lowered` sans poids numérique et sans ligne d'explication est rendue « up » (point vert) (`why.js:134`). Les lignes du vrai scorer passent par le chemin normal ; le repli doit déduire le sens de `lowered` | `breakui-500-offres-offres-1440.png` (« php ») | `/impeccable harden` | S |
| O12 | P3 | Pied de fiche : un « × » seul à côté du primaire (nom accessible « Écarter l'offre », mais aucun mot visible) et un second « × » de fermeture en haut | `offres-1440-dark.png` | `/impeccable clarify` | S |

### Candidatures (`#candidatures`)

| ID | Prio | Problème | Capture | Commande | Effort |
|---|---|---|---|---|---|
| C1 | **P1** | **Inconnu affiché comme zéro** quand le suivi ne charge pas : « 0 dossier suivi · 0 relance en retard · 0 entretien », colonnes « Aucune. », « Garde des offres dans Tri pour les voir ici », sidebar « Candidatures 0 ». C'est une donnée inventée (principe 3 de PRODUCT.md) : afficher « — » et un état « suivi indisponible » à la place des colonnes | `breakui-api-down-candidatures-1440.png` | `/impeccable harden` | M |
| C2 | P2 | **La même relance annoncée 5 fois** : sidebar « Relances à faire 1 », bouton ambre « 1 relance en retard », ligne de chiffres « 1 relance en retard », bandeau ambre pleine largeur, puce rouge sur la carte. Garder le bandeau (liste cliquable) et la puce ; retirer le bouton et le chiffre redondants | `candidatures-1440-dark.png` | `/impeccable distill` | S |
| C3 | P2 | **Clé brute comme titre** : une candidature dont l'offre a quitté l'instantané s'intitule `france_travail:GONE1` (`board.js:346`). Afficher « Offre retirée » + source et date, la clé en info-bulle | `candidatures-1440-dark.png` | `/impeccable clarify` | S |
| C4 | P2 | **Titres longs** : carte Kanban non bornée (8 lignes), bandeau de relance qui passe sur 4 lignes à 390 px avec un titre sans coupure | `breakui-long-titles-candidatures-1440.png`, `…-390.png` | `/impeccable harden` | S |
| C5 | P2 | **390 px** : les 4 colonnes s'empilent ; « Envoyée » (où est la relance due) arrive après tout « À candidater » ; le bouton « 1 relance en retard » et « Kanban / Tableau » se tassent sur 2 lignes. Sur téléphone, ouvrir sur la colonne qui a une action due ou proposer des onglets par statut | `candidatures-390-light.png` | `/impeccable adapt` | M |
| C6 | P3 | Un primaire « J'ai postulé » **par carte** « À candidater » : avec 6 cartes, 6 primaires | `candidatures-1440-dark.png` | `/impeccable quieter` | S |
| C7 | P3 | « Aujourd'hui » seul en tête des métadonnées de carte : on ne sait pas de quoi (mise à jour ? publication ?) | `candidatures-1440-dark.png` | `/impeccable clarify` | S |
| C8 | P3 | Titres `h1` → `h3` (le bandeau et les colonnes sautent `h2`) | — (détecteur) | `/impeccable polish` | S |
| C9 | P3 | Vocabulaire qui dérive pour la même action : « J'ai postulé », « Candidature envoyée », « Envoyée » ; liens « Offre » et « Voir la fiche » côte à côte ; point rouge « offre plus affichée » confondu avec le rouge de Refus | `candidatures-1440-dark.png` | `/impeccable clarify` | S |

### Statistiques (`#statistiques`)

| ID | Prio | Problème | Capture | Commande | Effort |
|---|---|---|---|---|---|
| S1 | P2 | **Graphe hebdomadaire illisible à petits effectifs** : axe max = 1, chaque événement devient un trait de 12 px de large sur toute la hauteur (≈ 250 px), le graphe sort de l'écran ; on lit des pics, pas une tendance. Hauteur proportionnée, barres groupées par semaine, et en dessous de ~5 événements montrer le tableau seul | `statistiques-1440-dark.png` | `/impeccable layout` | M |
| S2 | P3 | Tuiles « gros chiffre + libellé 11 px » (gabarit KPI) ; « anciennes) » orphelin ; le sous-texte de « Archivées » contredit le sens d'« archivée » dans Candidatures (cf. PROGRESS : connu) | `statistiques-1440-dark.png` | `/impeccable typeset` | S |
| S3 | P2 | **Arrondi trompeur** : 2 gardées sur 500 vues → « 0 % des vues » (`stats.js:236`, `Math.round`). Afficher « < 1 % » ou une décimale | `breakui-500-offres-statistiques-1440.png` | `/impeccable clarify` | S |

### Leads (`#leads`)

| ID | Prio | Problème | Capture | Commande | Effort |
|---|---|---|---|---|---|
| L1 | P3 | « 1 leads de financement » : pluriel codé en dur (`leads.js:70`) | `leads-1440-dark.png` | `/impeccable clarify` | S |
| L2 | P3 | Tour « series a » brut, en anglais et en minuscules ; « Publiée 18/10 » dans un format différent des autres vues | `leads-1440-dark.png` | `/impeccable clarify` | S |
| L3 | P3 | 390 px : l'étiquette « recruter 30 personnes » déborde de sa boîte de 111 px | `leads-390-dark.png` | `/impeccable harden` | S |
| L4 | P3 | Point vert sans libellé devant « Acme » (couleur seule) | `leads-1440-dark.png` | `/impeccable polish` | S |

### Exécutions (`#executions`)

| ID | Prio | Problème | Capture | Commande | Effort |
|---|---|---|---|---|---|
| E1 | P2 | **Codes machine non traduits** : « experience 197 · contract 30 · not_relevant 10 » (`runs.js:109` fait juste `toLowerCase()`), « ats: … france_travail: … » comme libellés de source. Le reste de l'UI dit « Trop senior », « France Travail » | `executions-1440-dark.png` | `/impeccable clarify` | S |
| E2 | P3 | Deux boutons « Lancer maintenant » au nom accessible identique (Rerank IA / Documents) : un lecteur d'écran ne les distingue pas (`index.template.html:280,285`) | `executions-1440-dark.png` | `/impeccable polish` | S |
| E3 | P3 | Texte de la carte « Documents » en retrait par rapport à son titre (encart dans la carte) | `executions-390-dark.png` | `/impeccable layout` | S |
| E4 | P3 | 30 cartes de 3–4 lignes de compteurs : la seule exécution en panne se repère, mais comparer deux jours demande de lire ; une ligne par exécution + détail dépliable suffirait | `executions-1440-dark.png` | `/impeccable distill` | M |

### Coque commune (sidebar, barre du haut, tab bar)

| ID | Prio | Problème | Capture | Commande | Effort |
|---|---|---|---|---|---|
| G1 | P2 | **En-tête de page-slogan sur les 6 vues** (surtitre capitales + titre 26 px + sous-titre ≈ 130 px) : AI slop n° 1, contraire à DESIGN.md, et coût vertical réel (T2) | toutes les captures 1440 | `/impeccable distill` | S |
| G2 | P2 | **Texte à 10 px hors échelle** dans 12 règles CSS, dont les libellés de la tab bar (téléphone) et, à 390 px, `.row-meta` = entreprise · lieu · contrat des lignes Offres | `offres-390-dark.png` | `/impeccable typeset` | S |
| G3 | P3 | « Rechercher p… » tronqué dans la sidebar de 232 px (le raccourci Ctrl K mange la place) | `offres-1440-dark.png` | `/impeccable layout` | S |
| G4 | P3 | Formats d'heure incohérents : « Instantané du 18 oct., 07:00 » (barre du haut, heure locale, sans année) vs « 18 oct. 2026, 09:00 UTC » (sidebar, UTC) vs « 18/10 » (Leads) | `offres-1440-dark.png`, `leads-1440-dark.png` | `/impeccable clarify` | S |
| G5 | P2 | **Tab bar à 6 onglets** (DESIGN.md en prévoit 5) aux libellés tronqués (« Candid. », « Exéc. ») ; « Relances à faire » n'existe pas sur téléphone ; le badge « 332 » recouvre l'icône. Regrouper Stats / Leads / Exécutions sous « Plus », badge de relances sur Candidatures | `offres-390-dark.png`, `breakui-500-offres-tri-390.png` | `/impeccable adapt` | M |
| G6 | P3 | « Mon espace / Tri » et « Espace personnel » simulent une profondeur et un multi-utilisateur qui n'existent pas. Non vérifié : la palette ne trouverait pas « relances » (signalé par la revue A, non reproduit ici) | toutes | `/impeccable distill` | S |

## 3. break-ui — ce qui casse

| Scénario | Vues | Résultat | Capture |
|---|---|---|---|
| Titres très longs (180 car., un mot de 128 car. sans coupure, raison sociale de 85 car.) | Tri, Offres, Candidatures | Aucun débordement horizontal (0 px). Liste Offres : ellipse propre + titre complet dans la fiche. **Cassé** : titre non borné dans la fiche (6 lignes à 26 px), la carte Tri (7 lignes à 390 px), la carte Kanban (8 lignes) et le bandeau de relance (4 lignes à 390 px) — le score passe sous la ligne de flottaison | `breakui-long-titles-*` |
| 0 offre | Tri, Offres, Candidatures, Statistiques | Pas d'erreur. **Cassé** : Offres dit « Le run de ce matin n'a rien collecté » alors que l'exécution a lu 533 offres (texte fixe, jamais confronté aux données) ; fiche vide « Sélectionne une offre… J et K… » sans rien à sélectionner ; « Trier les nouvelles » reste primaire et actif à 0 ; écran « Tri terminé » collé en bas de page | `breakui-empty-*` |
| 500 offres | Tri, Offres, Statistiques | Tient : 14 000 nœuds DOM, rendu initial ≈ 1,6 s (headless), frappe dans la recherche ≈ 33 ms, `j` ≈ 72 ms. Les 500 lignes sont toutes rendues (pas de virtualisation) — acceptable à ce volume, à surveiller au-delà | `breakui-500-offres-*` |
| Entreprise / lieu / contrat inconnus | Tri, Offres | Bon : « Entreprise non communiquée », « Contrat inconnu », « Années non précisées », pastille `?`. Seul défaut : les initiales viennent des premiers caractères bruts (« B< », « E1 ») | `breakui-unknown-company-*`, `offres-1440-dark.png` |
| API du Worker en panne (500) | Tri, Offres, Candidatures | Bandeau ambre + « Réessayer » : bien. **Cassé** : Candidatures affiche « 0 dossier suivi · 0 relance en retard · 0 entretien » et « Garde des offres dans Tri pour les voir ici » (inconnu présenté comme zéro) ; un 2e bandeau explique la cause à tort (« il demande le tableau de bord hébergé ») ; le compteur Tri passe de 1 à 3 (statuts inconnus) | `breakui-api-down-*` |
| Source en panne (France Travail, seed) | Exécutions | Bon : bandeau ambre « France Travail indisponible — clôtures suspendues : raison », compteurs « clôtures suspendues 12 » | `executions-1440-dark.png` |
| Pas de score IA | Tri, Offres | Rien ne casse ; l'absence est silencieuse (pas de « IA : pas d'avis »), ce qui reste cohérent tant que l'IA est optionnelle | `breakui-no-ai-*` |
| Zoom 200 % (≈ 720×450) | Tri, Offres, Candidatures | Pas de débordement. **Cassé** : chrome fixe (barre 56 px + en-tête de page + progression + barre d'actions + tab bar 64 px) : la carte Tri n'a plus que ≈ 100 px utiles, la liste Offres commence sous la ligne de flottaison | `zoom200-*` |

## 4. Détecteur Impeccable (`npx impeccable detect`)

**Statique** (`src/job_match/dashboard/assets`) — 2 findings :
- `side-tab` · `app.css:218` — liseré violet de 3 px de la ligne sélectionnée. **Voulu** : imposé par
  `JOB_MATCH_FOCUS.md` (« discreet 3px violet left edge »). À garder, ou à arbitrer contre le contrat.
- `overused-font` · `tokens.css:6` — Inter. **Voulu** (DESIGN.md, auto-hébergée). Pas d'action.

**URL** (12 scans, 6 vues × 1440/390, thème clair du navigateur headless) :

| Règle | Scans | Vérification |
|---|---|---|
| `kicker-above-heading` (slop) | 12/12 | **Confirmé** : un surtitre en capitales violet au-dessus de chaque `h1` |
| `undersized-ui-text` | 12/12 | **Confirmé** : 10 px sur `.side-label`, `.eyebrow`, `.tab-item` (libellés de la tab bar), `.score small`, `.score-tag`, `.score-ai`, `.record-crumb`… (12 règles CSS hors de l'échelle 11/12/13) |
| `tiny-text` (11 px de corps) | 8 | **Partiel** : `p.kb-dates`, `p.kb-follow`, `.stats-tile-sub`, `#last-run` — 11 px est le `--fs-xs` du système ; acceptable pour des métadonnées, pas pour « Relance le 19/10 · 1 j de retard » qui est l'information d'action de la carte |
| `nested-cards` (slop) | 7 | **Partiel** : carte dans colonne Kanban (motif de tableau, accepté) ; `section.ledger` dans la carte Tri, `article.run-ai` et `p.run-outage` dans une carte Exécutions, `details.record-desc` dans la fiche (empilements de bordures réels) |
| `low-contrast` | 4 | **Confirmé (P1)** : thème clair, scores des lignes déjà traitées (`.is-handled` → opacité 0,6) : 2,4 à 2,7:1 ; tick `forte 70` du relevé 3,3:1 |
| `skipped-heading` | 2 | **Confirmé** : Candidatures `h1` → `h3` |
| `text-overflow` | 1 | **Confirmé** : Leads 390 px, `span.tag.tag-pos` déborde de 111 px |
| `straggler` | 1 | P3 : « anciennes) » seul en fin de ligne (tuile Archivées) |

Mon script de mesure (contraste calculé sur chaque nœud texte visible, cibles tactiles, débordement)
confirme : **0 px de débordement horizontal partout, 0 erreur console** hors le 404 attendu de
`/api/documents/…/content.json` (document de fixture jamais rendu) et le 500 volontaire du
scénario « API en panne ».

## 5. « AI slop patterns » détectés

| # | Motif | Où | Verdict |
|---|---|---|---|
| 1 | **Surtitre slogan au-dessus de chaque titre** (capitales, interlettrage 0,14 em, violet) : « Décider vite, sans se tromper », « Ta recherche, organisée », « Suivre, relancer, avancer », « Mesurer pour ajuster », « Signaux de financement », « Ce que la machine a fait » | `.eyebrow`, 6 vues | Le tic n° 1 des UI générées ; contredit aussi DESIGN.md (« Don't use all-caps eyebrows »). À retirer ou à remplacer par une information (date du lot, état) |
| 2 | **Titre-accroche marketing sur une vue outil** : « Les opportunités qui comptent » pour la liste Offres, « Tri des nouvelles offres » + « Une opportunité à la fois » | `.page-top h1` | Le fil d'Ariane dit déjà « Offres » ; une vue de travail n'a pas besoin d'un slogan |
| 3 | **Micro-libellés en capitales espacées partout** (10 règles) | `.side-label`, `.controls-summary`, « Trier par », `.sort`, `th`, `.tcard-desc-title`, `.record-crumb`… | Uniformise tout au même ton « dashboard template » ; contredit DESIGN.md |
| 4 | **Liseré latéral coloré** sur l'élément sélectionné | `app.css:218` | Imposé par le contrat Focus — conscient, pas accidentel |
| 5 | **Cartes imbriquées** (bordure dans bordure) | relevé dans la carte Tri, IA et panne dans une carte d'exécution, description dans la fiche | Ajoute du bruit visuel sans hiérarchie |
| 6 | **Tuiles « gros chiffre + petit libellé »** | Statistiques (4 tuiles) | Léger : les valeurs sont honnêtes (« — », « aucune paire de dates »), mais la forme est le gabarit KPI générique |
| 7 | **Pastilles-monogrammes** comme faux logos | lignes Offres (« AC », « GA », « B< ») | Le contrat les tolère « only when legitimate » ; ici elles n'apportent aucune information et cassent sur des noms atypiques |
| 8 | **Police Inter** | partout | Signalé par le détecteur ; voulu par DESIGN.md, aucune action proposée |

Ce qui n'est **pas** du slop (vérifié) : pas de dégradé, pas de glassmorphism, pas d'emoji comme
icône, pas d'ombre décorative, couleur réservée aux états, chiffres tabulaires, copie française
spécifique au produit (« Années non précisées », « clôtures suspendues »).

## 6. `/impeccable audit` — santé technique

| # | Dimension | Score | Constat clé |
|---|---|---|---|
| 1 | Accessibilité | 3/4 | AA presque partout (focus visible, `aria-keyshortcuts`, régions live, `inert` sous l'overlay, statut = point + mot) ; **échec AA** sur les scores des lignes traitées en clair (O1) et les graduations du relevé (T3) ; cibles 36–40 px à 390 px (O3) ; `h1`→`h3` (C8) ; noms de boutons dupliqués (E2) |
| 2 | Performance | 3/4 | 500 offres tenues (33 ms par frappe, `j` 72 ms) ; animations sur `transform`/`opacity`, un seul `will-change` ciblé (`.tcard.is-dragging`) ; toutes les lignes rendues (14 000 nœuds à 500 offres), pas de virtualisation |
| 3 | Theming | 3/4 | Tokens partout (une seule couleur en dur : `app.css:370`), clair/sombre complets ; dérive typographique : 12 tailles à 10 px hors échelle (G2) ; l'opacité 0,6 des lignes traitées casse le contraste en clair (O1) |
| 4 | Responsive | 3/4 | 0 px de débordement horizontal sur 58 captures, tab bar + safe-area, fiche plein écran ; cibles < 44 px (O3), viewport court mal servi (T2), Kanban empilé à 390 px (C5), étiquette Leads qui déborde (L3) |
| 5 | Intégrité d'implémentation | 3/4 | Système cohérent et propre au produit (relevé du score, porte d'expérience, « clôtures suspendues ») ; dérives : surtitres en capitales contraires à DESIGN.md, cartes imbriquées, codes machine bruts (E1), deux affirmations fausses dans des états limites (O4, C1) |
| **Total** | | **15/20** | **Bon** — corriger les dimensions faibles, pas de refonte |

**Verdict d'intégrité : réussi.** Le tableau de bord exprime un système propre au produit
(relevé ligne à ligne, inconnu dit comme tel, couleur = état, raccourcis partout). Les écarts
mesurés sont localisés et listés dans `DESIGN.md` (section « recorded drift »).

**Motion** (hors périmètre de cette passe, noté pour `review-animations`) : `prefers-reduced-motion`
coupe tout d'un bloc (`app.css:1072`, `animation: none !important; transition: none !important`) ;
c'est sûr, mais Impeccable recommande une alternative qui garde le signal d'état (fondu court) plutôt
qu'une coupe globale. Les skills d'animation installés n'ont pas été lancés : la consigne demandait
critique, audit, detect et break-ui.

**Points forts à préserver** : 0 erreur console ; contenu externe toujours en `textContent` (la
sonde XSS s'affiche en clair) ; « Entreprise non communiquée », « Contrat inconnu », « Années non
précisées » ; bandeau de panne de source explicite avec sa raison et ses compteurs ; recherche et
navigation au clavier rapides à 500 offres ; contraste du thème sombre conforme partout mesuré.

## 7. `/impeccable critique` — revue design (Assessment A)

Méthode : Assessment A dans un sous-agent isolé (34 captures lues + parcours clavier en direct
sur le serveur de fixtures) ; voir §0 pour la provenance. Ses constats nouveaux ont été vérifiés
avant d'entrer dans les tableaux du §2 (O10 et T7 confirmés, O11 confirmé mais limité au chemin
de repli → P2, O12 ramené à un défaut visuel, la palette non reproduite).

**Spécificité du design — verdict : une structure pensée pour ce produit, sous un habillage
interchangeable.** Propre au produit : le relevé du score avec ses repères et sa phrase d'écart,
l'inconnu traité comme une valeur, la bannière de panne de source, la barre du Tri au-dessus de
la tab bar avec Annuler. Interchangeable : le schéma surtitre-slogan + h1 + sous-titre identique
sur 6 vues, les capitales partout, le fil d'Ariane « Mon espace / … » pour un seul utilisateur,
la grille de 4 tuiles KPI. Le détecteur (§4) confirme indépendamment le surtitre (12/12 scans).

| # | Heuristique | Note | Problème principal |
|---|---|---|---|
| 1 | Visibilité de l'état du système | 3 | Compteurs à 0 quand le suivi échoue (C1) ; curseur j/k ≠ fiche (O10) |
| 2 | Correspondance avec le monde réel | 2 | `not_relevant`, `contract`, `ats:`, `france_travail:GONE1`, « series a », « digest » |
| 3 | Contrôle et liberté | 3 | Z, Échap, Réessayer ; mais étape raison minutée 8 s et absente sur la dernière carte (T7) |
| 4 | Cohérence et standards | 2 | « J'ai postulé » / « Candidature envoyée » / « Envoyée » ; « lues » / « récupérées » ; séparateurs « - » / « · » |
| 5 | Prévention des erreurs | 2 | X/S/A sur une offre que la fiche ne montre pas ; « × » sans mot ; malus en vert (repli) |
| 6 | Reconnaissance plutôt que rappel | 3 | Puces `kbd` et aide `?` ; « Ton avis » sans touche, « digest » jamais défini |
| 7 | Flexibilité et efficacité | 3 | Raccourcis, palette, chords G ; rien pour une file de 332 offres |
| 8 | Esthétique minimaliste | 3 | Surfaces sobres ; slogans et relance répétée 4–5 fois |
| 9 | Diagnostic des erreurs | 3 | Les bannières disent quoi faire ; « le serveur a échoué », « HTTP 404 », fausse cause « tableau de bord hébergé » |
| 10 | Aide et documentation | 3 | Aide complète ; bandes et repères (digest, forte, IA) jamais expliqués |
| **Total** | | **27/40** | **Acceptable (haut de bande)** |

**Charge cognitive** : 4 échecs sur 8 à la checklist (focus unique, choix minimaux, mémoire de
travail, regroupement). Points de décision à plus de 4 options : barre d'outils d'Offres (≈ 15),
fiche (8 : 5 « Ton avis » + 3 actions), carte Candidatures (select à 6 statuts + 3 actions), tab
bar mobile (6).

**Parcours émotionnel** : le pic prévu (cascade du relevé) disparaît quand le relevé n'a qu'une
ligne ; la **fin** est le moment le plus faible — « Tri terminé » en bas d'un vide, un seul bouton
neutre, rien sur ce qui reste à faire aujourd'hui (T5). Moment à fort enjeu, « Candidature
envoyée » : le toast de relance rassure, mais l'échec « Non enregistré (le serveur a échoué) » ne
dit pas si quelque chose est perdu. Creux d'anxiété : 4 alertes ambre pour une seule relance ;
« 0 dossier suivi » lu comme une perte de données.

**Ce qui marche** : (1) l'inconnu traité comme une valeur jusque dans les cas limites ; (2) le
relevé du score lisible en une seconde, fermé, dans le Tri ; (3) un système clavier réellement
complet (←/→/Z/1–4, j/k/x/s/a/o, `/`, G + lettre, Échap, lien d'évitement en premier Tab).

**Personas**
- *Alex, expert clavier* : doit appuyer sur `O` avant chaque `A` pour être sûr (O10) ; aucune
  action groupée pour 332 offres ; « Ton avis » sans touche.
- *Sam, lecteur d'écran / zoom* : étape raison qui expire (T7) ; malus porté par la couleur, et la
  mauvaise (O11) ; point de Lead sans libellé (L4) ; capitales 10 px pénibles à 200 %.
- *Casey, mobile distraite* : rangée de tri à 36 px qui défile (O3, O8) ; relance sous la ligne de
  flottaison (C5) ; Écarter / Garder bien dans la zone du pouce.
- *Le propriétaire à 8 h 30 sur son téléphone, après le digest* : le lien ouvre `#tri`, un slogan
  passe avant la carte ; en panne d'API sur réseau mobile il lit « 0 relance » et ferme rassuré à
  tort (C1) ; après la dernière carte rien ne lui dit qu'une relance a un jour de retard.

**Questions à se poser**
1. Si le Tri finissait par « voilà ce qui reste aujourd'hui », une vue « Aujourd'hui » aurait-elle
   encore une raison d'exister ?
2. CLAUDE.md (règle 6) dit qu'un écart entre moteurs est un signal : pourquoi « IA 78 » est-il un
   chiffre de 10 px sous « 72 À tenter » plutôt qu'un écart affiché et expliqué ?
3. Un Kanban à 4 colonnes est-il la bonne forme pour 3 à 30 dossiers, quand la question
   quotidienne est « qui relancer, et quand ? »

## 8. Idée : une vue « Aujourd'hui »

**Données disponibles sans rien inventer** (toutes déjà chargées par la page) :

| Bloc | Source existante | Risque |
|---|---|---|
| À trier | `triage.js sidebarCounts` (compteur Tri) | aucun |
| Relances dues | `board.js dueKeys` (`follow_up_at` ≤ aujourd'hui) | dépend du suivi Worker |
| Documents prêts | `track.documents` (`status: ready`) pour les « À candidater » sans `sent_documents_version` | dépend du suivi Worker |
| Réponses à confirmer | `track.inbox.to_confirm` | dépend du suivi Worker |
| (en plus) Entretiens du jour, source en panne | `interview_at`, `runs[].outages` | aucun |

**Ce que ça dupliquerait** : le compteur Tri et « Relances à faire » de la sidebar, le bouton et la
ligne « 1 relance en retard » de Candidatures (déjà en trop, C2), l'écran de fin du Tri.

**Avis (convergent entre la revue A et l'audit) : oui à la fonction, non à une 7e vue.** La tab bar
a déjà un onglet de trop (G5) et le lien du digest ouvre `#tri`. Deux options, de la moins chère
à la plus complète :

1. **Recommandée — « Aujourd'hui » = l'écran de fin et l'état « file vide » du Tri.** Il liste
   les relances dues, les documents prêts non envoyés, les réponses à confirmer, chacun avec son
   action directe ; une ligne « Après le tri : 1 relance, 1 réponse » sous la progression. Corrige
   la fin ratée (T5), aucune route nouvelle, aucun onglet. Effort **M**. Commande :
   `/impeccable shape` (brief) puis `/impeccable onboard`.
2. **Vue d'accueil `#aujourdhui`** qui *remplace* (pas s'ajoute à) « Accès rapide » de la sidebar
   et les rappels de Candidatures, et prend la place de « Stats » dans la tab bar. Effort **L**
   (nouveau `today.js`, invariants de compteurs dans `worker/test/triage.test.mjs`, tests
   Playwright, ADR).

**Conditions dans les deux cas** : suivi indisponible ⇒ « — » et « suivi indisponible », jamais
« 0 » (sinon on recrée C1) ; tout à zéro ⇒ une phrase (« Rien d'autre aujourd'hui ») plus l'état
de la dernière collecte, pas de tuiles KPI ; pas de nouvelle alerte ambre.

## 9. Plan de correction proposé (après validation)

Ordre proposé, une commande = un commit, tests Playwright mis à jour et captures refaites après
chaque lot (rien n'est lancé avant ta validation) :

1. **[P1] `/impeccable harden` — Offres + Candidatures** : la fiche suit le curseur j/k à ≥ 1280 px
   (O10) ; « — » et « suivi indisponible » au lieu de 0 (C1) ; fausse cause « tableau de bord
   hébergé » retirée (T4) ; repli malus (O11) ; titres bornés à 3 lignes (T1, O5, C4) ; clé brute
   (C3) ; monogrammes (O7) ; étiquette Leads (L3) ; repli du relevé (T6) ; étape raison sans
   minuteur (T7).
2. **[P1] `/impeccable polish` — contraste** : scores des lignes traitées en clair (O1), titres
   `h2` (C8), noms des deux « Lancer maintenant » (E2), point de Lead (L4).
3. **[P2] `/impeccable distill` + `/impeccable quieter` — la coque** : supprimer les surtitres-
   slogans et le fil « Mon espace » (G1, G6), un seul primaire par écran (O2, C6), la relance dite
   une fois (C2), Exécutions plus compactes (E4).
4. **[P2] `/impeccable clarify` — les mots** : codes machine (E1), liste vide fondée sur le dernier
   run (O4), graduations (T3), « 0 % » (S3), vocabulaire « envoyée » (C9), « × » (O12), pluriels et
   « Série A » (L1, L2), heures en heure de Paris (G4), « Aujourd'hui » sur les cartes (C7).
5. **[P2] `/impeccable typeset`** : plancher 11 px, fin des capitales espacées hors `kbd` (G2, S2).
6. **[P2] `/impeccable adapt`** : cibles 44 px (O3), tri en un seul select sur téléphone (O8),
   en-tête repliable en viewport court (T2), Kanban mobile (C5), tab bar à 5 onglets (G5).
7. **[P2] `/impeccable layout`** : fin du Tri sous la progression (T5), graphe hebdomadaire (S1),
   recherche sidebar (G3), encart Documents (E3).
8. **(option) `/impeccable shape`** pour « Aujourd'hui » (§8), si tu dis oui.
9. **`/impeccable polish`** final, puis `/impeccable audit` et `/impeccable critique` relancés pour
   mesurer l'écart (cible : 18/20 et ≥ 32/40).

O9 (virtualisation à 500+ offres) reste en observation.

## 10. Questions pour ta validation

1. **Périmètre** : je corrige les **3 P1 seulement**, **P1 + P2** (≈ 25 problèmes, lots 1–7), ou
   **tout** y compris les P3 ?
2. **Surtitres et titres-slogans (G1)** : les **supprimer** (DESIGN.md les interdit déjà), les
   **remplacer par une donnée** (« Lot du 18 oct. · 3 nouvelles »), ou les **garder** et amender
   DESIGN.md ?
3. **Liseré violet de la ligne sélectionnée** (seul finding statique du détecteur) : le garder
   (contrat Focus) ou le remplacer par le seul fond violet pâle ?
4. **« Aujourd'hui »** : **option 1** (fin du Tri = agenda du jour), **option 2** (vue d'accueil
   qui remplace Stats dans la tab bar), ou **rien** pour l'instant ?
