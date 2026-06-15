# Brief design — Refonte graphique de la vue "Legacy KB"

> Document destiné à un outil de génération de maquettes (Figma AI, Stitch, etc.) pour
> proposer des pistes de modernisation visuelle de la page "Legacy KB" de l'application
> **NotebookLM Azure**. Décrit l'état actuel (layout, composants, design system) ainsi
> que les objectifs et contraintes de la refonte. Aucune intention de changer les
> fonctionnalités — uniquement l'habillage visuel.

---

## 1. Contexte produit

**NotebookLM Azure** est une application de RAG documentaire (type "NotebookLM") avec
deux vues principales, accessibles via un switch en haut de l'écran :

- **Chat** — conversation avec un assistant qui répond à partir de documents indexés
  (panneau "Sources" à gauche, chat au centre, "Notes" à droite).
- **Legacy KB** — exploration en lecture seule d'un graphe de connaissances (issu d'une
  extraction GraphRAG sur un corpus mainframe legacy, type CardDemo/CICS/COBOL). C'est
  **cette seconde vue** qui fait l'objet de la refonte.

L'application a une identité visuelle "neutre/chaleureuse" (tons crème, accents bleu
azur), assez sobre, proche d'un outil de productivité (Notion-like). L'objectif de la
refonte est de rendre la vue Legacy KB **plus moderne, plus lisible et plus agréable**,
sans nécessairement copier le style du reste de l'app si une direction graphique plus
adaptée à la visualisation de graphe est pertinente — mais en restant cohérent avec
l'identité globale (cf. section 8, contraintes).

---

## 2. Vue d'ensemble de la page actuelle

La page "Legacy KB" occupe tout l'espace sous le header global de l'app. Elle est
structurée en **3 bandes horizontales** + un **corps en 3 colonnes** :

```
┌──────────────────────────────────────────────────────────────────────────┐
│ Header global app (logo, switch Chat/Legacy KB, statut connexion, bouton  │
│ "Nouvelle conversation")                                                   │
├──────────────────────────────────────────────────────────────────────────┤
│ BARRE 1 — Recherche + stats globales                                       │
│  [🔍 champ de recherche.......................] [Rechercher]   N entités · │
│                                              M communautés · X nœuds/Y arcs│
│                                                          [Réinitialiser]    │
├──────────────────────────────────────────────────────────────────────────┤
│ BARRE 2 — Filtres                                                          │
│  (●Programme) (●Job batch) (●Copybook) (●Fichier) (●Référence externe)     │
│  ☐ Recherche élargie aux descriptions          [Parcourir par domaine] →  │
├──────────────────────────────────────────────────────────────────────────┤
│ CORPS (3 colonnes, hauteur restante)                                       │
│ ┌────────────┬─────────────────────────────────────┬──────────────────┐  │
│ │ Résultats  │            CANVAS GRAPHE             │  Panneau détail   │  │
│ │ de         │   (React Flow : nœuds, arêtes,       │  (nœud sélec-     │  │
│ │ recherche  │    minimap, contrôles zoom)          │   tionné)         │  │
│ │ (liste,    │                                       │                   │  │
│ │ optionnel) │   ou état vide si aucun graphe        │  (optionnel)      │  │
│ └────────────┴─────────────────────────────────────┴──────────────────┘  │
└──────────────────────────────────────────────────────────────────────────┘
```

Les colonnes latérales (résultats de recherche à gauche, panneau de détail à droite)
sont **conditionnelles** : elles n'apparaissent que si une recherche a été lancée /
qu'un nœud est sélectionné. Le canvas central est toujours présent et prend tout
l'espace restant.

---

## 3. Design system actuel (tokens)

| Token | Valeur | Usage |
|---|---|---|
| `T.white` | `#ffffff` | fonds de carte, panneaux |
| `T.panel` | `#f6f6f3` | fond de zone secondaire (canvas, filtres) |
| `T.railBg` | `#fbfbf9` | fond des rails latéraux |
| `T.border` | `#eceae5` | bordures fines |
| `T.borderStrong` | `#e1ded7` | bordures plus marquées |
| `T.ink` | `#1c1b18` | texte principal |
| `T.sub` | `#6b6963` | texte secondaire |
| `T.muted` | `#9c9990` | texte tertiaire / labels |
| `T.azure` | `#2f6df0` | couleur d'accent principale (CTA, sélection) |
| `T.azureSoft` | `#ecf2fe` | fond des badges/chips actifs |
| `T.azureBorder` | `#d2e0fc` | bordure des badges actifs |
| `T.azureInk` | `#2257d4` | texte sur fond azur clair |
| `T.danger` | `#dc2626` | erreurs, actions destructives |
| `T.success` | `#16a34a` | indicateurs "connecté" |
| Police | `"Hanken Grotesk", sans-serif` | toute l'UI |
| Rayons | `8px` (sm) / `14px` (md) / `20px` (lg) / `999px` (pill) | boutons, cartes, badges |

