# Modernization Agent — Spécifications Fonctionnelles v1.0

> **Usage de ce document** : Ce fichier est le point d'entrée pour la génération de Solution Design Documents (SDD) détaillés et le développement des modules. Chaque module est une unité développable indépendante, mais les modules s'alimentent séquentiellement. Commencer par ADG-M.

---

## Contexte produit

**Produit** : Extension de l'agent ArchiMind existant pour la modernisation applicative. L'agent dispose déjà d'un RAG branché sur des rétro-docs générés par ArchiMind (documents Markdown/JSON décrivant des bases de code legacy — COBOL, mainframe, monolithes).

**Problème adressé** : Le RAG actuel permet de *retrouver* et *expliquer* l'existant. Il ne permet pas de *décider* : quel composant migrer, dans quel ordre, avec quelle trajectoire, à quel coût. Les 4 modules ci-dessous couvrent ce saut de valeur.

**Utilisateur cible** : Architecte de modernisation (profil Lead Solution Architect). Pas un opérateur cloud. L'outil doit produire des livrables défendables en COMEX et en CoDir IT.

---

## Contraintes techniques globales

| Dimension | Contrainte |
|---|---|
| **Environnement de développement** | PC Windows (Windows 11), VS Code |
| **Cloud** | Azure (subscription active) — services dans la limite du raisonnable (pas de clusters Kubernetes dédiés, pas de GPU managed) |
| **RAG existant** | Déjà opérationnel — Azure AI Search + Azure OpenAI GPT-4o. Ne pas le refaire, s'y brancher |
| **Langue de l'interface** | Français |
| **Format des rétro-docs entrants** | Markdown structuré + JSON (output ArchiMind) |
| **Format des livrables sortants** | Markdown (ADR), JSON (échange inter-modules), PowerPoint (deck COMEX via export) |
| **Authentification** | Azure AD / Entra ID (single tenant, compte développeur) |

---

## Architecture globale des modules

```
ArchiMind rétro-docs (Markdown/JSON)
              │
              ▼
    ┌─────────────────┐
    │   ADG-M [P0]    │  ← Fondation : graphe bi-plan fonctionnel + technique
    └────────┬────────┘
             │ fournit : nœuds, arcs, métriques, clusters
      ┌──────┴──────┐
      ▼             ▼
┌──────────┐  ┌──────────┐
│ 7RQA[P0] │  │ ADM-M[P1]│  ← Qualification par composant / positionnement stratégique
└──────────┘  └──────────┘
      │             │
      └──────┬──────┘
             ▼
    ┌─────────────────┐
    │   MWP  [P1]     │  ← Plan de vagues + états stables + estimation effort
    └─────────────────┘
             │
             ▼
   Livrables : ADR, Deck COMEX, Backlog Azure DevOps
```

**Règle de développement** : ADG-M est un prérequis bloquant pour tous les autres modules. 7RQA et ADM-M peuvent être développés en parallèle une fois ADG-M livré. MWP nécessite 7RQA et ADM-M.

---

## Module 1 — ADG-M : Architecture Dependency Graph for Modernization

### Priorité
`P0` — Fondation du produit. Aucun autre module ne fonctionne sans lui.

### Objectif fonctionnel
Produire une cartographie bi-plan (fonctionnel + technique) du périmètre legacy analysé, annotée pour supporter la décision de modernisation. La carte doit être vivante : elle se met à jour à chaque nouvelle rétro-doc ArchiMind ingérée.

### Schéma de données

#### Nœud fonctionnel (`FunctionalNode`)
```json
{
  "id": "string (uuid)",
  "type": "functional",
  "domain": "string",
  "subdomain": "string",
  "processes": ["string"],
  "sharedBusinessObjects": ["string"],
  "docCoveragePercent": "number (0-100)",
  "modernizationStatus": "EXISTING | IN_TRANSITION | TARGET",
  "sourceDocIds": ["string (ArchiMind doc ref)"]
}
```

