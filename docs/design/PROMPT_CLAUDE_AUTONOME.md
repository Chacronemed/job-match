# Mission Claude Code — Refonte Job Match « Focus », exécution autonome

> À lancer dans **Claude Code Cloud (claude.ai/code)** après extraction du pack à la racine du dépôt cloné depuis GitHub (avec les chemins `docs/design/...`). Le dépôt est déjà cloné par la session cloud ; aucun PC local ni clone local n’est requis. Ce message est une instruction explicite pour **UN SEUL chantier autonome de refonte UI/UX**, jusqu'à l'implémentation, les tests, la documentation et la publication d'une branche dédiée. N'attends pas de validation intermédiaire. Ne demande pas de décider d'une direction artistique : elle est imposée.

## 0. Rôle, mandat et ordre de priorité

Tu es simultanément **Senior Product Designer, Design Engineer, Frontend Engineer Vanilla JS, QA Playwright et mainteneur Git**. Tu dois prendre en charge une refonte de bout en bout de mon projet personnel Job Match, conçu pour m'aider à décrocher un emploi DevOps en France et servir de portfolio.

Je ne sais pas juger ni concevoir une bonne UI/UX. Tu n'as donc PAS pour mission de proposer un choix de designs : **la direction “FOCUS” a déjà été décidée et les cinq captures du dossier `docs/design/references/job-match-focus/` sont les références obligatoires**. L'objectif est une application belle, professionnelle, rapide, claire, opérationnelle, sans perdre ses fonctionnalités.

**Ordre de priorité en cas de conflit :**
1. Sécurité, absence de fuite de données, comportement métier exact, stabilité des API et des actions.
2. Préservation des fonctionnalités existantes et des tests.
3. Design imposé par `docs/design/JOB_MATCH_FOCUS.md` et les captures ; éviter de réinterpréter le concept.
4. Accessibilité, performance, responsive, qualité du code.
5. Finition visuelle.

**Livrable attendu avant de terminer :** code fonctionnel, captures réelles du résultat, tests exécutés, commits propres, branche distante poussée si possible, synthèse `docs/design/FOCUS_DELIVERY.md`. **Ne fais pas uniquement un audit, une liste de recommandations, un prototype isolé ou des fichiers CSS sans intégration.**

## 1. Démarrage obligatoire : comprendre l'existant sans perdre de temps