**Style général actuel** : interface plate, bordures fines 1px, badges en pilule,
ombres très légères (`0 1px 2px rgba(0,0,0,.06)`), pas de dégradés (sauf le logo "Azure"
en dégradé multicolore dans le header). Beaucoup de `border-radius: 999px` (pills) pour
les boutons/filtres.

---

## 4. Métamodèle des données Legacy KB (ce que le graphe représente)

Cette section décrit **les informations réellement disponibles** dans la base
`neo4j-legacykb` (dump GraphRAG brut d'un corpus mainframe legacy type
CardDemo/CICS/COBOL : 5812 nœuds, 19368 relations). Elle sert de référence pour que
l'IA de design comprenne **quel type de contenu peut apparaître** sur un nœud, une
arête ou dans le panneau de détail — utile pour proposer des représentations visuelles
pertinentes (icônes, hiérarchies, regroupements, densité d'information par carte…).

### 4.1 Deux familles de nœuds

**a) `:Entity`** — éléments techniques concrets du corpus mainframe. Identifiés par
`(type, name)`. Propriétés disponibles :

| Propriété | Contenu | Toujours présent ? |
|---|---|---|
| `type` | un des 5 types ci-dessous | oui |
| `name` | nom de l'élément (ex. nom de programme COBOL, de job JCL, de copybook…) | oui |
| `file_location` | chemin du fichier source dans le dépôt | souvent |
| `file_name` | nom de fichier | parfois |
| `repo_name` | dépôt d'origine | parfois |
| `updated_at` | date de dernière modification connue | parfois |
| `is_missing` | `true` si l'entité est une **référence externe non résolue** (mentionnée par d'autres éléments mais absente du corpus analysé) | — |
| `functional_description` | résumé en langage métier (1 phrase courte + détails) | variable selon type |
| `technical_description` | description technique brute (souvent verbeuse, contient des mots-clés mainframe — VSAM, CICS, DB2, JCL…) | variable selon type |

5 valeurs possibles pour `type` :

| `type` | Sens métier | Volume approx. |
|---|---|---|
| `Program` | Programme COBOL (unité de traitement) | 832 |
| `BatchJob` | Job batch (JCL) — orchestration de programmes | 40 |
| `Copybook` | Copybook (structure de données partagée, `COPY`) | 18 |
| `GenericFile` | Fichier de données / flux d'échange (VSAM, etc.) | 1 |
| `External/Doc` | Référence externe non résolue (mentionnée mais hors corpus, ex. doc/fichier tiers) | 4822 (~83 % du dump) |

→ **Implication design** : la grande majorité des nœuds qu'on peut rencontrer en
explorant le graphe sont des `External/Doc` peu informatifs (souvent juste un nom,
`is_missing: true`, sans description). Une représentation visuelle qui les distingue
clairement des entités "riches" (Program/BatchJob avec descriptions complètes) aiderait
à ne pas surcharger l'attention sur des nœuds peu utiles.

**b) `:Community`** — regroupements fonctionnels générés par l'algorithme GraphRAG
(détection de communautés sur le graphe), pas des éléments du code source. Identifiés
par un `id` natif. Propriétés :

| Propriété | Contenu |
|---|---|
| `id` | identifiant numérique de la communauté |
| `level` | `2` = domaine fonctionnel (macro, 96 communautés) / `1` = sous-domaine (plus fin) |
| `title` | nom du domaine (généré par LLM, ex. "Gestion des comptes clients") |
| `functional_summary` | résumé fonctionnel du domaine (texte LLM, plusieurs phrases) |
| `technical_summary` | résumé technique du domaine (texte LLM) |