#### Nœud technique (`TechnicalNode`)
```json
{
  "id": "string (uuid)",
  "type": "technical",
  "componentName": "string",
  "technology": "COBOL | JCL | PL1 | PACBASE | JAVA | DOTNET | OTHER",
  "linesOfCode": "number",
  "callFrequency": "HIGH | MEDIUM | LOW | UNKNOWN",
  "candidate7R": "RETIRE | RETAIN | REHOST | REPLATFORM | REPURCHASE | REFACTOR | REBUILD | UNQUALIFIED",
  "knowledgeOwner": "string (nom expert ou 'TACIT')",
  "regulatoryTags": ["DORA", "BCBS239", "NIS2", "AI_ACT"],
  "sourceDocIds": ["string"]
}
```

#### Arc (`DependencyArc`)
```json
{
  "id": "string (uuid)",
  "sourceNodeId": "string",
  "targetNodeId": "string",
  "arcType": "FUNCTIONAL | TECHNICAL_CALL_SYNC | TECHNICAL_CALL_ASYNC | TECHNICAL_BATCH | DATA_FLOW | TRANSITIONAL_COHABITATION",
  "dataFormat": "string (optionnel)",
  "direction": "UNIDIRECTIONAL | BIDIRECTIONAL",
  "criticality": "CRITICAL | HIGH | MEDIUM | LOW"
}
```

### Fonctions détaillées

#### F1.1 — Ingestion depuis les rétro-docs ArchiMind
- **Déclencheur** : Dépôt d'un fichier Markdown/JSON ArchiMind dans un dossier Azure Blob Storage dédié (`/retrodocs/incoming/`)
- **Pipeline** :
  1. Azure Function (HTTP trigger ou Blob trigger) parse le document entrant
  2. Prompt GPT-4o pour extraire les entités (nœuds) et relations (arcs) selon les schémas ci-dessus
  3. Écriture dans Neo4j (base de graphe)
  4. Déplacement du fichier vers `/retrodocs/processed/`
- **Règles de parsing** :
  - Toute section `## Dépendances` ou `## Interfaces` → arcs
  - Toute section `## Domaine` ou `## Objets métier` → nœuds fonctionnels
  - Tout programme référencé mais sans rétro-doc associée → nœud fantôme (`GHOST`, signalé visuellement)
  - Les tags réglementaires (DORA, BCBS 239...) trouvés dans le texte → champ `regulatoryTags` du nœud

#### F1.2 — Vue bi-plan commutable
- **Plan fonctionnel** : nœuds groupés par domaine métier, colorés par `modernizationStatus`
  - Couleurs : EXISTING = gris, IN_TRANSITION = orange, TARGET = vert
- **Plan technique** : graphe des composants, colorés par `candidate7R`
  - Couleurs : RETIRE = rouge, RETAIN = gris, REHOST = bleu clair, REPLATFORM = bleu, REPURCHASE = violet, REFACTOR = orange, REBUILD = vert, UNQUALIFIED = blanc/tiret
- **Vue superposée** : overlay des deux plans — alerte visuelle si un nœud fonctionnel `CRITICAL` est porté uniquement par des nœuds techniques `RETIRE` ou `UNQUALIFIED`

#### F1.3 — Score de criticité et détection SPOF
- **Score de criticité** d'un nœud = somme des arcs entrants × poids criticité de chaque arc source
- **SPOF** = nœud dont le score de criticité > percentile 90 ET aucun nœud redondant identifié dans le voisinage
- **Affichage** : badge rouge "⚠ SPOF" sur le nœud + liste des composants downstream impactés en cas de défaillance

#### F1.4 — Annotation 7R collaborative
- Sur chaque nœud technique : panneau latéral avec sélecteur 7R + champ justification (texte libre)
- L'agent propose une 7R candidate automatique depuis les métriques du nœud (voir grille 7RQA)
- La décision posée par l'architecte remplace la suggestion agent et est versionnée (qui, quand, motif)
- Les nœuds sans décision 7R validée restent à l'état `UNQUALIFIED` et apparaissent dans le backlog de qualification

