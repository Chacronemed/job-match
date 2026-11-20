# Workday : moins d'appels, sans contourner la protection — 20 novembre 2026

- **Date :** 2026-11-20, après le Daily run n° 96 (19:29 → 19:44 UTC, première collecte avec
  la PR #27).
- **Suite de** [`2026-11-20-coverage.md`](2026-11-20-coverage.md).
- **Règle :** la page « Security Check » de Workday est une protection anti-robot. Elle n'est
  **pas contournée** : pas de rotation d'IP ni de proxy, pas de navigateur headless, pas
  d'en-têtes de navigateur. Le projet réduit seulement ses appels.
- **Tests :** sur fixtures uniquement. La simulation du § 2 tourne dans
  `tests/unit/adapters/test_workday_budget.py`, sans aucun appel réseau.

## 1. Ce que le run n° 96 a montré

| | Run n° 95 (avant la PR #27) | Run n° 96 |
|---|---|---|
| Durée de la collecte | 37 min | 15 min |
| Temps passé sur Workday | 25 min | 4 min |
| Offres Workday lues | 112 | 8 |
| Boards Workday sans aucune offre lue | 7 sur 10 | **10 sur 11** |
| Vérifications de clôture sans réponse (`errors`) | 28 | 17 |
| SmartRecruiters | 335 offres lues | 535 (Sopra Steria 100 sur 1 004, Inetum 100 sur 357) |
| Air France (flux Talentsoft) | — | 20 |

Les onze tenants ont reçu la page « HTTP 429 (security check page) ». Dix n'ont rien donné ;
Equinix a livré 8 fiches sur 10 avant d'être refusé à son tour. Le projet réessayait encore
chaque appel deux fois : 41 requêtes refusées, contre une protection qui ne cède pas.

## 2. Appels Workday avant / après

Simulation sur fixture (`tests/fixtures/workday_simulation.json`) : les onze boards de
`config/ats_boards.yaml` avec le nombre d'offres en France que chacun annonçait le
20 novembre, des offres générées à partir de vingt titres inventés. Le même faux serveur
répond aux deux politiques, sur sept runs quotidiens.

- **Avant** : tout le listing France chaque jour (plafond 100 offres par board), une fiche
  par offre. C'est ce qui tournait jusqu'au 15 novembre, quand Workday répondait.
- **Après** : les réglages de `config/settings.yaml`.

| Board | Offres en France | Avant, par semaine | Après, semaine 1 | Après, semaine 2 |
|---|---:|---:|---:|---:|
| Airbus | 817 | 742 | 15 | 15 |
| Thales | 2 000 | 742 | 15 | 15 |
| Sanofi | 121 | 742 | 15 | 15 |
| Renault Group | 363 | 742 | 15 | 15 |
| Air Liquide | 306 | 742 | 15 | 15 |
| Michelin | 214 | 742 | 15 | 15 |
| Accenture | 211 | 742 | 15 | 15 |
| Kyndryl | 9 | 77 | 9 | 5 |
| Euronext | 38 | 287 | 13 | 5 |
| Equinix | 10 | 84 | 9 | 5 |
| Murex | 11 | 91 | 9 | 5 |
| **Total** | | **5 733** | **145** | **125** |

**5 733 appels par semaine avant, 145 après : 97,5 % de moins.** Par run : 819 appels sur
onze tenants avant, 15 à 30 appels sur un ou deux tenants après. Le maximum possible est de
165 par semaine (onze boards au plafond).

D'où vient la baisse :

| Mesure | Effet sur un grand board (Thales) |
|---|---|
| Recherche par mot-clé au lieu du listing | 5 pages de listing → 4 recherches |
| Fiche seulement si le titre est dans la cible et l'offre pas encore en base | 100 fiches → 10 au plus |
| Plafond de 15 appels par tenant et par run | 106 appels → 15 |
| Une lecture par semaine au lieu d'une par jour | × 1/7 |

La semaine 2 montre l'effet de `skip_known` : un petit board dont tout est déjà en base ne
coûte plus que ses cinq appels de recherche, et sur un grand board les dix fiches vont aux
offres suivantes, pas aux mêmes.

## 3. Ce qui change dans le code

Réglages dans `config/settings.yaml`, bloc `sources.ats` :

| Réglage | Valeur | Rôle |
|---|---|---|
| `search_keywords` | `[devops, cloud, sre, platform]` | recherche côté API, Workday et SmartRecruiters |
| `title_prefilter` | `[workday]` | pas de fiche pour un titre hors cible |
| `workday.max_calls_per_run` | `15` | plafond par tenant et par run, réessais et clôtures compris |
| `workday.frequency_days` | `7` | une lecture par semaine ; surcharge possible par board (`frequency_days` dans `ats_boards.yaml`) |
| `workday.skip_known` | `true` | pas de fiche pour une offre déjà en base |

- **Recherche filtrée.** Workday : un appel pour la facette pays, puis un `searchText` par
  mot-clé avec la facette France (ou les lieux français quand le tenant n'a pas de facette
  pays). Mesuré le 20 novembre : Workday lit plusieurs mots comme un ET (« devops » 174
  offres, « devops cloud sre platform » 13), d'où un appel par mot-clé. Une page de 20 par
  mot-clé, pas plus.
- **Fiche seulement si utile.** Le titre doit être dans la famille cœur ou proche
  (`title_relevance`) et ne pas être un poste de développeur ; la localisation est garantie
  par le filtre France de la recherche. Les offres les plus récentes passent d'abord
  (`postedOn`), car la recherche trie par pertinence.
- **Plafond.** Chaque requête compte. Au plafond, le tenant s'arrête : statut « OK, plafond
  d'appels atteint ».
- **Fréquence.** Le board en position *i* parmi les boards Workday est lu le jour *i* modulo
  7 : deux tenants par jour au plus, toujours le même jour pour un board. Aucun état à
  garder ; un run manqué coûte une semaine à ces deux boards.
- **Page de sécurité.** Arrêt immédiat du tenant pour le run, sans réessai, compté dans
  `workday_blocked`. Une même page servie en 403 est traitée pareil. Un vrai 429 de quota,
  un 5xx ou un timeout restent réessayés (dans la limite du plafond).
- **Clôtures.** Un board sauté ou bloqué ne dit rien de ses offres : la vérification répond
  « non demandé », ce n'est plus compté dans `errors`. Une offre Workday n'est donc
  vérifiée qu'une fois par semaine, dans la limite du plafond ; la limite d'âge de 45 jours
  reste le filet.

### Résumé du run

Chaque board Workday a un statut, affiché dans le résumé de la CLI, le résumé du job GitHub
et la page Exécutions :

```
workday:    1 OK · 9 sautés par fréquence · 1 bloqué anti-robot  (16 calls)
workday blocked (anti-robot, not retried): 1
  Airbus           bloqué anti-robot · 1 calls, 0 listed, 0 read
  Thales           sauté par fréquence (prochaine lecture dans 3 j)
  Sanofi           OK · 15 calls, 34 listed, 10 read
```

Statuts : OK · OK, plafond d'appels atteint · sauté par fréquence · bloqué anti-robot · erreur.

## 4. SmartRecruiters

- **Pagination** `offset` / `limit` : elle existait (pages de 100) ; elle est maintenant
  testée sur trois pages.
- **Filtre** : `country=fr` et `q=devops cloud sre platform`. Mesuré le 20 novembre sur
  l'API publique : `q` lit plusieurs mots comme un OU (« devops » 107, « cloud » 258,
  « devops cloud » 291 sur les 1 004 offres françaises de Sopra Steria), donc une seule
  requête par page. Le plafond de 100 offres par board et par run reste : ce sont désormais
  100 offres qui parlent du sujet, plus les 100 dernières publiées.
- **Filtre titre non activé pour SmartRecruiters.** Mesuré sur la collecte de 16:24 : il
  éviterait 78 % des fiches (335 → 74) mais ferait perdre 1 des 8 offres SmartRecruiters qui
  atteignaient le Tri (« Architecte / Ingénieur Dynatrace », titre hors familles, bonnes
  compétences). SmartRecruiters n'est pas bloqué : je n'ai pas pris ce risque sans toi. Pour
  l'activer : `title_prefilter: [workday, smartrecruiters]`.

Identifiants à 0 offre :

| Board | Constat | Décision |
|---|---|---|
| Dailymotion (`dailymotion`) | L'identifiant est le bon : la page carrière renvoie vers `smartrecruiters.com/Dailymotion/…` et la fiche lue directement porte cet identifiant. Mais l'API publique ne liste aucune offre (0 avec ou sans filtre pays) et la fiche est `active: false`. L'ancien board Lever répond 404. | Gardé (un appel par run). À retirer si tu préfères. |
| Cegid (`cegid`) | L'identifiant existe : une seule offre, au Canada. Aucune en France. Le site `careers.cegid.com` est injoignable d'ici ; Cegid éditant Talentsoft, c'est probablement un site Talentsoft. | Gardé. À vérifier depuis ton poste : si `careers.cegid.com/handlers/offerRss.ashx?LCID=1036` répond, une ligne `talentsoft` suffit. |

## 5. Entreprises Workday encore bloquées

Au run n° 96, la page de sécurité a été servie aux onze tenants :

| Entreprise | Résultat du run n° 96 |
|---|---|
| Airbus | bloqué au premier appel |
| Thales | bloqué (0 fiche lue) |
| Sanofi | bloqué au premier appel |
| Renault Group | bloqué au premier appel |
| Air Liquide | bloqué au premier appel |
| Michelin | bloqué au premier appel |
| Accenture | bloqué au premier appel |
| Kyndryl | bloqué au premier appel |
| Euronext | bloqué au premier appel |
| Murex | bloqué au premier appel |
| Equinix | partiel : 8 fiches sur 10, puis bloqué |

Tant que la protection est servie au client du projet, **ces onze entreprises ne sont pas
couvertes par la collecte**. Elles le seront plus tard par des alertes email via n8n ; rien
n'est codé pour ça dans cette PR. D'ici là, le résumé de chaque run dit lesquelles ont
répondu.

Avec la nouvelle politique, un tenant bloqué coûte **un appel par semaine** au lieu de trois
par jour. Si le blocage cesse, la collecte reprend d'elle-même, à quinze appels par tenant et
par semaine.

## 6. Limites à connaître

- **Découverte plus lente.** Dix fiches par tenant et par semaine : un grand board met
  plusieurs semaines à livrer tout ce que ses recherches listent. C'est le prix du plafond.
- **Une seule page par mot-clé**, triée par pertinence : une offre au-delà des vingt
  premières réponses d'un mot-clé n'est pas vue.
- **« cloud » ramène beaucoup** (2 000 réponses chez Thales, le maximum affiché) : le filtre
  titre fait le tri, mais les vingt premières réponses de ce mot-clé ne sont pas toujours les
  plus utiles.
- **Une offre déjà en base n'est plus relue** : si son texte change, la base garde l'ancien.
- **La fréquence est sans état** : deux runs le même jour lisent deux fois les mêmes tenants.