→ Un domaine niveau 2 peut avoir des sous-domaines niveau 1 (`SUBCOMMUNITY_OF`), et des
`:Entity` y sont rattachées (`IN_COMMUNITY`). Une communauté est donc un **regroupement
de plusieurs entités** — conceptuellement plus proche d'un "conteneur"/cluster que d'un
élément ponctuel, ce qui peut justifier une représentation visuelle différente (zone
englobante, halo, etc. — cf. pistes §7).

### 4.2 Relations (arêtes)

Deux catégories bien distinctes :

- **Relations structurelles entre `:Entity`** (le "vrai" graphe technique) : décrivent
  comment les programmes/jobs/fichiers interagissent entre eux.

  | Relation | Sens | Volume approx. |
  |---|---|---|
  | `CALLS` | Programme → Programme appelé | 1948 |
  | `INCLUDES` | Programme → Copybook inclus (`COPY`) | 1518 |
  | `READS` | lecture d'un fichier/copybook | — |
  | `INSERTS` / `UPDATES` / `DELETES` / `CREATES` | écriture sur un fichier | — |
  | `EXECUTES` | BatchJob → Programme exécuté par ce job | 369 |
  | `REFERENCES`, `INTERACTS_WITH`, `SENDS`, `RECEIVES`, `TRIGGERS`, `DEPENDS_ON` | autres relations techniques détectées (volumes faibles) | — |

  (`READS`/`INSERTS`/`UPDATES`/`DELETES`/`CREATES` représentent ensemble ~6800 relations,
  la plus grosse masse après `IN_COMMUNITY`.)

- **Relations d'appartenance / hiérarchie** (lient les `:Entity` aux `:Community`, et
  les communautés entre elles) :

  | Relation | Sens | Volume approx. |
  |---|---|---|
  | `IN_COMMUNITY` | Entity → Community (sous-domaine ou domaine) — une par entité | ~5713 (la plus fréquente, ~30 % du dump) |
  | `SUBCOMMUNITY_OF` | Community niveau 1 → Community niveau 2 (sous-domaine → domaine parent) | — |

→ **Implication design** : `IN_COMMUNITY` est numériquement la relation la plus
fréquente, mais elle n'apporte pas d'information "métier" en tant qu'arête — c'est un
lien d'appartenance. Une piste de refonte consiste à **ne pas la représenter comme une
arête classique** (avec label, flèche, etc.) mais plutôt via un **positionnement/
regroupement spatial** (l'entité est visuellement "dans" ou "proche de" sa communauté),
réservant le rendu "arête classique avec label" aux relations techniques
(`CALLS`/`INCLUDES`/`READS`/…) qui sont l'information la plus actionnable pour un
utilisateur explorant le legacy.

### 4.3 Ce que l'utilisateur peut concrètement vouloir lire sur un nœud

En résumé, pour une carte de nœud (vue graphe) et le panneau de détail, les informations
disponibles et potentiellement affichables sont :

- **Identité** : nom, type/niveau (avec icône/couleur dédiée).
- **Statut** : référence externe non résolue (`is_missing`) — information binaire,
  potentiellement un simple badge/style atténué.
- **Résumé fonctionnel** (1 à quelques phrases, registre métier — "à quoi ça sert").
- **Description technique** (texte plus long, jargon mainframe — VSAM/CICS/DB2/JCL/
  COPY/PACBASE…) — peut contenir des mots-clés intéressants à mettre en avant (tags).
- **Provenance** : fichier source, dépôt.
- **Position dans la hiérarchie de domaines** (domaine fonctionnel → sous-domaine).
- **Connectivité** : nombre de relations entrantes/sortantes par type (déjà résumé en
  mini barres dans le panneau actuel — cf. §6.4).

Tous les nœuds n'ont pas toutes ces informations (un `External/Doc` aura souvent
seulement un nom et `is_missing: true`) — la maquette doit donc bien fonctionner pour
des cartes "pauvres" (juste un nom) comme pour des cartes "riches" (toutes les sections
remplies).

---

## 5. Le graphe (zone centrale — cœur de la refonte)

C'est la zone que l'utilisateur trouve actuellement peu engageante et souhaite
moderniser en priorité. Rendu avec **React Flow (xyflow)** + layout automatique
**dagre** (orientation gauche → droite).

### 4.1 Nœuds

Deux familles de nœuds, actuellement rendues avec la **même forme de carte** (pilule
arrondie 220×44px, fond blanc, bordure fine, ombre légère, texte 12px gras) — seule la
**pastille de couleur** à gauche du libellé change :