#### F1.5 — Détection des appartements candidats (clustering)
- Algorithme : Louvain community detection sur le graphe Neo4j
- Un cluster est un "appartement candidat" si : cohésion interne > 0.7 ET couplage externe < 0.3 (métriques configurables)
- Chaque cluster est affiché comme une zone délimitée sur le graphe, nommée par l'architecte
- Export JSON des clusters vers MWP pour séquençage des vagues

### Interface utilisateur
- Application web (React + TypeScript)
- Librairie de graphe : **Cytoscape.js** (adapté aux graphes métier, layouts hiérarchiques)
- Panneau gauche : liste des domaines / filtres
- Zone centrale : graphe interactif (zoom, pan, clic sur nœud → panneau détail)
- Panneau droit : détail nœud + annotation 7R + liste des arcs
- Barre supérieure : switch Plan Fonctionnel / Plan Technique / Vue Superposée

### Stack technique

| Composant | Choix | Justification |
|---|---|---|
| Base de graphe | **Neo4j** (Azure Marketplace ou Neo4j AuraDB Free Tier) | Algorithmes natifs (Louvain, PageRank, betweenness) — supérieur à Cosmos DB Gremlin pour l'analyse |
| Pipeline d'ingestion | **Azure Functions** (Python, Consumption Plan) | Serverless, coût quasi nul au repos |
| Modèle d'extraction | **Azure OpenAI GPT-4o** (déjà provisionné) | Cohérence avec le RAG existant |
| Stockage rétro-docs | **Azure Blob Storage** (déjà existant si RAG en place) | Réutiliser l'existant |
| Frontend | **React + TypeScript + Cytoscape.js** | Stack standard, Cytoscape bien documenté |
| Hébergement frontend | **Azure Static Web Apps** (Free Tier) | Gratuit pour un usage développeur |

### Livrables du module
- API REST (Azure Function) : `POST /graph/ingest`, `GET /graph/nodes`, `GET /graph/arcs`, `GET /graph/clusters`
- Interface web de visualisation bi-plan
- Export JSON des clusters pour MWP
- Export CSV des nœuds UNQUALIFIED pour backlog 7RQA

---

## Module 2 — 7RQA : 7R Qualification Assistant

### Priorité
`P0` — Différenciateur produit. Transforme le graphe en aide à la décision stratégique.

### Objectif fonctionnel
Depuis les données du graphe ADG-M et la rétro-doc ArchiMind du composant, qualifier la trajectoire de modernisation optimale (7R) avec une argumentation auditée, défendable en comité de gouvernance.

### Principe de sortie
L'agent ne produit pas une réponse : il produit un **dossier de qualification** structuré contenant la 7R recommandée, les alternatives écartées avec motif, le niveau de confiance, les hypothèses posées et les kill criteria (conditions qui invalideraient la recommandation).

### Grille d'évaluation (6 dimensions)

| Dimension | Source de données | Règle de décision indicative |
|---|---|---|
| Complexité de migration | `linesOfCode` + degré de couplage (arcs sortants) | > 500 arcs sortants → recommander Rehost avant Refactor |
| Valeur métier différenciante | Annotation fonctionnelle ADG-M (`domain`, `sharedBusinessObjects`) | Composant différenciant → exclure Retire et Replace |
| Risque perte de connaissance | `docCoveragePercent` + `knowledgeOwner` = TACIT | < 40% couverture → favoriser trajectoire conservatrice (Rehost, Retain) |
| Contrainte réglementaire | `regulatoryTags` | DORA ou BCBS239 présent → exclure Rebuild sans plan de continuité |
| Disponibilité équivalent SaaS | Recherche RAG sur catalogue solutions (prompt dédié) | Marché mature + non différenciant → suggérer Repurchase |
| Effort estimé (proxy) | `linesOfCode` × coeff complexité (calibré sur missions Arkéa / Retail Compagnie) | Fourchette jours·homme avec intervalle de confiance |

### Fonctions détaillées