1. `git status --short --branch`, branche courante, `git remote -v`, dernière entrée de `docs/PROGRESS.md`.
2. Lis de façon ciblée : `CLAUDE.md`, `docs/design/DESIGN.md`, `docs/design/JOB_MATCH_FOCUS.md`, `docs/adr/0021-dashboard-js-split-one-row-light-mode.md` si présent (sinon trouve l'ADR 0021), `docs/ARCHITECTURE.md` (section dashboard seulement), `.github/workflows/ci.yml`, `pyproject.toml`.
3. Ouvre/inspecte impérativement les 5 images :
   - `docs/design/references/job-match-focus/01-offres-1440x900.png`
   - `docs/design/references/job-match-focus/02-candidatures-1440x900.png`
   - `docs/design/references/job-match-focus/03-offres-390x844.png`
   - `docs/design/references/job-match-focus/04-tri-390x844.png`
   - `docs/design/references/job-match-focus/05-fiche-390x844.png`
   Le fichier `reference.html` est une maquette VISUELLE statique. Elle aide à reproduire les espacements et les proportions mais ne contient aucune logique métier et **ne doit pas être copiée dans le produit avec ses données fictives**.
4. Inspecte l'implémentation actuelle dans `src/job_match/dashboard/assets/` : `index.template.html`, `tokens.css`, `app.css`, `dashboard.css`, `app.js`, `list.js`, `tri.js`, `board.js`, `leads.js`, `runs.js`, `why.js`, `score.js`, `palette.js`, `tracking.js`, `triage.js`, `ui.js`; lis `src/job_match/dashboard/render.py`, les tests de `tests/unit/browser/` et `tests/unit/dashboard/` utiles à ta modification.
5. Identifie les contrats DOM réellement utilisés par les tests et le JS : `id`, `data-*`, `aria`, hash, formulaires, événements, sélecteurs, ordre de chargement, objets `window.JM`, fragments et CSP. Prépare un inventaire interne et évite de casser ces contrats. Si un sélecteur doit évoluer, mets à jour tests et JS de façon cohérente, pas en supprimant le test.
6. Prends une capture de l'existant avec les fixtures via les helpers Playwright et garde-la dans `docs/design/screenshots/focus/before/` sans donnée personnelle. **Ne teste pas avec la base de prod ni avec des identifiants réels.**

### Politique Git : préserver absolument le travail qui existe déjà

- Le dépôt cloné dans le cloud peut contenir des changements de session, ou avoir des modifications non committées ; **ne le perds jamais**. Interdits : `git reset --hard`, `git clean -fd`, stash automatique sur le dépôt utilisateur, rebase destructeur, force-push, suppression de branche, changement non autorisé de la branche `main`.
- Le pack de référence nouvellement extrait dans `docs/design/JOB_MATCH_FOCUS.md`, `docs/design/PROMPT_CLAUDE_AUTONOME.md`, `docs/design/references/job-match-focus/` est considéré comme **un ajout intentionnel lié à cette mission**, pas comme un conflit. Tu peux l'inclure dans les commits.
- Dans une session cloud, utilise la branche de travail automatiquement créée par Claude Code, sauf si elle n’existe pas : dans ce cas crée une branche dédiée depuis le HEAD courant. N’essaie pas de changer de branche si cela risque de casser la publication automatique. Nom recommandé : `feat/ui-focus-redesign` (ou suffixe non destructif si le nom existe).
- S'il existe d'autres fichiers sales, ne les écrase pas. Crée un **git worktree** sur une nouvelle branche depuis le HEAD et copie seulement les fichiers du pack dans ce worktree ; travaille dans ce worktree. Les changements locaux préexistants restent dans le dossier initial. Si un worktree est impossible, arrête avant toute opération risquée, rédige le blocage et ne pousse rien.
- Si aucun dépôt Git, aucune origine `origin` ou aucune authentification ne sont disponibles, réalise et teste dans la VM cloud, puis rapporte clairement que le push est impossible. Ne fabrique pas de succès.

### Dérogation explicite à CLAUDE.md pour CETTE mission

`CLAUDE.md` dit normalement « un milestone puis attendre », « ne jamais git add/commit/push ». **Je t'autorise explicitement, pour cette seule mission Focus, à exécuter tous les lots décrits ci-dessous sans attendre ma validation, à `git add` sur liste de fichiers, `git commit` et `git push -u origin <branche-dédiée>`**, dans les limites strictes de la politique Git ci-dessus. Cela **n'autorise PAS** un merge, un déploiement, un push sur `main`, une modification de secrets ou une écriture dans des services de production. Les autres règles de `CLAUDE.md` restent valables.

## 2. Direction visuelle NON NÉGOCIABLE : Focus

Lis entièrement `docs/design/JOB_MATCH_FOCUS.md`. C'est le contrat de design. Reproduis fidèlement ses **compositions, proportions, traitements des surfaces, couleurs et hiérarchies**.

- **Style** : application de productivité sombre, sobre, dense et haut de gamme. Équivalent en qualité de finition aux références Linear (listes), Attio (fiche détaillée), Huntr (pipeline), sans copie de marque.
- **Palette imposée** : fond `#111113`, surface `#18191b`, raised `#212225`, texte `#edeef0`, secondaire `#b0b4ba`, discret `#91959e`, violet principal `#6e56cf`, violet clair `#baa7ff`. Green/amber/red/blue UNIQUEMENT pour informations sémantiques. Si les tokens existants correspondent déjà, **réutilise-les**.
- **Typographie** : Inter Variable déjà auto-hébergée ; base 13px, titres 26px desktop et 23px mobile, numérique tabulaire. N'installe pas de police externe. Lucide existant. Rayon 6/8/11px, bordures fines, pas de gradients, pas d'effets glass, pas de grosses ombres.
- **Desktop** : sidebar 220–232px, en-tête 63–64px, marges ~29px, gap panneaux 16px ; vue Offres en split view avec colonne de détails 404–440px et liste qui prend le reste à partir de ~1280px.
- **Mobile** : bottom nav 5 vues, vraie largeur utile, actions Tri au-dessus de la nav, fiche offre plein écran, retour listant état et position ; aucun scrolling horizontal du body.
- **Light mode** : le thème clair existant doit rester utilisable et accessible, même si le design de référence illustre seulement le sombre ; adapter les mêmes composants, pas un second produit.
- **No alternative aesthetics** : ne propose pas A/B, pas de « nouvelles idées » de styles, pas de landing page, pas de dashboard KPI plein de cartes, pas de home supplémentaire, pas d'illustrations artificielles, pas d'effets juste pour impressionner.

**Nuance fondamentale** : Les nombres, entreprises et extraits dans les PNG sont des **données de démonstration fictives**. Utilise exclusivement les vraies données déjà exposées par l'app ; ne fabrique pas de scores, dates, disponibilités ou conclusions IA. Les libellés de démo ne définissent pas la structure de la base. Un champ absent s'affiche comme absent ou inconnu.

## 3. Périmètre fonctionnel et écrans à livrer

### Lot 1 — Offres desktop + fiche d'offre (priorité absolue)

- Reproduis `01-offres-1440x900.png` : tête de page, recherche visible, segments/compteurs issus de vraies données, liste lisible de titres d'offres, entreprise/localisation/contrat, score réel + mot descriptif, ligne sélectionnée discrètement violette, panneau détails continu à droite.
- Panneau détails : description, données d'éligibilité et de score, preuves concrètes via le **Relevé du score** existant (`why.js`), correspondances positives/négatives, expérience explicite, IA présentée distinctement, alertes si réellement fondées. Actions existantes : consulter l'annonce, garder/écarter, dossier de candidature, modification de statut, notes, génération CV/lettre si applicable. Les fonctionnalités non visibles sur la référence sont accessibles par des onglets, détails ou menu secondaire, sans suppression.
- Conserve impérativement recherche, filtres par section/département/source et ATS/IA/statut/score, tri, densité dense/confortable, filtres encodés dans hash et persistance existante, clavier `j/k/x/s/a/Enter/Space/o///?`, états optimistic/rollback et undo. Évite les shortcuts dans les inputs.
- Clic ligne = sélection et détail (ou comportement équivalent intuitif) ; clic sur véritable lien externe reste un lien, pas une mutation. Ne casse pas les deep-links `#...?...fiche=...`.
- La fiche actuelle `#record` peut être réutilisée/repositionnée si c'est le chemin le moins risqué. Évite de réécrire ses actions métier ; change le rendu et la composition. Sur tablette, le panneau devient drawer, sans couper ni liste ni contrôles.

### Lot 2 — Offres mobile + Tri desktop/mobile

- Reproduis `03-offres-390x844.png`, `05-fiche-390x844.png`, `04-tri-390x844.png` ; pour le desktop de Tri, même esthétique avec vraie carte centrée ~680–760px de largeur et espace exploité, jamais une carte minuscule isolée.
- Mobile : bottom tabbar, app header, search, filtres accessibles, score lisible, fiche plein écran avec retour, scroll préservé ; aucune action derrière une barre fixe, touches >=44px, `env(safe-area-inset-bottom)`.
- Tri : 1 annonce à la fois, progression réelle, résumé utile, `Relevé du score` exact, phrases sourcées, éligibilité réelle, actions Écarter / Annuler / Garder avec raccourcis et gestion d'échec. Respecte les deux flux Tri et Offres, qui ne sont pas identiques.

### Lot 3 — Candidatures desktop/mobile et interactions existantes

- Reproduis `02-candidatures-1440x900.png` pour densité/typographie/colonnes/cartes. **Ne remplace pas les statuts réels de `board.js` par les états fictifs des maquettes**. Les vraies colonnes peuvent différer : dispose-les en Kanban accessible avec défilement horizontal contrôlé si nécessaire.
- Suivi : statut, date d'envoi, dernière action, prochaine relance, inbox recruteurs, liste vs Kanban, notes, pièces, documents, régénération et téléchargement PDF/DOCX, kit de réponses et fonctionnalités `apply` existantes : tout reste fonctionnel, y compris leurs états d'erreur.
- Une relance en retard est visible mais pas une énorme bannière rouge. États vides qualitatifs, textes utiles sans inventions et aucun faux CTA.
- Pour mobile, colonnes par défilement/groupe ou vue liste adaptée — choisis le **comportement responsive le plus simple** qui préserve les actions ; la direction visuelle reste figée.

### Lot 4 — Leads / Exécutions et cohérence globale

- Même design tokens, barres de filtres, densité, états vides et chargement, typographie et badges.
- Leads = signaux de financement, pas annonces d'emploi. Maintien des liens et de la relation vers les offres réelles de l'entreprise.
- Exécutions : chiffres et statuts de collecte réels, rerank IA et documents, erreurs clairement textuelles, données absentes explicites, pas de graphiques/KPI inventés.
- Modal d'aide, palette de commandes, toast, banner, filtres, mode clair, PWA, navigation mobile, raccourcis, affichages inactifs et responsive doivent être harmonisés.

## 4. Contraintes architecturales et sécurité

- **AUCUN framework frontend** ajouté : reste en HTML/CSS/JS vanilla, namespace `window.JM`, montage des CSS/JS et hash CSP via `src/job_match/dashboard/render.py`. Pas de React/Vite/Next/Tailwind, pas de changement de contrat API, de migrations DB, de microservices, de refonte du backend.
- Ne modifie pas les endpoints Cloudflare ni les mécanismes d'authentification/Cloudflare Access. Ne change pas CSP pour désactiver une protection. Aucun CDN ou script distant ; pas de tracking/analytics externe.
- Ne modifie pas le scoring métier, les filtres d'éligibilité, le pipeline de collecte, les fichiers privés, les secrets, la config de production ou les Workflows GitHub. Le périmètre est UI + tests/docs nécessaires à cette UI.
- Ne fais **aucune écriture dans la production**, ne déclenche ni `wrangler deploy`, ni migration D1 distante, ni pipeline quotidien, ni application réelle, ni envoi mail. Pas de test sur vraies données. Pas de capture publique du vrai CV/PII/offres privées. Tests avec fixtures et routes mocked.
- S'il faut installer des dépendances pour exécuter les tests : utilise d'abord les environnements existants ; sinon installe **uniquement** les dépendances de développement déclarées (`pip install -e '.[dev]'`, `npm ci --prefix worker`, navigateur Playwright/Chromium selon besoin) ; respect de la plateforme OS. Ne télécharge ni modèle IA ni outil design non nécessaire. Évite les modifications lockfiles uniquement dues à l'environnement.
- Ne fais pas de « redesign » par ajout de CSS override infini. Rationalise plutôt les règles existantes, factorise les éléments visuels, supprime uniquement du code confirmé mort, puis re-teste les 5 vues.

## 5. Procédure autonome (tu ne m'interromps pas entre les lots)

**Étape A — Audit rapide et baseline** : lecture ciblée, inventaire fonctionnalités, screenshot avant, exécution des tests pertinents et note des échecs déjà présents. Ne t'arrête pas après audit.

**Étape B — Architecture UI et tokens** : définis une intégration minimale sans casser les `id` et handlers. Réorganise layout + navigation + panneau record + styles communs, en gardant le thème clair. Vérifie rendu et console.

**Étape C — Implémenter lot 1 Offres** : vraie capture desktop à 1440×900 avec fixtures. Compare visuellement à `01-*`. Corrige les écarts concrets (taille sidebar, panel, densité, sélection, header, lisibilité). Fais 2 passes de critique/révision minimum. Ajoute/répare tests de sélection, actions, filtres et deep-links.

**Étape D — Implémenter lot 2 Offres mobile + Tri** : captures à 390×844 (liste, fiche, tri). Vérifie tactile, raccourcis, barres fixes, scroll, absence d'overflow. Deux passes visuelles minimum. Ne masque aucune fonctionnalité pour réussir une capture.

**Étape E — Implémenter lot 3 Candidatures** : vraie capture Kanban 1440×900, et mobile. Teste toutes les interactions couvertes par `tests/unit/browser/test_candidatures.py`, `test_download_speed.py`, `test_inbox.py`, `test_answer_kit.py`, `test_apply_button.py` et analogues. Deux passes visuelles minimum.

**Étape F — Harmoniser Leads / Exécutions et système** : vise la cohérence et la clarté, pas une refonte métier. Vérifie tous les panneaux et les états vides/erreurs.

**Étape G — QA complète et corrections** :
- Exécute les mêmes familles de validations que `.github/workflows/ci.yml` avec l'OS et l'environnement disponibles : `ruff check .`, les tests pytest hors navigateur/worker, puis les tests browser/worker, les tests Node nécessaires. Sur Windows utilise `.venv\Scripts\...`, sur Unix `.venv/bin/...` ou les commandes de la venv active. Si `pytest-xdist` présent, `-n auto` comme CI ; sinon `pytest -q` et signale la différence.
- Exécute les tests navigateur sur fixtures/routes mockées ; pour chaque vue (Tri, Offres, Candidatures, Leads, Exécutions), en desktop et mobile, détecte `console.error`, erreurs JS, requêtes inattendues, overflow horizontal, recouvrement d'actions, pertes de focus et dysfonctionnements de navigation.
- Ajoute des tests UI ciblés sur **split-pane responsive**, conservation des filtres et focus à l'ouverture de la fiche, état mobile retour, menu/onglets, tri/undo, tableau/kanban, thème clair, erreurs d'API et texte d'éligibilité inconnu. Ne transforme pas les tests en simples `assert True`.
- Évalue le contraste WCAG AA pour textes essentiels et les focus visibles ; vérifie `prefers-reduced-motion`, clavier seul, 390×844, 768×1024, 1024×768 et 1440×900.
- Si un test existant échoue, diagnostique la cause. Corrige toute régression créée ; distingue clairement les échecs préexistants/des dépendances indisponibles. Ne supprime ni skippe artificiellement un test pour afficher du vert.

**Étape H — Captures finales et rapport** :
- Enregistre dans `docs/design/screenshots/focus/after/` des captures **de l'app réelle avec données fictives des fixtures**, avec au moins : `offres-1440-dark.png`, `candidatures-1440-dark.png`, `tri-1440-dark.png`, `offres-390-dark.png`, `offre-detail-390-dark.png`, `tri-390-dark.png`, `offres-1440-light.png` ; captures supplémentaires utiles pour Lead/Runs.
- Crée `docs/design/FOCUS_DELIVERY.md` avec : architecture UI, avant/après, décisions d'intégration, fonctions préservées, captures et emplacement, résultats de chaque famille de tests (nombre, échecs, skips), bugs corrigés, limitations honnêtes, captures restées différents des références et raisons, liste des commits, branche/remote/PR si possible.
- Mets à jour `docs/PROGRESS.md` brièvement en ajoutant la livraison Focus, sans effacer l'historique ou les autres chantiers.

**Étape I — Git et publication du travail** :
1. Vérifie `git diff --check`, `git status`, `git diff --stat` ; inspecte précisément chaque fichier à committer ; fais une vérification qu'aucun `.env`, credentials, données réelles, `private/`, `*.sqlite`, screenshot PII, `node_modules`, `venv`, trace ou gros fichier temporaire ne sera inclus.
2. `git add` **uniquement** les fichiers autorisés : dashboard frontend modifié, tests concernés, `docs/design/` nécessaires (avec captures de fixtures et pack de référence) et `docs/PROGRESS.md`.
3. Fais 2 à 4 commits logiques selon le travail (ex.: `feat(ui): add Focus split view for offers`; `feat(ui): refine triage and application boards`; `test(ui): add responsive interaction coverage`; `docs(ui): record Focus screenshots and delivery`). Le premier commit peut contenir les références visuelles.
4. Termine par `git push -u origin <ta-branche-de-session-ou-dédiée>` **uniquement**, à condition que le remote soit correct et l'authentification disponible. **Ne pousse PAS sur `main`**, ne force-push pas, ne déploie pas, ne merge pas. Si `gh` est déjà installé et authentifié, tu peux éventuellement créer une **PR en brouillon**, sans activer la fusion automatique et sans merge ; sinon rapporte l'URL de la branche distante si disponible.
5. Si push échoue pour une raison extérieure, garde les commits dans la VM de session, consigne la commande de push nécessaire et l'erreur. Ne sollicite jamais mes identifiants ni ne contourne des protections.

## 6. Règles anti-dérive et auto-contrôle

- Ne demande pas « quelle direction préfères-tu ? » : Focus est définitif.
- Ne reviens pas me demander une validation après audit, maquette, écran 1 ou lot 2 ; avance jusqu'à la livraison des lots et tests dans cette session.
- Ne remplace jamais un vrai écran par une image statique. Les PNG sont des *blueprints* ; seules les données et actions réelles doivent alimenter le résultat.
- Ne considère pas une capture « jolie » comme un test. Capture, inspecte, corrige, puis fais un test d'interaction.
- Ne redéfinis pas les statuts métier selon les données fictives des exemples.
- Ne sacrifie ni ergonomie mobile ni fonctionnalité pour reproduire exactement un pixel de la maquette ; note les compromis dans le rapport.
- Ne change pas `CLAUDE.md` juste pour supprimer ses limites : la dérogation Git de cette mission est explicite dans ce prompt uniquement.
- Ne dépense pas le temps disponible à explorer des outils, ajouter des skills ou comparer dix applications : les références et le design sont déjà fournis. Les compétences `frontend-design`, `web-design-guidelines`, Playwright peuvent être utilisées ponctuellement, mais **n'utilise pas `design-taste-frontend`** (ciblé marketing).
- Ne prétends pas avoir testé ce que tu n'as pas exécuté. Ne prétends pas avoir poussé sans réponse `git push` réussie.

## 7. Définition de FINISH

L'exécution est terminée quand :
- Les cinq vues fonctionnent, le parcours critique « trouver → comprendre le score → garder → préparer / suivre » fonctionne sur données de test.
- L'interface est visuellement proche de la composition des références sur desktop et mobile, avec le thème clair et l'accessibilité conservés.
- Les tests et captures sont produits, les régressions résolues ou documentées honnêtement.
- Les changements sont committés sur **une branche dédiée**, puis poussés sur `origin` si autorisé et techniquement possible, SANS déploiement ou merge.
- `docs/design/FOCUS_DELIVERY.md` contient un récapitulatif vérifiable de l'exécution.

**Maintenant : commence l'étape A, puis enchaîne B → I sans attendre une réponse de ma part.**