- **Entités** (pastille **ronde**, carte très arrondie `border-radius: 999px`) :
  | Type | Couleur | Libellé FR |
  |---|---|---|
  | `Program` | `#1565c0` (bleu) | Programme |
  | `BatchJob` | `#8d6e63` (brun) | Job batch |
  | `Copybook` | `#7b1fa2` (violet) | Copybook |
  | `GenericFile` | `#26a69a` (turquoise) | Fichier |
  | `External/Doc` | `#9e9e9e` (gris) | Référence externe |

- **Communautés / domaines** (pastille **carrée**, carte moins arrondie
  `border-radius: 8px`) :
  | Niveau | Couleur | Libellé FR |
  |---|---|---|
  | 2 | `#fb8c00` (orange foncé) | Domaine fonctionnel |
  | 1 | `#ffb74d` (orange clair) | Sous-domaine |

- Le **nœud central** (point de départ de l'exploration courante) a une bordure bleue
  azur 2px (`T.azure`) au lieu de la bordure grise par défaut — c'est le seul signal de
  "focus".

- Chaque nœud a **8 points d'ancrage invisibles** (4 côtés × source/target) pour le
  routage des arêtes — visuellement ce sont de petits points colorés de 8px sur les
  4 bords de la carte, actuellement assez visibles/parasites.

### 4.2 Arêtes (relations)

- Tracé `smoothstep` (coudes à angle droit arrondis), couleur gris clair `#cbd5e1`,
  flèche pleine à l'arrivée.
- Label texte (type de relation : "Appelle", "Inclut", "Lit", "Met à jour", "Domaine"…)
  affiché en permanence sur l'arête, fond blanc semi-transparent, 10px.
- Relations possibles : `CALLS, INCLUDES, READS, INSERTS, UPDATES, DELETES, CREATES,
  REFERENCES, EXECUTES, INTERACTS_WITH, SENDS, RECEIVES, TRIGGERS, DEPENDS_ON,
  IN_COMMUNITY, SUBCOMMUNITY_OF`.

### 4.3 Fond, contrôles et navigation

- Fond du canvas : grille de points (`Background` xyflow), couleur `T.border`, espacement
  20px, sur fond `T.panel` (beige très clair).
- **Contrôles zoom/fit** (boutons +/− /fit) en bas à gauche — composant standard React
  Flow, pas restylé.
- **Mini-carte** de navigation en bas à droite — composant standard React Flow, fond
  `T.panel`, bordure `T.border`, couleur des nœuds reprenant la palette
  entités/communautés ci-dessus.
- Zoom fluide, pan, et **drag des nœuds** activés (positions persistées par
  l'utilisateur même quand le graphe est étendu).

### 4.4 Interactions sur les nœuds

- **Clic simple** sur un nœud :
  1. Ouvre le **panneau de détail** à droite (cf. §6.4).
  2. Affiche un **menu contextuel flottant** ancré au curseur (cf. capture ci-dessous),
     style "Neo4j Browser", avec deux actions :
     - *"Étendre la vue avec les relations de ce nœud"* (icône loupe/microscope)
     - *"Effacer de la vue"* (icône croix, texte en rouge) — supprime le nœud **et**
       les nœuds devenus isolés (sans plus aucun lien visible) suite à cette
       suppression.
- **Double-clic** sur un nœud : étend directement le graphe avec son voisinage (équivaut
  au raccourci du menu).
- **Clic sur le fond (pane)** : ferme le panneau de détail et le menu contextuel.

Menu contextuel actuel (à moderniser également) :
```
┌──────────────────────────────────────────────┐
│ 🔬  Étendre la vue avec les relations de ce... │
│ ✕   Effacer de la vue                          │  (texte rouge)
└──────────────────────────────────────────────┘
```
Carte blanche, ombre portée, coins arrondis 14px, items en liste verticale avec hover
gris clair.

### 4.5 État vide du canvas

Quand aucun graphe n'est affiché (avant toute recherche/exploration) : message centré,
texte gris, deux lignes :
> "Legacy KB — graphe brut GraphRAG"
> "Recherchez un programme, un fichier ou une communauté, puis cliquez sur un résultat
> pour afficher son voisinage. Double-clic sur un nœud pour étendre l'exploration."

---

## 6. Autres zones de la page

### 5.1 Barre de recherche + stats (bandeau supérieur)

- Champ de recherche en pilule (icône loupe, placeholder "Rechercher un programme,
  fichier, communauté…"), bouton "Rechercher" plein bleu azur à droite.
- À droite : compteurs globaux en texte gris discret ("N entités · M communautés"), et
  si un graphe est affiché, un second compteur ("X nœuds · Y arcs") + bouton
  "Réinitialiser" (pilule outline).

### 5.2 Barre de filtres

- **Chips de type d'entité** (5 chips, une par type d'entité ci-dessus) : pastille de
  couleur + libellé, état actif = fond bleu clair `T.azureSoft` + bordure
  `T.azureBorder` + texte `T.azureInk` ; état inactif = fond blanc, bordure grise.
  Toggle multi-sélection (filtre OR sur la recherche).
- **Checkbox** "Recherche élargie aux descriptions" (étend la recherche au texte des
  descriptions fonctionnelles/techniques, pas juste aux noms).
- **Bouton "Parcourir par domaine"** aligné à droite, même style chip, actif = bleu
  clair. Bascule la liste de résultats vers la liste des domaines fonctionnels
  (communautés niveau 2) avec leurs sous-domaines.

### 5.3 Rail "Résultats de recherche" (gauche, conditionnel)

- Largeur fixe 280px, fond `T.railBg`, scrollable.
- Liste de résultats (recherche texte ou liste de domaines), chaque item :
  - ligne 1 : pastille de couleur (ronde=entité / carrée=communauté) + nom (tronqué)
  - ligne 2 : type d'entité ou "Domaine fonctionnel"/"Sous-domaine" + nombre de
    sous-domaines le cas échéant
  - item sélectionné : fond bleu clair `T.azureSoft` ; hover : fond `T.panel`.
- Clic sur un item = lance/étend l'exploration du graphe sur ce nœud.

### 5.4 Panneau de détail (droite, conditionnel)

- Largeur fixe 360px, fond blanc, bordure gauche fine, scrollable, padding 18px.
- En-tête : nom du nœud (gros, gras) + bouton fermer (croix) à droite.
- **Pour une entité** :
  - ligne type (pastille + libellé) + badge "Référence externe" si applicable
  - fil d'Ariane domaine/sous-domaine (chips bleu clair cliquables, navigables)
  - section "Résumé" — texte avec "Lire la suite / Réduire" (1ère phrase en gras,
    reste replié)
  - section "Connectivité" — mini barres horizontales de comptage par type de relation
    (jusqu'à 8, triées, barre bleue sur fond beige)
  - section "Métadonnées techniques" — fichier source, dépôt, date de mise à jour, +
    badges de tags techniques détectés (VSAM, CICS, DB2, SQL, MQ, IMS, KSDS, JCL, COPY,
    PACBASE, GOBACK…) en petites pilules bleu clair
  - section "Description technique" — texte brut
- **Pour une communauté/domaine** :
  - ligne niveau (pastille carrée + "Domaine fonctionnel"/"Sous-domaine")
  - fil d'Ariane vers le domaine parent si sous-domaine
  - section "Composition" (nb sous-domaines, nb membres)
  - section "Résumé fonctionnel", "Connectivité", "Résumé technique" (même formats que
    pour une entité)
- Toutes les sections sont des blocs verticaux séparés par un petit titre majuscule gris
  (11.5px, letter-spacing) au-dessus d'un texte 12.5px gris foncé.

---

## 7. Pistes de réflexion pour la refonte

L'utilisateur juge le rendu actuel du graphe "pas assez moderne/joli". Pistes ouvertes
pour les propositions de maquette (à explorer librement par l'IA de design) :

- **Nœuds** : formes/cartes plus distinctives par type (au-delà d'une simple pastille de
  couleur) — icônes par type d'entité (programme, job batch, copybook, fichier,
  référence externe), meilleure hiérarchie visuelle entre entités et communautés
  (peut-être tailles différentes, styles de carte différents — ex. communautés en
  "conteneurs"/zones de regroupement visuel plutôt que nœuds au même niveau que les
  entités).
- **Zones de regroupement par communauté** (`IN_COMMUNITY`, cf. §4.2) : représenter
  visuellement les domaines/sous-domaines comme des **zones englobantes** (fond teinté,
  contour, étiquette de titre) à l'intérieur desquelles sont positionnées les entités
  membres — plutôt que des nœuds "communauté" isolés au même niveau que les entités.
  Chaque entité possède exactement **une** communauté de rattachement (`IN_COMMUNITY`,
  une par entité), donc l'appartenance "zone" elle-même n'est pas ambiguë ; en revanche,
  une fois le graphe étendu (exploration multi-communautés), les **relations
  techniques** (`CALLS`, `INCLUDES`, `READS`…) d'une entité peuvent pointer vers des
  entités appartenant à **d'autres zones** — c'est ce cas qui doit être traité
  visuellement :
  - **Option a — entité positionnée en bordure de sa zone**, du côté le plus proche des
    zones avec lesquelles elle a des relations cross-domaine (plus simple à articuler
    avec un layout type dagre/clustering).
  - **Option b — entité positionnée hors de toute zone** (dans un espace "neutre" entre
    les zones), si elle a des relations vers plusieurs domaines différents — sert de
    "pont" visuel entre zones.
  - Dans les deux cas, prévoir un indicateur visuel léger (icône, liseré coloré multi-
    teintes) signalant qu'une entité est un point de connexion inter-domaines — utile
    pour repérer rapidement les éléments transverses (souvent les `Copybook`/
    `GenericFile` partagés). À l'IA de design de proposer la solution la plus lisible ;
    la contrainte forte est que les **arêtes techniques restent visibles et routables**
    même quand leurs deux extrémités sont dans des zones différentes (cf. §8, pas de
    layout pixel-perfect — coordonnées calculées algorithmiquement).
- **Arêtes** : réduire le bruit visuel des labels toujours visibles (peut-être au survol
  uniquement, ou typographie plus discrète) ; styles de trait différenciés par catégorie
  de relation (ex. relations de structure vs. relations de communauté).
- **Palette** : la palette actuelle (bleu/brun/violet/turquoise/gris pour les entités,
  orange pour les communautés) peut être revue pour plus d'harmonie/contraste tout en
  restant distinguable (accessibilité daltonisme à considérer si possible).
- **Densité** : avec beaucoup de nœuds explorés, le canvas peut devenir chargé — pistes
  : clustering visuel par domaine, regroupement (grouping/zones), niveaux de zoom
  sémantiques (masquer les labels à faible zoom).
- **Menu contextuel & handles** : le menu contextuel actuel et les 8 points d'ancrage
  visibles sur chaque nœud sont fonctionnels mais peu soignés visuellement — proposer un
  habillage plus discret/élégant (ex. handles invisibles sauf au survol).
- **Panneaux latéraux** (résultats / détail) : actuellement très "liste/texte" — peuvent
  gagner en hiérarchie visuelle (cartes, icônes, mise en valeur des métadonnées clés).
- **Ambiance générale** : explorer si un fond de canvas plus sombre/contrasté (mode
  "graphe" différencié du reste de l'app, à la manière de Neo4j Bloom, Linear, ou
  d'outils de data-viz modernes) servirait mieux la lisibilité du graphe, tout en
  gardant les bandeaux de recherche/filtres dans le style actuel de l'app pour la
  cohérence globale.

---

## 8. Contraintes techniques à respecter dans les propositions

- Le rendu du graphe est implémenté avec **React Flow (xyflow)** : les propositions
  doivent rester compatibles avec ses primitives (nœuds = composants React positionnés
  en absolu, arêtes = tracés SVG `smoothstep`/`bezier`/`straight`, `Background`,
  `Controls`, `MiniMap`, `Handle` à 4 points par défaut). Pas de rendu 3D / WebGL.
- Layout automatique via **dagre** (orientation gauche→droite) — toute proposition de
  layout en grille/zones doit rester compatible avec un positionnement (x,y) calculé
  algorithmiquement (pas de mise en page manuelle pixel-perfect).
- Le reste de l'application (Header, Chat, panneaux Sources/Notes) garde son style
  actuel — la refonte porte sur la vue Legacy KB uniquement (canvas + ses panneaux
  associés : recherche, filtres, résultats, détail, menu contextuel).
- Pas de dépendance externe supplémentaire non vendorisée (politique "pas de CDN") —
  toute nouvelle police/icône doit pouvoir être auto-hébergée.
- Les couleurs par type d'entité/communauté doivent rester **suffisamment distinctes**
  (5 types d'entités + 2 niveaux de communauté = 7 couleurs minimum à terme).