#### F2.1 — Intake de qualification (mode unitaire)
- L'architecte clique sur un nœud technique dans ADG-M → bouton "Qualifier 7R"
- L'agent charge automatiquement :
  - Données du nœud depuis Neo4j
  - Rétro-doc ArchiMind associée (via `sourceDocIds` → requête RAG Azure AI Search)
  - Décisions ADM-M déjà posées sur le domaine fonctionnel associé (si ADM-M disponible)
- L'agent exécute la grille d'évaluation sur les 6 dimensions et produit le rapport de qualification

#### F2.2 — Rapport de qualification (structure fixe)
```markdown
# Qualification 7R — [Nom du composant]
**Date** : [date]  **Architecte** : [utilisateur]  **Confiance** : ÉLEVÉE / MOYENNE / FAIBLE

## Décision recommandée : [7R]
[Justification en 3-5 phrases, argumentation factuelle depuis les métriques]

## Évaluation par dimension
| Dimension | Valeur observée | Impact sur la décision |
|---|---|---|
| Complexité | X lignes, Y arcs sortants | ... |
| Valeur métier | Différenciant / Non différenciant | ... |
| Connaissance | X% couverture, propriétaire : [nom/TACIT] | ... |
| Réglementaire | [tags présents] | ... |
| SaaS disponible | [résultat recherche] | ... |
| Effort estimé | X à Y j·h (intervalle de confiance : Z%) | ... |

## 7R écartées
- **[7R]** : écarté car [motif précis]
- **[7R]** : écarté car [motif précis]

## Hypothèses posées
- [Hypothèse 1 : si fausse, reconsidérer la décision]
- [Hypothèse 2 : ...]

## Kill criteria
- Si [condition], la décision doit être révisée en [7R alternative]

## Lien ADR
[Lien vers l'ADR généré dans ADM-M — à compléter après validation]
```

#### F2.3 — Validation et surcharge architecte
- L'architecte peut valider la recommandation agent (→ statut `VALIDATED`) ou la surcharger (→ statut `OVERRIDDEN` + champ obligatoire "Motif de surcharge")
- La décision validée met à jour le champ `candidate7R` du nœud dans Neo4j
- Historique complet des révisions (versioning en base SQL)

#### F2.4 — Mode batch (portefeuille applicatif)
- Déclencheur : bouton "Qualifier tout le portefeuille" ou sélection d'un cluster ADG-M
- L'agent traite tous les nœuds `UNQUALIFIED` du périmètre
- Sortie : tableau de synthèse avec distribution des 7R + colonne "Confiance"
- Les nœuds `FAIBLE` confiance sont signalés comme priorité d'investigation humaine (insufficient data)

#### F2.5 — Calibration depuis les références missions
- Jeu de données de calibration : Retail Compagnie (COBOL, 5M lignes) + Arkéa (COBOL bancaire, migration + QA)
- Le coefficient d'effort est calculé depuis ces références et affiché dans chaque rapport ("Calibration : Arkéa 2025")
- Ce mécanisme de traçabilité de la calibration est ce qui rend le rapport opposable en COMEX

### Interface utilisateur
- Panneau latéral dans ADG-M (déclenchement depuis le graphe)
- Vue autonome "Backlog de qualification" : liste des nœuds UNQUALIFIED avec filtres domaine / criticité
- Vue "Tableau de synthèse portefeuille" : distribution 7R, heatmap confiance

### Stack technique

| Composant | Choix | Justification |
|---|---|---|
| Orchestration | **Semantic Kernel** (Python SDK) | Pipelines chaînés multi-étapes, mémoire de session, écosystème Azure natif |
| Modèle de raisonnement | **Azure OpenAI o4-mini** (reasoning) | La qualification multicritères nécessite du raisonnement, pas de la génération |
| Stockage rapports | **Azure SQL Database** (Basic tier, ~5€/mois) | Versioning, requêtes d'agrégation portefeuille |
| API | **Azure Functions** (Python) | Cohérence avec ADG-M |

