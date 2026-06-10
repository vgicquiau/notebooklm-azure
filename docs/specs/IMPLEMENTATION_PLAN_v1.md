# Plan d'implémentation — Modernization Agent v1
**Dernière mise à jour** : 2026-06-06
**Sources** : `SDD_ADG-M_v1.md`, `SDD_7RQA_v1.md`, `SDD_ADM-M_v1.md`, `SDD_MWP_v1.md`

> **Convention de durée** : les durées sont en **jours·homme (solo)**. Deux lectures de calendrier en découlent :
> - **Chemin critique ≈ 30 j** : durée incompressible si les tracks parallèles sont menés simultanément (équipe de ~3).
> - **Charge totale ≈ 95,5 j·h (~19 semaines)** : calendrier réel pour **un développeur solo** (pas de parallélisme).
> Le plan de sprints ci-dessous est dimensionné pour une **équipe de ~3** (≈ 8 semaines) ; la colonne « solo » permet de replanifier pour une personne seule.

---

## 1. Analyse de dépendances

### Tableau des tâches et prérequis

| ID | Tâche | Module | Type | Durée (j solo) | Prérequis (IDs) |
|---|---|---|---|---|---|
| T01 | Neo4j Docker Community + plugin GDS + application du schéma Cypher (contraintes/index) | Socle | Infra | 1 | aucun |
| T02 | Provisionner Azure SQL Basic + base `modernagent_db` | Socle | Infra | 0.5 | aucun |
| T03 | Scaffold React (Vite + TS) + auth MSAL + palette partagée | Socle | Frontend | 1.5 | aucun |
| T04 | Scaffold Azure Functions (Python v4) : libs partagées (auth AAD, logging structuré, client HTTP, enveloppe d'erreur) | Socle | Backend | 1.5 | aucun |
| T05 | Azure Static Web Apps + pipeline CI | Socle | Infra | 1 | T03 |
| T06 | Vérifier RAG (Azure AI Search) + déploiements Azure OpenAI (gpt-4o, o4-mini) | Socle | Infra | 0.5 | aucun |
| T10 | DDL SQL ADG-M (`IngestionJob`, `NodeAnnotationHistory`) | ADG-M | Backend | 0.5 | T02 |
| T11 | Pipeline d'ingestion : Blob trigger → parse → extraction GPT-4o → écriture Neo4j → move `processed/` (F1.1) | ADG-M | Backend | 4 | T01, T04, T06 |
| T12 | API lecture : `GET /graph/nodes`, `/graph/nodes/{id}`, `/graph/arcs`, `/graph/health` | ADG-M | Backend | 2 | T01, T04 |
| T13 | API écriture : `PATCH /graph/nodes/{id}/qualification` + historisation | ADG-M | Backend | 1 | T01, T04, T10 |
| T14 | Score de criticité + détection SPOF (betweenness GDS) + `GET /graph/nodes/{id}/impact` (F1.3) | ADG-M | Backend | 2.5 | T01, T12 |
| T15 | Clustering Louvain (GDS) + `GET /graph/clusters` (F1.5) | ADG-M | Backend | 2 | T01, T12 |
| T16 | Frontend Cytoscape : rendu graphe + switch bi-plan (F1.2) | ADG-M | Frontend | 4 | T03, T12 |
| T17 | Frontend : panneau détail + annotation 7R (F1.4) + badge SPOF | ADG-M | Frontend | 2.5 | T16, T13, T14 |
| T18 | Exports JSON clusters + CSV UNQUALIFIED | ADG-M | Backend | 1 | T15 |
| T20 | DDL SQL 7RQA (rapports, dimensions, révisions) + `EffortCalibration` + seed | 7RQA | Backend | 0.5 | T02 |
| T21 | Pipeline Semantic Kernel : chargement nœud (ADG-M) + récupération rétro-doc (RAG) | 7RQA | Backend | 2.5 | T04, T06, T12 |
| T22 | Évaluateurs des 6 dimensions (o4-mini) (F2.1) | 7RQA | Backend | 4 | T21 |
| T23 | Estimation d'effort depuis calibration (F2.5) | 7RQA | Backend | 1.5 | T20, T22 |
| T24 | Assemblage du rapport + persistance + `GET /qualify/report(s)` (F2.2) | 7RQA | Backend | 2 | T22, T23 |
| T25 | `POST /qualify/single/{nodeId}` | 7RQA | Backend | 1 | T24 |
| T26 | Validation/surcharge + write-back ADG-M + révisions (F2.3) — `POST /decision` | 7RQA | Backend | 2 | T25, T13 |
| T27 | Mode batch `POST /qualify/batch` (F2.4) | 7RQA | Backend | 1.5 | T25, T15 |
| T28 | Frontend : `QualificationReportView` + `DecisionActions` + drawer dans le graphe | 7RQA | Frontend | 3 | T16, T25 |
| T29 | Frontend : backlog de qualification + tableau de synthèse portefeuille | 7RQA | Frontend | 2.5 | T28, T27 |
| T30 | DDL SQL ADM-M (profils, positions, critères, historique, ADR) + seed profil | ADM-M | Backend | 0.5 | T02 |
| T31 | Moteur des 12 critères (métriques graphe + GPT-4o pour D1/D4/D6) (F3.1) | ADM-M | Backend | 4 | T12, T14, T06 |
| T32 | Attribution quadrant + palette + `POST/GET /matrix/position` | ADM-M | Backend | 2 | T30, T31 |
| T33 | Profils de pondération (F3.2) `POST/GET /matrix/profile(s)` | ADM-M | Backend | 1 | T30 |
| T34 | `PUT /matrix/position` (surcharge + validation + write-back) + historique (F3.4) | ADM-M | Backend | 2 | T32, T13 |
| T35 | Génération ADR Markdown + export Blob + `GET /matrix/adr` (F3.5) | ADM-M | Backend | 2 | T32, T24 |
| T36 | `GET /matrix/portfolio` (F3.3) | ADM-M | Backend | 1 | T32 |
| T37 | Frontend : quadrant D3.js + panneau de scoring | ADM-M | Frontend | 4 | T03, T32 |
| T38 | Frontend : vue portefeuille + timeline historique + panneau ADR | ADM-M | Frontend | 2.5 | T37, T35, T36 |
| T40 | DDL SQL MWP (plan, vagues, composants, interop, scénarios, statuts) | MWP | Backend | 0.5 | T02 |
| T41 | Tri topologique + détection de cycle (lecture ADG-M) | MWP | Backend | 2 | T12 |
| T42 | Modes VALUE/RISK/BUDGET + validité de vague (3 conditions) (F4.1) | MWP | Backend | 3 | T41, T36 |
| T43 | Estimation effort/durée (lecture `EffortCalibration`) (F4.3) | MWP | Backend | 2 | T40, T20 |
| T44 | Couches d'interopérabilité / états stables / kill criteria (F4.2) | MWP | Backend | 2 | T42, T35 |
| T45 | `POST /wave/generate` + `GET /wave/plan` | MWP | Backend | 1.5 | T42, T43, T44 |
| T46 | Simulation de scénarios `POST /wave/simulate` (F4.4) | MWP | Backend | 2 | T45 |
| T47 | Pilotage `PUT /wave/status` + alertes downstream + dérive (F4.5) | MWP | Backend | 2 | T45 |
| T48 | Export Azure DevOps (Epics/Features) (F4.6) | MWP | Integration | 2 | T45 |
| T49 | Export PowerPoint (python-pptx) + fiches Markdown (F4.6) | MWP | Backend | 2 | T45, T46 |
| T50 | Frontend : Gantt vis-timeline + courbes superposées | MWP | Frontend | 3.5 | T03, T45 |
| T51 | Frontend : comparaison scénarios + dashboard pilotage + panneau export | MWP | Frontend | 3 | T50, T46, T47 |
| T60 | Navigation croisée inter-modules (ADG-M ↔ 7RQA ↔ ADM-M ↔ MWP) | Cross | Integration | 2 | T29, T38, T51 |
| T61 | Test d'intégration bout-en-bout (rétro-doc Retail Compagnie réelle) | Cross | Test | 2 | T60 |
| T62 | Intégration des données de calibration réelles (Arkéa/Retail) | Cross | Backend | 1 | T20 *(+ donnée Q4)* |

**Charge totale** : ≈ **95,5 j·h**. Répartition : Socle 6 · ADG-M 19,5 · 7RQA 20,5 · ADM-M 19 · MWP 25,5 · Cross 5.

### Tâches Day-1 ready (démarrables en parallèle dès le Jour 1)

Aucun prérequis : **T01** (Neo4j+GDS), **T02** (Azure SQL), **T03** (scaffold React), **T04** (scaffold Functions), **T06** (vérif RAG/OpenAI).
*(T05 démarre dès T03 fini ; T10/T20/T30/T40 — les DDL — démarrent dès T02 fini, soit en fin de Jour 1.)*

### Chemin critique

Le goulot est **ADG-M** : ses API de lecture (T12) et ses métriques (T14) débloquent 7RQA, ADM-M et MWP. Le plus long chemin réel du DAG passe par ADM-M (portefeuille) puis MWP (le module le plus lourd) puis l'intégration :

```
T04 → T12 → T14 → T31 → T32 → T36 → T42 → T44 → T45 → T50 → T51 → T60 → T61
1.5    2     2.5    4      2     1     3     2     1.5    3.5    3     2     2
```

**Durée du chemin critique (earliest finish) ≈ 30 j** (avec parallélisme d'équipe).
**Conséquence d'ordonnancement** : prioriser **T12 puis T14** au plus tôt (fin de Sprint 1) est l'action à plus fort effet de levier — tout retard sur ADG-M core décale 7RQA, ADM-M **et** MWP simultanément.

---

## 2. Tracks parallèles

### Track A — Socle & Infrastructure
**Responsabilité** : environnements Azure + locaux, scaffolds backend/frontend, libs transverses (auth, logging, erreurs).
**Peut démarrer** : Jour 1.

| Ordre | Tâche (ID) | Durée | Livrable de vérification |
|---|---|---|---|
| 1 | Neo4j + GDS (T01) | 1j | `SHOW CONSTRAINTS` OK + `gds.version()` répond |
| 2 | Azure SQL + db (T02) | 0.5j | Connexion `sqlcmd` à `modernagent_db` OK |
| 3 | Scaffold Functions (T04) | 1.5j | `func start` répond ; middleware auth/log actif |
| 4 | Scaffold React + MSAL (T03) | 1.5j | `npm run dev` + login Azure AD OK |
| 5 | Vérif RAG/OpenAI (T06) | 0.5j | Requête test index + complétion gpt-4o/o4-mini |
| 6 | Static Web Apps + CI (T05) | 1j | Déploiement automatique sur push |

### Track B — ADG-M (Fondation graphe) — *track bloquant*
**Responsabilité** : ingestion, graphe bi-plan, métriques, clusters, annotation.
**Peut démarrer** : après T01/T04 (≈ Jour 2).

| Ordre | Tâche (ID) | Durée | Livrable de vérification |
|---|---|---|---|
| 1 | DDL ADG-M (T10) | 0.5j | Tables créées |
| 2 | API lecture (T12) | 2j | `GET /graph/nodes` retourne le graphe seedé |
| 3 | Ingestion (T11) | 4j | Rétro-doc → nœuds/arcs en base + `processed/` |
| 4 | Criticité + SPOF + impact (T14) | 2.5j | Badge SPOF + `/impact` cohérents |
| 5 | Clusters Louvain (T15) | 2j | `GET /graph/clusters` retourne ≥1 appartement |
| 6 | PATCH qualification (T13) | 1j | `candidate7R` mis à jour + historique |
| 7 | Frontend graphe bi-plan (T16) | 4j | 3 plans colorés affichés |
| 8 | Frontend détail + annotation (T17) | 2.5j | Annotation 7R depuis le panneau |
| 9 | Exports JSON/CSV (T18) | 1j | Fichiers exportés |

### Track C — 7RQA (Qualification)
**Responsabilité** : dossiers de qualification, validation, batch, calibration.
**Peut démarrer** : après T12 (≈ fin Sprint 1).

| Ordre | Tâche (ID) | Durée | Livrable de vérification |
|---|---|---|---|
| 1 | DDL + calibration seed (T20) | 0.5j | `EffortCalibration` peuplée |
| 2 | Pipeline SK + RAG (T21) | 2.5j | Nœud + rétro-doc chargés |
| 3 | 6 dimensions o4-mini (T22) | 4j | Évaluation structurée retournée |
| 4 | Estimation effort (T23) | 1.5j | Fourchette j·h + réf calibration |
| 5 | Rapport + GET (T24) | 2j | Rapport persisté lisible |
| 6 | `POST /single` (T25) | 1j | Qualification unitaire OK |
| 7 | Décision + write-back (T26) | 2j | 7R propagée dans Neo4j |
| 8 | Batch (T27) | 1.5j | Distribution + FAIBLE confiance |
| 9 | Frontend rapport + actions (T28) | 3j | Rapport affiché + valider/surcharger |
| 10 | Frontend backlog + portefeuille (T29) | 2.5j | Heatmap confiance |

### Track D — ADM-M (Matrice & ADR)
**Responsabilité** : positionnement quadrant, profils, ADR.
**Peut démarrer** : après T12/T14 (≈ fin Sprint 1 / début Sprint 2).

| Ordre | Tâche (ID) | Durée | Livrable de vérification |
|---|---|---|---|
| 1 | DDL + profil seed (T30) | 0.5j | Profil « Uniforme » présent |
| 2 | Moteur 12 critères (T31) | 4j | 12 scores + confiance |
| 3 | Quadrant + position API (T32) | 2j | (D,C) + quadrant + palette |
| 4 | Profils pondération (T33) | 1j | Profil « Banque DORA » créable |
| 5 | Portefeuille (T36) | 1j | `GET /matrix/portfolio` |
| 6 | PUT validate + write-back (T34) | 2j | 7R propagée + version 2 |
| 7 | ADR + Blob (T35) | 2j | ADR Markdown sur Blob |
| 8 | Frontend quadrant + scoring (T37) | 4j | Drag-and-drop + surcharge |
| 9 | Frontend portefeuille + ADR (T38) | 2.5j | Vue d'ensemble + aperçu ADR |

### Track E — MWP (Vagues & exports)
**Responsabilité** : séquençage, estimation, simulation, pilotage, exports.
**Peut démarrer** : tri topo après T12 ; modes après T36 (ADM-M portefeuille).

| Ordre | Tâche (ID) | Durée | Livrable de vérification |
|---|---|---|---|
| 1 | DDL MWP (T40) | 0.5j | Tables créées |
| 2 | Tri topologique + cycles (T41) | 2j | Ordre + cycles détectés |
| 3 | Effort/durée (T43) | 2j | Effort par composant chiffré |
| 4 | Modes + validité vague (T42) | 3j | 3 modes produisent des plans distincts |
| 5 | Interop / états stables (T44) | 2j | Kill criteria + double run |
| 6 | `POST /generate` + GET (T45) | 1.5j | Plan complet retourné |
| 7 | Simulation (T46) | 2j | 3 variantes comparées |
| 8 | Pilotage statut (T47) | 2j | Alertes downstream + dérive |
| 9 | Export DevOps (T48) | 2j | Epics/Features créés |
| 10 | Export PPTX + MD (T49) | 2j | Deck généré |
| 11 | Frontend Gantt (T50) | 3.5j | Timeline + courbes |
| 12 | Frontend comparaison + pilotage (T51) | 3j | Dashboard pilotage |

### Track F — Intégration (transverse, fin de programme)
**Responsabilité** : navigation croisée, E2E, calibration réelle.
**Peut démarrer** : après les frontends des 4 modules.

| Ordre | Tâche (ID) | Durée | Livrable de vérification |
|---|---|---|---|
| 1 | Navigation croisée (T60) | 2j | Parcours ADG-M→7RQA→ADM-M→MWP fluide |
| 2 | E2E rétro-doc réelle (T61) | 2j | Chaîne complète validée |
| 3 | Calibration réelle (T62) | 1j | `EffortCalibration` mise à jour (si donnée Q4) |

---

## 3. Plan de sprints (semaines de 5 jours ouvrés)

> Dimensionné pour une **équipe de ~3**. En solo, dérouler les tracks séquentiellement (≈ 19 semaines).

### Sprint 0 — Semaine 1 — « Le socle tient debout »
**Tracks actifs** :
- Track A : T01, T02, T04, T03, T06 (T05 en fin de semaine)
**Livrable de fin de sprint** : un appel `GET /graph/health` répond 200 ; le frontend affiche un écran vide authentifié Azure AD ; Neo4j+GDS et `modernagent_db` opérationnels.
**Définition de « Done »** :
- [ ] `func start` + `npm run dev` fonctionnent en local
- [ ] Neo4j répond et GDS est installé (`gds.version()`)
- [ ] Connexion RAG + OpenAI (gpt-4o, o4-mini) vérifiée

### Sprint 1 — Semaines 2-3 — « Le patrimoine est cartographié » *(gate critique)*
**Tracks actifs** :
- Track B : T10, T12, T11, T14 (puis T13, T15) — **priorité absolue à T12 puis T14**
- Track A : T05 (finalisation CI)
**Livrable de fin de sprint** : ingérer une rétro-doc et voir le graphe via API ; criticité/SPOF calculés.
**Définition de « Done »** :
- [ ] Ingestion d'une rétro-doc crée nœuds + arcs dans Neo4j
- [ ] `GET /graph/nodes` / `/arcs` / `/nodes/{id}/impact` répondent
- [ ] SPOF détecté sur le corpus de test

### Sprint 2 — Semaines 4-5 — « On voit, on décide, on positionne »
**Tracks actifs** :
- Track B : T16, T17, T18 (frontend graphe + annotation + exports)
- Track C : T20, T21, T22, T23 (pipeline + 6 dimensions + effort)
- Track D : T30, T31, T32, T33, T36 (12 critères + quadrant + portefeuille)
**Livrable de fin de sprint** : graphe bi-plan interactif affiché ; un composant qualifié (rapport 6 dimensions) ; un composant positionné sur le quadrant.
**Définition de « Done »** :
- [ ] Les 3 plans (fonctionnel/technique/superposé) s'affichent
- [ ] `POST /qualify/single` produit un rapport complet
- [ ] `POST /matrix/position` place un composant dans le bon quadrant

### Sprint 3 — Semaine 6 — « La décision devient traçable »
**Tracks actifs** :
- Track C : T24, T25, T26, T27, T28, T29 (rapport, write-back, batch, frontend)
- Track D : T34, T35, T37, T38 (validation, ADR, frontend quadrant)
- Track E : T40, T41, T43 (tri topo + effort — démarrage MWP)
**Livrable de fin de sprint** : qualifier → valider → 7R écrite dans le graphe ; ADR généré sur Blob ; quadrant portefeuille affiché.
**Définition de « Done »** :
- [ ] Validation 7RQA propage la 7R dans Neo4j + révision SQL
- [ ] ADR Markdown généré et exporté
- [ ] Vue portefeuille (quadrant + backlog confiance) fonctionnelle

### Sprint 4 — Semaine 7 — « Le programme se planifie »
**Tracks actifs** :
- Track E : T42, T44, T45, T46, T47 (modes, états stables, génération, simulation, pilotage)
**Livrable de fin de sprint** : générer un plan de vagues à partir des décisions, comparer 3 scénarios.
**Définition de « Done »** :
- [ ] `POST /wave/generate` produit des vagues valides (3 conditions)
- [ ] `POST /wave/simulate` compare 3 variantes sur 3 indicateurs
- [ ] `PUT /wave/status` signale les déblocages downstream

### Sprint 5 — Semaine 8 — « La chaîne complète, du legacy au COMEX »
**Tracks actifs** :
- Track E : T48, T49, T50, T51 (exports DevOps/PPTX + frontend Gantt + pilotage)
- Track F : T60, T61, T62 (navigation croisée, E2E, calibration réelle)
**Livrable de fin de sprint** : démonstration de bout en bout — rétro-doc → graphe → qualification → quadrant/ADR → plan de vagues → deck COMEX + backlog Azure DevOps.
**Définition de « Done »** :
- [ ] Navigation croisée entre les 4 modules
- [ ] Export Azure DevOps (Epics/Features) + PowerPoint
- [ ] Test E2E sur rétro-doc Retail Compagnie réelle vert

---

## 4. Jalons et démos intermédiaires

| Jalon | Sprint | Ce qui est démontrable | Données de démo recommandées |
|---|---|---|---|
| **M1 — Patrimoine cartographié** | Sprint 1 | « Je dépose une rétro-doc, je vois le graphe bi-plan avec les SPOF en rouge. » | Rétro-doc Retail Compagnie réelle (Gestion des commandes) |
| **M2 — Trajectoire décidée** | Sprint 2 | « Je clique sur un composant, j'obtiens un dossier 7R argumenté, chiffré, opposable. » | GESTION-COMMANDE (18 420 lignes, BCBS239) |
| **M3 — Lecture stratégique** | Sprint 3 | « Je vois tout le patrimoine en Core/Context et je génère un ADR signé. » | Portefeuille de ~30 composants positionnés |
| **M4 — Programme chiffré** | Sprint 4 | « Je compare 3 trajectoires de migration sur valeur/risque/coût de double run. » | Clusters cl-commandes-01 + cl-facturation-02 |
| **M5 — Chaîne COMEX complète** | Sprint 5 | « Du legacy au deck COMEX et au backlog Azure DevOps, en une session. » | Corpus complet + organisation Azure DevOps |

---

## 5. Tableau de parallélisme semaine par semaine

| Semaine | Track A (Socle) | Track B (ADG-M) | Track C (7RQA) | Track D (ADM-M) | Track E (MWP) | Track F (Intég.) |
|---|---|---|---|---|---|---|
| **S1** | T01,T02,T04,T03,T06 | — | — | — | — | — |
| **S2** | T05 | T10,T12,T11 | — | — | — | — |
| **S3** | — | T14,T13,T15 | T20,T21 | T30,T31 | — | — |
| **S4** | — | T16,T17,T18 | T22,T23 | T32,T33,T36 | — | — |
| **S5** | — | — | T24,T25,T26 | T34,T35,T37 | T40,T41,T43 | — |
| **S6** | — | — | T27,T28,T29 | T38 | T42,T44,T45 | — |
| **S7** | — | — | — | — | T46,T47,T48,T49,T50 | — |
| **S8** | — | — | — | — | T51 | T60,T61,T62 |

> Lecture : après le **gate ADG-M** (S2-S3), trois tracks (C, D, puis E) avancent en parallèle. Le module **MWP** (Track E) concentre la charge de fin de programme — c'est le segment final du chemin critique.

---

## 6. Risques et points de blocage

| # | Risque | Probabilité | Impact | Mitigation |
|---|---|---|---|---|
| 1 | **Données de calibration Arkéa/Retail indisponibles** (Q4) — l'effort 7RQA/MWP repose dessus. | Élevée | Élevé | Démarrer sur valeurs indicatives (table `EffortCalibration` seedée) + intervalles larges ; isoler T62 en fin de programme ; afficher la réf de calibration pour traçabilité. La valeur produit ne dépend pas de la précision absolue mais de la cohérence relative. |
| 2 | **ADG-M est le goulot** : T12/T14 bloquent 7RQA, ADM-M ET MWP. | Moyenne | Élevé | Prioriser T12 puis T14 dès le début du Sprint 1 ; figer tôt les contrats d'API (déjà faits dans les SDDs) pour permettre aux tracks C/D/E de coder contre des mocks avant la fin réelle d'ADG-M. |
| 3 | **Qualité d'extraction GPT-4o variable** selon le format des rétro-docs (Q1). | Moyenne | Élevé | Validation de schéma stricte à l'ingestion (rejet → `ERR_ADGM_002`), rejouabilité (`force=true`), normalisation amont ; jeu de fixtures représentatif dès Sprint 1. |
| 4 | **Modèle o4-mini indisponible** dans la région Azure (Q3). | Moyenne | Moyen | Repli configurable `o3-mini` ou GPT-4o en chaîne de raisonnement structurée ; variable `AZURE_OPENAI_DEPLOYMENT_REASONING` isole le changement. |
| 5 | **Hébergement Neo4j** sous contrainte « Azure, sans Marketplace » (Q2). | Faible | Moyen | Image Docker Neo4j Community + GDS : Docker Desktop (PC) en dev, **Azure Container Instances / Container Apps** en cloud (first-party, hors Marketplace). Fallback si graphe managé Azure-natif imposé : Cosmos DB Gremlin + Louvain/betweenness réimplémentés (networkx). |
| 6 | **Organisation Azure DevOps absente** (Q5) — export F4.6. | Faible | Faible | Export DevOps désactivable ; Markdown + PowerPoint suffisent aux démos M4/M5 ; brancher DevOps quand le tenant est disponible. |

---

## Annexe — Décisions transverses à trancher (consolidées des SDDs)

Ces points sont repris de la section 10 de chaque SDD et de `PROGRESS.md`. Ils ne bloquent pas le démarrage (hypothèses retenues) mais doivent être confirmés avant la mise en production :

1. **Q1 — Format des rétro-docs ArchiMind** (Markdown/JSON) → impacte T11.
2. **Q2 — Hébergement Neo4j** sous contrainte « Azure sans Marketplace » : image Docker Community + GDS, PC en dev / **ACI / Container Apps** en cloud → impacte T01, T14, T15.
3. **Q3 — Déploiement o4-mini** → impacte T22.
4. **Q4 — Données de calibration réelles** → impacte T23, T43, T62.
5. **Q5 — Tenant Azure DevOps** → impacte T48.
6. **Q6 — Granularité Azure AD** (mono-utilisateur retenu) → impacte T04, T07.
7. **Q7 — Quadrant ADM-M** : incohérence des specs résolue en lecture Core/Context → impacte T31, T32, T37 (à confirmer par l'architecte métier).