### Livrables du module
- API : `POST /qualify/single/{nodeId}`, `POST /qualify/batch/{clusterId}`, `GET /qualify/report/{reportId}`
- Interface backlog de qualification
- Interface tableau de synthèse portefeuille
- Mise à jour automatique du champ `candidate7R` dans Neo4j

---

## Module 3 — ADM-M : Architecture Decision Matrix for Modernization

### Priorité
`P1` — Complète 7RQA par une lecture stratégique portefeuille (macro) là où 7RQA est composant par composant (micro).

### Objectif fonctionnel
Positionner chaque composant sur un quadrant **Criticité métier × Différenciation métier**, dériver la palette 7R naturelle par quadrant, et générer des ADR traçables depuis chaque décision validée.

### Différence avec une ADM classique
Une ADM classique compare des solutions technologiques (Azure SQL vs Cosmos DB). L'ADM-M compare des **trajectoires de modernisation** pour un composant en fonction de son positionnement métier. L'objet est différent.

### Schéma du quadrant

```
Criticité métier
    ▲
    │  RETAIN                │  REFACTOR / REBUILD
    │  (différenciant,       │  (différenciant,
    │  critique mais         │  critique et
    │  modernisation risquée)│  modernisation prioritaire)
    │                        │
    ├────────────────────────┤
    │  RETIRE / REPLACE      │  REHOST / REPLATFORM
    │  (non différenciant,   │  (non différenciant,
    │  peu critique)         │  mais critique opérationnellement)
    │                        │
    └────────────────────────►
                              Différenciation métier
```

### Les 12 critères de positionnement

#### Axe différenciation (6 critères)
| # | Critère | Source |
|---|---|---|
| D1 | Existence d'un équivalent SaaS mature sur le marché | Recherche RAG catalogue + prompt GPT-4o |
| D2 | Niveau de personnalisation des règles de gestion | `linesOfCode` règles métier / rétro-doc ArchiMind |
| D3 | Fréquence d'évolution fonctionnelle demandée | Backlog (si disponible) ou estimation depuis rétro-doc |
| D4 | Unicité du processus dans le secteur d'activité | Prompt GPT-4o sur description fonctionnelle |
| D5 | Niveau de dépendance des canaux clients | Arcs entrants depuis nœuds "Frontend / Canal" dans ADG-M |
| D6 | Propriété intellectuelle embarquée dans le code | Détection via rétro-doc ArchiMind (règles de gestion propriétaires) |

#### Axe criticité (6 critères)
| # | Critère | Source |
|---|---|---|
| C1 | Présence dans des flux de valeur critiques | Arcs ADG-M, type `CRITICAL` |
| C2 | Niveau de couplage entrant (degré in-degree) | Métriques Neo4j |
| C3 | Contraintes de disponibilité réglementaires | `regulatoryTags` du nœud |
| C4 | Volume de transactions journalières | Rétro-doc ArchiMind (section volumétrie) |
| C5 | Présence de SPOF downstream | Score SPOF ADG-M |
| C6 | Niveau de risque données (PII, données bancaires) | Tags dans rétro-doc ArchiMind |

### Fonctions détaillées

#### F3.1 — Positionnement sur le quadrant
- L'agent calcule un score D (0-10) et un score C (0-10) depuis les 12 critères
- Chaque critère est évalué automatiquement depuis les données disponibles, avec un niveau de confiance par critère
- L'architecte peut ajuster le score de chaque critère manuellement + note justificative
- Le composant est placé sur le quadrant à la position (D, C)
- La palette 7R naturelle du quadrant est affichée en superposition

#### F3.2 — Pondération personnalisable
- L'architecte peut pondérer les 12 critères selon le contexte projet (ex : "La conformité DORA vaut 30% du score criticité pour ce client bancaire")
- Les pondérations sont sauvegardées comme "profil de projet" réutilisable

#### F3.3 — Vue portefeuille
- Tous les composants qualifiés affichés simultanément sur le quadrant
- Filtres : par domaine métier, par statut de qualification, par technologie
- Lecture d'un coup d'œil : distribution Core/Context du patrimoine + niveau de décision 7R atteint

#### F3.4 — Traçabilité et versioning
- Chaque positionnement est daté, signé (utilisateur), et versionné
- Delta visible si un repositionnement intervient (avant / après, motif)
- Historique complet consultable par composant

#### F3.5 — Génération d'ADR
- Depuis la validation d'un positionnement + 7R associée, génération automatique d'un ADR au format standard :

```markdown
# ADR-[numéro] — [Nom du composant]
**Date** : [date]  **Statut** : PROPOSÉ / ACCEPTÉ / DÉPRÉCIÉ
**Décideur(s)** : [utilisateur]

## Contexte
[Métriques du composant : LOC, couplage, criticité, couverture rétro-doc]

## Décision
**Trajectoire 7R retenue** : [7R]  
**Position quadrant** : Criticité [C/10] × Différenciation [D/10]

## Justification
[Résumé des 12 critères de positionnement]

## Conséquences
- Impact sur le graphe de dépendances : [nœuds affectés]
- Appartements impactés (MWP) : [clusters concernés]
- Couche d'interopérabilité requise : OUI / NON

## Alternatives écartées
[Depuis le rapport 7RQA associé]

## Lien 7RQA
[Référence du rapport de qualification]
```

- Export Markdown vers Azure Blob / Azure DevOps Wiki

### Interface utilisateur
- Vue principale : quadrant interactif (D3.js, drag-and-drop des composants)
- Panneau de scoring : les 12 critères avec valeur agent + surcharge architecte
- Vue historique : timeline des repositionnements par composant
- Vue portefeuille : quadrant avec tous les composants + filtres

### Stack technique

| Composant | Choix | Justification |
|---|---|---|
| Calcul des scores | **Azure Functions** (Python) | Appels GPT-4o pour les critères nécessitant analyse textuelle |
| Stockage matrices | **Azure SQL Database** (même instance que 7RQA) | Requêtes croisées composant / décision / historique |
| Visualisation quadrant | **D3.js** dans React | Contrôle total du layout drag-and-drop |
| Export ADR | Template Markdown + Azure Blob | Format universel, intégrable dans n'importe quel wiki |

### Livrables du module
- API : `POST /matrix/position/{nodeId}`, `GET /matrix/portfolio`, `POST /matrix/adr/generate/{nodeId}`
- Interface quadrant interactif
- Générateur d'ADR avec export Markdown
- Liaison avec 7RQA (lecture des rapports de qualification)

---

## Module 4 — MWP : Migration Wave Planner

### Priorité
`P1` — Livrable final. Transforme l'analyse en programme de transformation pilotable.

### Objectif fonctionnel
Traduire le graphe de dépendances (ADG-M) et les décisions 7R validées (7RQA + ADM-M) en un plan de migration séquencé par vagues, avec identification des états stables intermédiaires, estimation effort/durée et simulation de scénarios alternatifs.

### Définition d'une vague valide
Une vague est valide si et seulement si elle satisfait les trois conditions suivantes :
1. **Pas de dépendance circulaire non résolue** : aucun composant de la vague ne dépend d'un composant non encore migré sans couche d'interopérabilité prévue
2. **État stable opérationnel à la fin de la vague** : le SI peut fonctionner sans les composants legacy migrés — la vague est un "appartement livrable"
3. **Valeur métier mesurable indépendante** : la vague délivre une valeur identifiable sans attendre les vagues suivantes

### Fonctions détaillées

#### F4.1 — Génération automatique de vagues
- **Input** : graphe ADG-M (nœuds + arcs) + décisions 7R validées + clusters d'appartements ADG-M
- **Algorithme** : tri topologique sur le graphe Neo4j avec contraintes de priorité pondérées
- **Trois modes de priorisation** (configurables par l'architecte) :
  - **Mode Valeur** : prioriser les Rebuild/Refactor à forte différenciation → valeur métier tôt
  - **Mode Risque** : commencer par les composants faiblement couplés → minimiser le risque de transition
  - **Mode Budget** (= principe "Context finance Core") : commencer par les Retire/Replace → dégager l'OPEX qui finance la suite

#### F4.2 — États stables intermédiaires
Pour chaque vague, l'agent identifie et documente :

| Élément | Description |
|---|---|
| Couches d'interopérabilité nécessaires | Proxy, CDC (Change Data Capture), API façade, pendant la cohabitation |
| Composants en double run | Liste des composants legacy qui continuent de fonctionner en parallèle de la cible |
| Kill criteria de décommissionnement | Conditions mesurables pour sortir le legacy (ex : "100% des flux validés sur cible depuis 30 jours") |
| Durée estimée de cohabitation | Fourchette en semaines avec facteurs d'incertitude |

#### F4.3 — Estimation effort / durée
- **Base de calibration** :
  - Retail Compagnie : ratio effort ArchiMind / volume COBOL (rétro-doc phase 1)
  - Arkéa : ratio effort QA / volume migré + anomalies détectées

- **Calcul par composant** :
  ```
  Effort_composant = LOC × coeff_complexité × coeff_couplage × coeff_couverture_doc
  coeff_couverture_doc = 1 / (docCoveragePercent / 100) — pénalité si rétro-doc incomplète
  ```

- **Sortie par vague** :
  - Effort total (jours·homme) : fourchette min / médiane / max
  - Durée calendaire : estimation avec hypothèse d'équipe (configurable)
  - Niveau d'incertitude : FAIBLE / MOYEN / ÉLEVÉ avec facteurs explicites
  - Référence de calibration utilisée

#### F4.4 — Simulation de scénarios
- L'architecte peut générer plusieurs variantes de plan et les comparer :

| Variante | Description |
|---|---|
| Variante A | Vagues de 6 mois, mode Valeur |
| Variante B | Vagues de 3 mois, mode Risque |
| Variante C | Retire d'abord, mode Budget |

- Chaque variante est évaluée sur 3 indicateurs et affichée sur un graphe de comparaison :
  1. **Mois avant la première valeur métier délivrée**
  2. **Pic de coût de double run** (OPEX legacy + OPEX nouveau simultanés)
  3. **Niveau de risque maximal** (point de la trajectoire où les deux systèmes sont le plus exposés)

#### F4.5 — Pilotage de l'avancement (post-lancement)
- Une fois le plan de vagues validé, le MWP devient tableau de bord d'avancement :
  - Statut de chaque composant par vague : À FAIRE / EN COURS / LIVRÉ / BLOQUÉ
  - Alertes sur dépendances bloquantes (composant prérequis non livré)
  - Calcul automatique de la dérive : si vague N est en retard → impact sur vagues N+1, N+2 affiché
  - Indicateur "Budget libéré" : OPEX legacy éteint cumulé depuis le début du programme

#### F4.6 — Export
- **Markdown** : fiche de vague avec état stable, couches d'interopérabilité, kill criteria
- **Azure DevOps** : création automatique d'Epics (une par vague) et Features (un par composant) via API Azure DevOps
- **PowerPoint** : slide de synthèse du plan de vagues pour deck COMEX (une slide par variante + slide de comparaison)

### Interface utilisateur
- **Vue principale** : timeline Gantt interactive (React + vis-timeline)
  - Axe X : temps (mois)
  - Axe Y : vagues
  - Blocs : composants, colorés par 7R
  - Indicateurs superposés : courbe coût double run, courbe valeur livrée
- **Vue dépendances** : graphe ADG-M filtré sur la vague sélectionnée, avec arcs de cohabitation en évidence
- **Vue comparaison** : 3 variantes côte à côte sur les 3 indicateurs
- **Vue pilotage** : tableau de bord d'avancement par vague (post-lancement)

### Stack technique

| Composant | Choix | Justification |
|---|---|---|
| Moteur de séquençage | **Algorithme topologique Neo4j** (via appel Cypher) | Natif sur la base de graphe déjà en place |
| Calcul de scénarios | **Azure Functions** (Python, batch) | Calcul asynchrone, pas de serveur dédié |
| Interface Gantt | **React + vis-timeline** | Librairie Gantt interactive mature, open source |
| Export Azure DevOps | **Azure DevOps REST API** | API officielle, pas de lib tierce nécessaire |
| Export PowerPoint | **python-pptx** | Génération côté serveur, sans dépendance Windows COM |
| Stockage plans | **Azure SQL Database** (même instance) | Cohérence avec les autres modules |

### Livrables du module
- API : `POST /wave/generate`, `GET /wave/plan/{planId}`, `POST /wave/simulate`, `PUT /wave/status/{componentId}`
- Interface Gantt interactive avec vue comparaison scénarios
- Export Azure DevOps (Epics / Features)
- Export PowerPoint deck COMEX
- Dashboard de pilotage d'avancement

---

## Backlog de développement suggéré

### Sprint 0 — Infrastructure (1 semaine)
- [ ] Provisionner Neo4j (AuraDB Free Tier ou déploiement Azure Marketplace)
- [ ] Provisionner Azure SQL Database (Basic)
- [ ] Créer le projet React (Vite + TypeScript)
- [ ] Configurer Azure Functions (Python, runtime v4)
- [ ] Configurer Azure Static Web Apps
- [ ] Vérifier la connexion au RAG existant (Azure AI Search)

### Sprint 1 — ADG-M core (2-3 semaines)
- [ ] Pipeline d'ingestion Blob → GPT-4o → Neo4j
- [ ] API `GET /graph/nodes` et `GET /graph/arcs`
- [ ] Interface Cytoscape.js — rendu basique du graphe
- [ ] Switch Plan Fonctionnel / Plan Technique
- [ ] Annotation 7R manuelle sur nœud

### Sprint 2 — ADG-M avancé + 7RQA (2-3 semaines)
- [ ] Score de criticité et détection SPOF
- [ ] Clustering Louvain (appartements candidats)
- [ ] 7RQA mode unitaire (grille 6 dimensions + rapport)
- [ ] Validation / surcharge architecte
- [ ] Mise à jour Neo4j depuis décision validée

### Sprint 3 — ADM-M (2 semaines)
- [ ] Calcul des 12 critères (D + C)
- [ ] Interface quadrant D3.js
- [ ] Générateur d'ADR Markdown
- [ ] Vue portefeuille

### Sprint 4 — MWP (2-3 semaines)
- [ ] Tri topologique + génération de vagues
- [ ] Estimation effort/durée (calibration Arkéa / Retail)
- [ ] Interface Gantt vis-timeline
- [ ] Simulation de scénarios (3 variantes)
- [ ] Export Azure DevOps

### Sprint 5 — MWP avancé + finitions (1-2 semaines)
- [ ] 7RQA mode batch
- [ ] Dashboard pilotage avancement MWP
- [ ] Export PowerPoint (python-pptx)
- [ ] Cohérence inter-modules (navigation croisée ADG-M ↔ 7RQA ↔ ADM-M ↔ MWP)

---

## Questions ouvertes pour le SDD détaillé

Ces points nécessitent une décision avant de passer au développement :

1. **Format exact des rétro-docs ArchiMind** : Markdown pur ? JSON structuré ? Les deux ? → détermine la complexité du pipeline d'ingestion F1.1
2. **Authentification** : Azure AD avec quelle granularité ? Utilisateur unique (dev solo) ou multi-utilisateurs ? → détermine si on met en place Azure AD App Registration dès maintenant
3. **Neo4j** : AuraDB Free Tier (cloud, 200MB limite) ou déploiement Docker local sur Windows pour le dev ? → AuraDB est plus simple mais la limite mémoire peut poser problème sur de gros corpus
4. **Données de calibration Arkéa / Retail Compagnie** : sont-elles accessibles sous forme structurée (ratio LOC/effort) ou nécessitent-elles une extraction manuelle ? → critique pour F2.5 et F4.3
5. **Azure DevOps** : le tenant cible existe-t-il déjà ? → pour F4.6 export
