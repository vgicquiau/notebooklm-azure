# Glossaire & Taxonomie GraphRAG — Legacy Modernisation
## Référentiel générique de langage commun

> **Version** : 2.0 — Généraliste (technologie-agnostique)
> **Usage** : Document de référence injectable dans le pipeline d'extraction GraphRAG.
> Paramétrable par contexte technologique via la **Partie E**.
>
> **Double usage** :
> 1. **Instruire le LLM extracteur** (Phase 2 — `extract.py`) : fournir à GPT-4o/Claude les définitions et marqueurs pour reconnaître, nommer et classer chaque entité dans n'importe quel corpus de documentation legacy.
> 2. **Contraindre le schéma Neo4j** (Phase 3 — import graph) : définir les labels de nœuds, les types de relations et les propriétés attendues de façon stable entre les engagements.
>
> **Conventions** :
> - `[TYPE_EXEMPLE]` : exemple illustratif générique, à remplacer par les noms réels du système cible.
> - **[Nœud]** / **[Relation]** / **[Propriété]** : rôle dans le graphe Neo4j.
> - Les termes marqués `[existant]` figuraient dans la version initiale du glossaire.

---

## Principes d'organisation — 8 couches

| # | Couche | Rôle dans le graphe | Labels / Types couverts |
|---|--------|---------------------|-------------------------|
| 0 | **Méta-fiabilité** | Propriétés transverses — qualifient toute assertion du graphe | `fiabilite`, `source`, `incertitude` |
| 1 | **Fonctionnelle** | Domaines, règles et processus fonctionnels | `Domaine_Fonctionnel`, `Processus_Fonctionnel`, `Fonction`, `Regle_Metier` |
| 2 | **Applicative** | Artefacts exécutables (programmes, jobs, transactions) | `Composant`, `Point_Entree`, `Interface_Utilisateur`, `Job_Batch`, `Unite_Execution`, `Procedure_Reutilisable`, `Domaine_Technique` |
| 3 | **Données** | Stores physiques et structures partagées | `Store_Donnees`, `Store_Echange`, `Table_Relationnelle`, `Store_Hierarchique`, `Structure_Partagee`, `Entite_Donnees`, `Canal_Messagerie` |
| 4 | **Intégration** | Liens et flux entre composants | `Flux`, `Interface`, `Dependance`, `Point_Integration` |
| 5 | **Architecture DDD** | Découpage cible et patterns de décomposition | `Bounded_Context`, `Aggregate`, `Anti_Corruption_Layer`, `Evenement_Domaine`, `Context_Map` |
| 6 | **Risque & Qualité** | Métriques et détection de risques structurels | `SPOF`, `Zone_Contention`, `Communaute_Louvain`, `Noeud_Articulation` + propriétés analytiques |
| 7 | **Modernisation** | Trajectoire et gouvernance de transformation | `Declencheur`, `Strategie_Transformation`, `Decision_Architecture`, `Zone_Incertitude`, `Periode_Double_Run` |

---

## COUCHE 0 — Méta-fiabilité (propriétés transverses)

> Ces quatre concepts ne sont **pas des nœuds** dans le graphe : ce sont des **valeurs de la propriété `fiabilite`**, applicable à tout nœud ou relation.
> Couche la plus critique : sans elle, le graphe ne peut pas distinguer ce qui est prouvé de ce qui est supposé par le LLM extracteur.
> **Règle absolue** : tout nœud extrait sans source identifiable dans le corpus doit être classé `SUPPOSÉ` ou `MANQUANT`, jamais `FAIT`.

| Valeur | Définition | Signal d'identification | Impact sur le graphe |
|--------|------------|------------------------|----------------------|
| **FAIT** | Information directement observable et vérifiable dans un artefact source (code, DDL, JCL, documentation formelle). Aucune inférence requise. | Instruction de code explicite, définition dans un fichier source, entrée dans un catalogue ou un CSD, colonne d'une matrice documentée. | Nœud/relation de confiance maximale — exploitable pour les décisions d'architecture. |
| **HYPOTHÈSE** | Information déduite par analyse logique à partir de faits observés. Vraisemblable, falsifiable, non encore confirmée formellement par une source humaine. | Raisonnement par inférence : "N composants appellent ce module, donc il est probablement un hub", "seul composant à écrire dans ce store, donc probablement propriétaire". | Nœud/relation exploitable mais à valider avant décision bloquante. |
| **SUPPOSÉ** | Inférence sans source fiable dans le corpus. Risque élevé de propagation d'erreur. À valider impérativement avant toute décision architecturale. | Phrases : "probablement", "devrait", "on suppose que", "non identifié dans le corpus". Référence à un composant dont aucune définition n'est disponible. | Nœud/relation signalé visuellement (⚠️) — génère automatiquement une `Zone_Incertitude`. |
| **MANQUANT** | Information nécessaire à l'analyse mais absente du corpus. Doit déclencher la création d'une `Zone_Incertitude` et l'identification du détenteur de l'information. | Référence à un composant, fichier ou système sans définition disponible. Trou dans une matrice de flux ou un inventaire. | Nœud fantôme ou absence de nœud — bloque les analyses de chemin critique. |

---

## COUCHE 1 — Fonctionnelle

> **Structure et rôles** :
>
> | Concept | Question | Rôle dans la couche |
> |---------|----------|---------------------|
> | `Domaine_Fonctionnel` | *Quoi — le cadre* | Grand ensemble cohérent d'activités ; **contient** des `Processus_Fonctionnel` et **catalogue** des `Fonction` |
> | `Processus_Fonctionnel` | *Comment & Quand* | Suite ordonnée d'activités déclenchée par un événement ; orchestre des `Fonction` ; ses branchements sont orientés par des `Regle_Metier` |
> | `Fonction` | *Quoi — l'action* | Action élémentaire réutilisable ; peut être appelée par plusieurs processus ; sa logique interne est gouvernée par des `Regle_Metier` |
> | `Regle_Metier` | *Sous quelles conditions ?* | **Double rôle** : (1) dicte la logique interne d'une `Fonction` ; (2) oriente les branchements d'un `Processus_Fonctionnel` |
>
> La couche fonctionnelle est **indépendante de la technologie** — elle décrit ce que fait l'application et quand, pas comment.

| Label Neo4j | Définition | Signal d'identification dans le corpus | Exemple illustratif | Type graphe |
|-------------|------------|----------------------------------------|---------------------|-------------|
| `Domaine_Fonctionnel` | **Cadre majeur** — grand ensemble cohérent de l'activité d'une organisation. Joue un double rôle : (1) il **contient structurellement** un ou plusieurs `Processus_Fonctionnel` ; (2) il **catalogue logiquement** des `Fonction`, indépendamment du moment où elles sont exécutées. Frontière de cohérence sémantique indépendante de la technologie. | Section de document intitulée "Domaine [N]", "Périmètre [métier]" ou "Secteur d'activité". Regroupement de processus et fonctions autour d'un même objet métier. Identifiant type `D-[NOM]` ou `DOM-[NNN]`. | `D-VENTES` (Gestion des Ventes), `D-RH` (Ressources Humaines), `D-COMPTA` (Comptabilité) | **[Nœud]** |
| `Processus_Fonctionnel` | **Suite ordonnée d'activités déclenchée par un événement**, visant à produire un résultat de valeur. Le processus est le "comment" et le "quand" : il donne le sens logique, le timing et l'ordre d'enchaînement des `Fonction`. Ses **branchements sont orientés par des `Regle_Metier`** (conditions de routage : "si dossier incomplet, retourner à l'étape précédente"). Peut mobiliser des fonctions d'un même domaine ou de domaines différents. | Description d'un workflow déclenché par un événement ("clic sur Acheter", "réception d'un virement", "fin de mois"). Diagramme de séquence ou d'activité. Section de documentation de cinématique applicative ou d'ordonnancement. | `Passer une commande en ligne` (déclencheur : clic "Acheter"), `Intégration d'un nouveau collaborateur` (déclencheur : signature contrat), `Clôture mensuelle` (déclencheur : fin de mois) | **[Nœud]** |
| `Fonction` | **Action élémentaire et réutilisable** que le système doit être capable de réaliser — le "quoi" à la granularité d'une opération. Une même fonction peut être **appelée par plusieurs processus fonctionnels différents** (réutilisabilité). Elle applique des `Regle_Metier` pour exécuter correctement son traitement algorithmique. Appartient au catalogue d'un `Domaine_Fonctionnel` indépendamment de tout processus. **Ne pas agréger** : chaque opération identifiable est une fonction distincte. | Verbe métier + objet dans un titre, une option de menu ou une spécification : "Calculer la TVA", "Émettre une alerte", "Valider un paiement". Identifiant type `F-[NNN]`. Capacité citée dans plusieurs processus différents = signal de réutilisabilité. | `F-042 — Calculer les frais de port`, `F-071 — Valider l'autorisation de paiement`, `F-018 — Générer un relevé de compte` | **[Nœud]** |
| `Regle_Metier` | Contrainte, calcul ou directive métier textuelle régissant le comportement de l'entreprise. **Double rôle selon le contexte** : (1) appliquée à une `Fonction` — dicte sa logique interne (calcul exact, critères de validation) ; (2) appliquée à un `Processus_Fonctionnel` — dicte les conditions de routage (les choix aux aiguillages du flux). Invariant fonctionnel qui doit survivre à la modernisation. Propriété du domaine, pas du composant — même si elle est encodée dans le code. Peut être explicite ou implicite (connaissance tacite d'un expert). | Identifiant `RG-[NNN]`. Formulation normative : "doit", "ne peut pas", "si X alors Y", "est interdit si". Condition de validation dans le code (`IF`, `WHEN`, `CASE`). Contrainte énoncée dans la documentation métier. | `RG-015 : frais de port = 0 si commande > 50 €` (logique interne de `F-042`), `RG-032 : si dossier incomplet → retour étape validation` (routage dans le processus `Passer une commande en ligne`) | **[Nœud]** |
| `Domaine_Technique` | Ensemble cohérent de composants, jobs et structures de données partageant une technologie et une responsabilité d'exécution. **Frontière architecturale de groupement — pas une capacité métier.** Un domaine technique peut recouper plusieurs domaines fonctionnels, et inversement. | Identifiant `DT-[NN]`. Regroupement de sources dans un répertoire ou un projet de build commun. Section "domaine technique" ou "couche applicative" dans une cartographie. | `DT-01 — Servicing online`, `DT-05 — Traitements batch de clôture` | **[Nœud]** |

---

## COUCHE 2 — Applicative (artefacts exécutables)

> **Note de paramétrage** : les noms de labels Neo4j de cette couche sont délibérément **génériques** (`Composant`, `Point_Entree`, etc.) pour couvrir tout stack technologique. Les marqueurs d'identification spécifiques par technologie (COBOL, PACBASE, RPG, NATURAL...) sont détaillés en **Partie E**.

| Label Neo4j | Définition | Signal d'identification (générique) | Exemple illustratif | Type graphe |
|-------------|------------|-------------------------------------|---------------------|-------------|
| `Composant` | Unité compilée et exécutable autonome. Nœud central du graphe applicatif. Possède un identifiant unique, peut en appeler d'autres ou être appelé. Équivalent à : programme COBOL, module NATURAL, programme RPG, objet ABAP, script PL/SQL, service applicatif. | Présence d'une unité de compilation autonome avec un identifiant unique. Référencé par un appel (`CALL`, `PERFORM`, `LINK`, `EXECUTE`, etc.). Extension de fichier spécifique à la technologie. | `[NAVMENU]` (menu principal), `[CALC_INTERETS]` (calcul batch intérêts), `[VALID_PAIEMENT]` (validation transaction) | **[Nœud]** |
| `Point_Entree` | Identifiant d'invocation d'un composant depuis une couche d'orchestration (runtime online, scheduler batch). Distinct du composant lui-même : c'est le "nom de déclenchement" enregistré dans le catalogue du runtime. | Identifiant 4–8 caractères enregistré dans un catalogue runtime (CSD CICS, menu AS/400, T-code SAP, entrée de scheduler). Associé à un composant de premier appel. | `[TXPMT]` → déclenche `[PAIMENT_MAIN]`, `[TXCPT]` → déclenche `[COMPTE_VIEW]` | **[Nœud]** |
| `Interface_Utilisateur` | Définition d'une vue/écran/formulaire contrôlant la présentation et la saisie dans une transaction interactive. Compilée séparément du composant de traitement. | Source de définition d'écran (BMS, DDS, map NATURAL, formulaire Oracle Forms, screen definition AS/400). Instruction d'envoi/réception d'écran dans un composant (`SEND MAP`, `EXFMT`, `WRITE WORKSSTN`). | `[ECRAN_SAISIE_VIREMENT]`, `[FORMULAIRE_OUVERTURE_COMPTE]` | **[Nœud]** |
| `Job_Batch` | Unité d'exécution batch soumise à un gestionnaire de travaux ou un scheduler. Contient une ou plusieurs `Unite_Execution`. Identifié par un nom unique dans le scheduler. | Fichier de définition de job (`.jcl`, `.cj`, script shell batch, définition Control-M/CA7). Référencé dans un ordonnanceur. Déclenché périodiquement ou par événement. | `[JOB_CLOTURE_NUIT]`, `[JOB_EXTRACT_REPORTING]`, `[JOB_CALCUL_SOLDES]` | **[Nœud]** |
| `Unite_Execution` | Composant élémentaire d'un `Job_Batch`, référençant un `Composant` ou une `Procedure_Reutilisable`. Définit les ressources (entrées/sorties) de son composant. | Step JCL (`EXEC PGM=`), étape batch dans un scheduler, invocation de programme dans un script de traitement. Associations DD/allocation de fichiers. | `[STEP-CALCUL-INTERETS]` dans `[JOB_CLOTURE_NUIT]` | **[Nœud]** |
| `Procedure_Reutilisable` | Ensemble de `Unite_Execution` catalogué et invocable depuis plusieurs `Job_Batch`. Factorisation des séquences de traitement récurrentes. | Fichier de procédure cataloguée (`.prc`, `.proc`, include de script). Invocable par référence depuis un job. | `[PROC_COMPILE_BATCH]`, `[PROC_ARCHIVAGE_FICHIERS]` | **[Nœud]** |

---

## COUCHE 3 — Données (stores physiques et structures partagées)

> **Note de paramétrage** : les labels Neo4j utilisent des termes génériques. Le mapping vers les technologies spécifiques (VSAM, ADABAS, AS/400 physical file, etc.) est en **Partie E**.

| Label Neo4j | Définition | Signal d'identification (générique) | Exemple illustratif | Type graphe |
|-------------|------------|-------------------------------------|---------------------|-------------|
| `Store_Donnees` | Fichier ou base de données persistant(e) avec accès direct par clé (indexé, séquentiel-indexé, hiérarchique). Stockage persistant principal du système. | Déclaration de fichier indexé dans le code source. Instruction d'accès par clé (`READ ... KEY IS`, `CHAIN`, `SETLL/READE`). Définition DDL ou cluster VSAM. Propriété `type: KSDS | ESDS | RRDS | Physical_File | ADABAS | ...`. | `[FICHIER_COMPTES]` (accès clé par numéro de compte), `[FICHIER_CLIENTS]` (accès clé par identifiant client) | **[Nœud]** |
| `Store_Echange` | Fichier ou flux séquentiel utilisé pour les échanges inter-composants ou inter-systèmes. Pas d'accès direct par clé. Souvent transitoire (entrée d'un batch, export vers un tiers). | Organisation séquentielle dans le code source (`SEQUENTIAL`, `LINE SEQUENTIAL`). Extension `.PS`, `.GDG`, `.csv`, `.dat`. Clauses d'allocation dans un job batch. | `[FLUX_TRANSACTIONS_JOURNEE]`, `[EXPORT_REPORTING_HEBDO]`, `[IMPORT_VIREMENTS_EXTERNES]` | **[Nœud]** |
| `Table_Relationnelle` | Table dans un SGBDR embarqué ou distribué. Source de vérité pour les référentiels et les données structurées. Accès par SQL statique précompilé ou dynamique. | Instruction `SELECT/INSERT/UPDATE/DELETE` dans le code source. Fichier DDL (`CREATE TABLE`). Copybook généré par DCLGEN ou équivalent. Schéma qualifié `[SCHEMA].[TABLE]`. | `[DB.REFERENTIEL_TAUX]`, `[DB.FRAUD_EVENTS]`, `[DB.TRANSACTION_TYPES]` | **[Nœud]** |
| `Store_Hierarchique` | Base de données hiérarchique ou réseau (IMS, IDMS, ADABAS). Accès via API spécifique (DL/I, DML, ADABAS commands). Souvent irremplaçable à court terme — migration complexe. | Instruction d'accès spécifique (`EXEC DLI`, `FIND`, `READ ISN`, `L1`/`L2`). Référence à un segment, un DBD ou un PSB. Définition de record/segment dans un schéma de base hiérarchique. | `[SEGM_AUTORISATIONS_ENCOURS]`, `[SEGM_HISTORIQUE_TRANSACTIONS]` | **[Nœud]** |
| `Structure_Partagee` | Module de définition de données partagé par référence entre plusieurs composants. Nœud transversal du graphe : partagé par N composants = point de couplage structurel. Ne contient jamais de logique exécutable. | Instruction d'inclusion par référence (`COPY`, `INCLUDE`, `/COPY`, `++INCLUDE`). Extension spécifique au langage (`.cpy`, `.inc`, `.dds`). Membre d'une bibliothèque de structures partagées. Jamais un point d'entrée exécutable. | `[STRUCT_COMMAREA_NAV]` (structure de navigation partagée), `[STRUCT_ENTETE_MSG]` (en-tête de message partagé) | **[Nœud]** |
| `Entite_Donnees` | Objet métier persisté, abstraction au-dessus du stockage physique. Permet de raisonner sur la donnée indépendamment du support (fichier indexé, table SQL, store hiérarchique). Une entité peut être portée par plusieurs stores physiques. | Identifiant `E[NN]` ou `ENT-[NOM]` dans une matrice CRUD ou un dictionnaire de données. Concept métier nommé dans la documentation. Objet dont les attributs sont décrits dans une structure partagée ou un DDL. | `Client` (→ `[FICHIER_CLIENTS]`), `Compte` (→ `[FICHIER_COMPTES]`), `Transaction` (→ `[STORE_TRANSACTIONS]`) | **[Nœud]** |
| `Canal_Messagerie` | Canal de messagerie asynchrone (MQ, Kafka topic, queue JMS, fichier d'échange événementiel). Point d'intégration externe ou inter-domaine. Un message entrant déclenche un traitement, un message sortant notifie un consommateur. | Référence à une file ou un topic dans le code source ou une configuration. API de messagerie (`MQPUT`, `MQGET`, `produce`, `consume`). Définition de service ou de connecteur dans un fichier de configuration applicatif. | `[QUEUE_DEMANDES_AUTORISATION]`, `[TOPIC_TRANSACTIONS_VALIDEES]` | **[Nœud]** |

---

## COUCHE 4 — Intégration

| Label Neo4j | Définition | Signal d'identification | Exemple illustratif | Type graphe |
|-------------|------------|------------------------|---------------------|-------------|
| `Flux` | Lien orienté entre deux composants représentant un échange de données ou un appel de service à l'exécution. Unité de base de la Matrice de Flux. Propriétés : `mode` (SYNCHRO / ASYNCHRO / FICHIER / EVENEMENT), `type` (CALL / REDIRECT / ACCES_DONNEES / MESSAGE / FILE), `fiabilite`. | Toute instruction de transfert de contrôle ou d'accès à un store dans le code source : appel de composant, lecture/écriture de store, envoi/réception de message, écriture dans un fichier d'échange. | `[CALC_INTERETS]` →[ACCÈS_LECTURE]→ `[FICHIER_COMPTES]`, `[VALID_PAIEMENT]` →[CALL]→ `[VERIF_FRAUDE]` | **[Relation]** |
| `Interface` | Point de contact formalisé entre deux systèmes ou domaines, indépendamment du protocole. Abstraction au-dessus des flux techniques. Porte une sémantique métier ("service de consultation solde", "canal d'autorisation externe"). | Description d'une intégration inter-système dans un DAT ou un catalogue d'interfaces. Frontière nommée entre deux domaines dans une cartographie. Contrat d'échange documenté. | `Interface RESTful Consultation Compte` (entre système tiers et domaine Compte), `Interface fichier batch Transactions Externes` | **[Nœud]** |
| `Dependance` | Relation structurelle orientée de dépendance statique entre deux artefacts. Différent d'un Flux (dynamique, runtime) : la dépendance est une contrainte de compilation ou d'inclusion. Types : `INCLUSION` (composant→structure partagée), `APPEL_STATIQUE` (composant→composant), `DÉCLENCHEMENT` (job→composant). | `COPY / INCLUDE` d'une structure → `INCLUSION`. Appel résolu à la compilation → `APPEL_STATIQUE`. Référence `EXEC PGM=` ou équivalent → `DÉCLENCHEMENT`. Fan-in/fan-out élevés signalent des points de couplage fort. | `[CALCUL_REMISE]` a une dépendance `INCLUSION` vers `[STRUCT_GRILLE_TARIF]` partagée par 12 composants | **[Relation]** |
| `Point_Integration` | Nœud dans le graphe où plusieurs flux convergent ou divergent, créant un couplage structurel entre domaines. Candidat automatique à l'analyse SPOF et à la définition d'une Anti-Corruption Layer. | Nombre d'arcs entrants (fan-in) ou sortants (fan-out) supérieur à un seuil paramétrable (ex : > 5). Composant appartenant à plusieurs communautés Louvain. Score de betweenness centrality élevé. | `[ORCHESTRATEUR_NAVIGATION]` (hub central appelé par 8 composants), `[REFERENTIEL_CODES_POSTAUX]` (lu par 15 composants) | **[Nœud]** |

---

## COUCHE 5 — Architecture DDD (découpage cible)

| Label Neo4j | Définition | Signal d'identification | Exemple illustratif | Type graphe |
|-------------|------------|------------------------|---------------------|-------------|
| `Bounded_Context` | Périmètre DDD délimitant une sous-partie cohérente du domaine métier, avec son modèle de domaine propre, son Ubiquitous Language et son équipe de responsabilité. Frontière contractuelle dans l'architecture cible. Toute communication inter-BC passe par une Interface formalisée. | Identifiant `BC-[NOM]`. Section "Bounded Context" dans un DAT ou une étude DDD. Fiche d'appartement onepoint. Regroupement de composants et d'entités de données autour d'une cohérence métier. | `BC-Identite`, `BC-Client`, `BC-Compte`, `BC-Paiement`, `BC-Fraude_Autorisation` | **[Nœud]** |
| `Aggregate` | Cluster d'entités et de value objects traités comme une unité de cohérence transactionnelle dans un Bounded Context. Accessible uniquement via sa racine (Aggregate Root). Garantit les invariants du domaine. | Entité nommée comme "racine" dans un diagramme de tactical design. Terme "Aggregate Root" dans la documentation DDD. Objet dont tous les sous-objets sont inaccessibles directement depuis l'extérieur du cluster. | `Compte` (racine du cluster Compte + Lignes de crédit + Soldes), `Commande` (racine + LignesCommande + Paiement) | **[Nœud]** |
| `Anti_Corruption_Layer` | Couche d'isolation entre le système Legacy et le système cible, absorbant les différences sémantiques, structurelles et technologiques. N'ajoute aucune logique métier — traduit uniquement. Composant temporaire dont la durée de vie est bornée à la migration. | Mention de "ACL", "couche d'adaptation", "traducteur Legacy↔cible" dans un DAT ou un ADR. Composant dont la responsabilité est définie comme "conversion de format" ou "mapping sémantique". | ACL entre le batch de posting Legacy et le Write Model du `BC-Transaction` cible | **[Nœud]** |
| `Evenement_Domaine` | Fait métier passé, immutable, nommé au passé actif. Unité de communication asynchrone entre Bounded Contexts. Ne peut jamais être modifié ou supprimé (append-only). Porte une sémantique métier forte. | Nom en PascalCase au passé : `CompteOuvert`, `PaiementValidé`, `FraudeDetectée`. Post-it orange dans un Event Storming. Payload JSON avec un timestamp `occurred_at`. | `TransactionComptabilisée`, `LimiteCreditDepassée`, `UtilisateurBloque` | **[Nœud]** |
| `Context_Map` | Vue de l'ensemble des Bounded Contexts et de leurs relations d'intégration, avec qualification du pattern de chaque relation (Upstream/Downstream, Shared Kernel, ACL, Conformist, Open Host Service, Published Language). | Diagramme de Context Map dans un DAT ou une étude DDD. Tableau des relations BC avec pattern qualifié. | Relation `BC-Client` (Upstream) → `BC-Compte` (Downstream, Conformist) | **[Nœud]** |

---

## COUCHE 6 — Risque & Qualité

| Label Neo4j | Définition | Signal d'identification | Exemple illustratif | Type graphe / Propriété |
|-------------|------------|------------------------|---------------------|--------------------------|
| `SPOF` | Single Point of Failure — composant dont la défaillance entraîne l'arrêt ou la corruption d'une chaîne critique, sans chemin alternatif identifié. Détecté par analyse de point d'articulation dans le graphe et/ou score de betweenness anormalement élevé. | Identifiant `SPOF-[NNN]` ou `R[NN]` dans un référentiel de risques. Propriété `isSpof: true`. Composant avec `betweennessScore` > seuil configuré. Composant unique entre deux sous-graphes. | `[ORCHESTRATEUR_NAVIGATION]` : retire-le, les composants aval sont injoignables. `[FICHIER_DALYTRAN]` : producteur inconnu = SPOF de données. | **[Nœud]** + `isSpof: boolean` |
| `Zone_Contention` | Situation de concurrence d'accès en écriture sur un même store par plusieurs composants appartenant à des domaines distincts, sans mécanisme de coordination formalisé. Risque de corruption lors d'une migration partielle. | Même store avec des instructions d'écriture depuis des composants de domaines différents. Composants online ET batch écrivant simultanément sans verrous documentés. Propriété `contention: true` sur un `Flux` ou un `Store_Donnees`. | `[STORE_TRANSACTIONS]` : écrit par composant online ET batch de nuit sans coordination documentée | **[Propriété]** `contention: boolean` |
| `Communaute_Louvain` | Cluster de nœuds fortement interconnectés identifié automatiquement par l'algorithme de Louvain. Résultat stocké comme propriété `communityId` sur chaque nœud. Proxy automatique pour valider ou challenger les Bounded Contexts candidats. | Valeur entière `communityId` assignée par l'algorithme GDS Neo4j (`gds.louvain`). L'écart entre communautés Louvain et Bounded Contexts DDD signale des incohérences à investiguer. | Communauté `C3 : {COMP_A, COMP_B, STORE_X, STRUCT_Y}` ≈ `BC-Transaction` | **[Propriété]** `communityId: integer` |
| `Noeud_Articulation` | Nœud dont la suppression entraîne une fragmentation du graphe en composantes déconnectées. Équivalent structurel d'un SPOF au sens de la théorie des graphes. | Score betweenness normalisé > 0.5. Résultat positif de `gds.alpha.articulationPoints`. Nœud dont le retrait isole des sous-graphes. | `[ORCHESTRATEUR_NAVIGATION]` : sa suppression isole 8 composants aval | **[Propriété]** `isArticulationPoint: boolean` + `betweennessScore: float` |
| `Score_Criticite` | Métrique composite normalisée [0–100] calculée sur un nœud. Agrège : fan-in, fan-out, couplage inter-domaines, présence sur chemin critique, présence SPOF. Sert à prioriser les analyses et les transformations. | Propriété `criticiteScore: integer [0–100]` sur un nœud. Calculée en Phase 4 (`F1.3`). Score > seuil configuré (ex : 75) → alerte revue architecturale. | `[ORCHESTRATEUR_NAVIGATION]` : `criticiteScore ≈ 87` (fan-out 11, SPOF, point d'articulation) | **[Propriété]** `criticiteScore: integer` |

---

## COUCHE 7 — Modernisation

| Label Neo4j | Définition | Signal d'identification | Exemple illustratif | Type graphe |
|-------------|------------|------------------------|---------------------|-------------|
| `Declencheur` | Signal objectif (technique, réglementaire, stratégique ou organisationnel) justifiant une décision de modernisation. Classifié par niveau d'urgence : **Bloquant**, **Majeur**, **Mineur**. | Identifiant `DEC-[NNN]` dans une étude de déclencheurs. Contrainte technique non contournable, exigence réglementaire, obsolescence éditeur, risque de compétence (départ d'expert unique). Section "Déclencheurs" dans un document ArchiMind. | `DEC-07 : store hiérarchique incompatible avec cibles cloud → Bloquant`, `DEC-04 : données personnelles sans pseudonymisation → Réglementaire Majeur` | **[Nœud]** |
| `Strategie_Transformation` | Classification de la trajectoire de transformation d'un composant selon le framework 7R : Retire, Retain, Rehost, Replatform, Refactor, Re-architect, Replace. Déterminée après analyse des déclencheurs et des contraintes de couplage. | Mention explicite d'un des 7 termes dans un DAT, ADR, fiche de domaine ou roadmap. Propriété `strategie7R` sur un nœud `Composant` ou `Domaine_Fonctionnel`. | `[ORCHESTRATEUR_NAVIGATION]` → `Re-architect` (trop couplé pour Refactor). `[UTIL_VALIDATION_DATE]` → `Retain` (utilitaire stateless sans dette). | **[Nœud]** + `strategie7R: enum` |
| `Decision_Architecture` | Choix formel et tracé sur un point bloquant ou majeur, avec alternatives évaluées, décision retenue et justification documentée. Format ADR (Architecture Decision Record). Immutable : un ADR ne se modifie pas, il est supersedé par un nouveau. | Identifiant `ADR-[NNN]`. Structure Contexte / Alternatives / Décision / Conséquences. Statut : `Proposé | Accepté | Déprécié | Superseded`. | `ADR-003 : Propriétaire du store COMPTES — Account ou Customer ?`, `ADR-007 : Migration store hiérarchique → SGBDR` | **[Nœud]** |
| `Zone_Incertitude` | Information manquante ou hypothèse non confirmée, bloquant ou fragilisant une décision d'architecture. Documentée avec un code unique et un plan de résolution (qui fournit l'information, par quel biais). | Identifiant `INC-[NNN]`. Annotation `fiabilite: MANQUANT` sur un nœud ou une relation. Phrases : "source non identifiée", "à confirmer par exploitation", "inconnu du corpus". Toute entité `SUPPOSÉ` sans plan de résolution. | `INC-007 : producteur du flux journalier `[FLUX_TRANSACTIONS_JOURNEE]` non identifié dans le corpus` | **[Nœud]** |
| `Periode_Double_Run` | Phase de cohabitation temporaire entre le système Legacy et le système cible pendant laquelle les deux traitent en parallèle pour validation. Contrat temporel borné. Requiert une stratégie de réconciliation des divergences. | Mention de "run en parallèle", "cohabitation Legacy/cible", "double run", "réconciliation source/cible" dans un DAT ou un plan de migration. Propriété `dureeMaxMois: integer`. | Double run `[STORE_TRANSACTIONS]` Legacy ↔ Write Model `TransactionComptabilisée` : 3 mois max | **[Nœud]** |

---

## PARTIE B — Types de relations Neo4j

> Chaque relation porte au minimum la propriété `fiabilite: FAIT | HYPOTHÈSE | SUPPOSÉ`.

### B.1 — Relations de la couche fonctionnelle

| Type de relation | Source → Destination | Description | Propriétés clés |
|-----------------|---------------------|-------------|----------------|
| `CONTIENT` | `Domaine_Fonctionnel` → `Processus_Fonctionnel` | Ce domaine fonctionnel contient structurellement ce processus. Le domaine est la frontière macroscopique qui délimite quels processus lui appartiennent. | `fiabilite` |
| `CATALOGUE` | `Domaine_Fonctionnel` → `Fonction` | Ce domaine fonctionnel regroupe cette fonction dans son catalogue logique, indépendamment du moment où elle est exécutée. Une fonction peut être dans le catalogue d'un domaine sans être invoquée par aucun processus connu. | `fiabilite` |
| `ORCHESTRE` | `Processus_Fonctionnel` → `Fonction` | Ce processus fait intervenir cette fonction à cette position dans son enchaînement. Relation **many-to-many** : une même fonction peut être orchestrée par plusieurs processus différents (réutilisabilité). La propriété `ordre` porte la séquence au sein du processus. La propriété `conditionnel` indique si l'appel dépend d'un branchement. | `fiabilite`, `ordre: integer`, `conditionnel: boolean` |
| `ORIENTE_PAR` | `Processus_Fonctionnel` → `Regle_Metier` | Ce processus est orienté par cette règle pour ses conditions de routage (branchements, aiguillages du flux). Rôle : "si dossier incomplet, retourner à l'étape précédente". Distinct de `PORTE_REGLE` qui concerne la logique interne d'une fonction. | `fiabilite`, `typeRoutage: BRANCHEMENT\|BOUCLE\|CONDITION_SORTIE` |
| `PORTE_REGLE` | `Fonction` → `Regle_Metier` | Cette fonction est gouvernée par cette règle pour sa logique interne (calcul exact, critères de validation algorithmique). Rôle : "frais de port = 0 si commande > 50 €". | `fiabilite`, `typePortage: EXPLICITE\|IMPLICITE` |
| `IMPLÉMENTE` | `Composant` → `Fonction` | Ce composant technique implémente cette fonction. Lien de traçabilité entre la couche applicative et la couche fonctionnelle. | `fiabilite` |
| `ENCODE_REGLE` | `Composant` → `Regle_Metier` | Ce composant encode cette règle dans son code source. Lien technique — distinct de `PORTE_REGLE` (fonctionnel) et `ORIENTE_PAR` (processus). | `fiabilite`, `typeEncodage: EXPLICITE\|IMPLICITE` |

### B.2 — Relations des autres couches

| Type de relation | Source → Destination | Description | Propriétés clés |
|-----------------|---------------------|-------------|----------------|
| `APPARTIENT_AU_CONTEXTE` | `Composant`, `Entite_Donnees`, `Aggregate`, `Fonction` → `Bounded_Context` | Appartenance au découpage DDD cible | `fiabilite` |
| `APPELLE` | `Composant` → `Composant` | Appel synchrone inter-composants | `fiabilite`, `typeAppel: STATIQUE\|DYNAMIQUE\|REDIRECT`, `conditionnel: boolean` |
| `INCLUT` | `Composant` → `Structure_Partagee` | Ce composant inclut cette structure partagée | `fiabilite` |
| `ACCEDE_A` | `Composant` → `Store_Donnees`, `Store_Echange`, `Table_Relationnelle`, `Store_Hierarchique`, `Canal_Messagerie` | Accès à un store de données | `fiabilite`, `mode: R\|W\|RW`, `contention: boolean` |
| `DÉCLENCHE` | `Unite_Execution`, `Point_Entree` → `Composant` | Ce point d'entrée ou step déclenche ce composant | `fiabilite` |
| `CONTIENT_STEP` | `Job_Batch` → `Unite_Execution` | Ce job contient ce step/unité d'exécution | `fiabilite`, `ordre: integer` |
| `EXPOSE` | `Bounded_Context` → `Interface` | Ce BC expose cette interface | `fiabilite` |
| `CONSOMME` | `Bounded_Context` → `Interface` | Ce BC consomme cette interface | `fiabilite` |
| `PROTEGE_PAR` | `Bounded_Context` → `Anti_Corruption_Layer` | Ce BC est protégé côté Legacy par cette ACL | `fiabilite` |
| `CORRESPOND_A` | `Entite_Donnees` → `Store_Donnees`, `Table_Relationnelle`, `Store_Hierarchique` | Cette entité est portée physiquement par ce store | `fiabilite` |
| `EST_RACINE_DE` | `Aggregate` → `Entite_Donnees` | Cet Aggregate a cette entité comme racine | `fiabilite` |
| `DECLENCHE_DECISION` | `Declencheur` → `Decision_Architecture` | Ce déclencheur motive cette décision | `fiabilite` |
| `RÉSOUT_INCERTITUDE` | `Decision_Architecture` → `Zone_Incertitude` | Cette décision lève cette incertitude | `fiabilite` |
| `GENERE_INCERTITUDE` | `Flux`, `Composant`, `Store_Donnees` → `Zone_Incertitude` | Cet élément génère cette zone d'incertitude | `fiabilite` |
| `CANDIDATE_STRATEGIE` | `Composant`, `Domaine_Fonctionnel` → `Strategie_Transformation` | Candidat à cette stratégie de transformation | `fiabilite`, `priorite: BLOQUANT\|MAJEUR\|MINEUR` |
| `NÉCESSITE_DOUBLE_RUN` | `Domaine_Fonctionnel`, `Bounded_Context` → `Periode_Double_Run` | Ce périmètre nécessite un double run | `fiabilite`, `dureeMaxMois: integer` |
| `EST_SPOF` | `Composant`, `Store_Donnees`, `Interface` → `SPOF` | Ce composant a été classifié SPOF | `fiabilite`, `identifiant: SPOF-NNN`, `severite: CRITIQUE\|MAJEUR` |
| `APPARTIENT_COMMUNAUTE` | Tout nœud → `Communaute_Louvain` | Résultat de clustering Louvain | `communityId: integer`, `modularity: float` |
| `PRODUIT` | `Composant`, `Bounded_Context` → `Evenement_Domaine` | Ce composant produit cet événement | `fiabilite` |
| `CONSOMME_EVENEMENT` | `Composant`, `Bounded_Context` → `Evenement_Domaine` | Ce composant consomme cet événement | `fiabilite` |

---

## PARTIE C — Propriétés des nœuds

| Propriété | Type | Applicable sur | Description |
|-----------|------|----------------|-------------|
| `id` | string | Tous | Identifiant unique stable dans le graphe (`type:nom`, ex : `comp:NAVMENU`, `bc:Paiement`) |
| `nom` | string | Tous | Nom canonique du composant dans le système source |
| `fiabilite` | enum | Tous | `FAIT \| HYPOTHÈSE \| SUPPOSÉ \| MANQUANT` |
| `source` | string | Tous | Nom du document source (fichier du corpus) |
| `description` | string | Tous | Description synthétique (1–3 phrases) |
| `technologie` | enum | `Composant`, `Store_Donnees`, `Table_Relationnelle`, `Store_Hierarchique` | Stack technologique du composant — valeurs paramétrables par contexte (voir Partie E) |
| `typeExecution` | enum | `Composant` | `ONLINE \| BATCH \| UTILITAIRE \| SERVICE` |
| `criticiteScore` | integer [0–100] | `Composant`, `Store_Donnees`, `Interface` | Score composite de criticité (calculé Phase 4) |
| `isSpof` | boolean | `Composant`, `Store_Donnees` | Classifié SPOF dans le référentiel de risques |
| `isArticulationPoint` | boolean | `Composant` | Point d'articulation du graphe (Phase 4) |
| `betweennessScore` | float | `Composant`, `Store_Donnees` | Score de betweenness centrality normalisé [0–1] |
| `communityId` | integer | Tous | Identifiant de communauté Louvain (Phase 4) |
| `fanIn` | integer | `Composant`, `Structure_Partagee` | Nombre d'arcs entrants |
| `fanOut` | integer | `Composant` | Nombre d'arcs sortants |
| `modeAcces` | enum | `Store_Donnees`, `Table_Relationnelle` | `R \| W \| RW \| RW_CONTENTION` |
| `strategie7R` | enum | `Composant`, `Domaine_Fonctionnel` | `RETIRE \| RETAIN \| REHOST \| REPLATFORM \| REFACTOR \| RE_ARCHITECT \| REPLACE` |
| `niveauUrgence` | enum | `Declencheur`, `Zone_Incertitude` | `BLOQUANT \| MAJEUR \| MINEUR` |
| `statut` | enum | `Decision_Architecture` | `PROPOSÉ \| ACCEPTÉ \| DÉPRÉCIÉ \| SUPERSEDED` |
| `domaineDDD` | enum | `Bounded_Context`, `Domaine_Fonctionnel` | `CORE \| SUPPORTING \| GENERIC` |
| `regpd` | boolean | `Entite_Donnees`, `Table_Relationnelle`, `Store_Donnees` | Contient des données à caractère personnel soumises au RGPD |

---

## PARTIE D — Labels Neo4j (schéma de référence)

```cypher
// ── NŒUDS ──────────────────────────────────────────────────────────────────

// Couche 1 — Fonctionnelle
:Domaine_Fonctionnel
:Fonction
:Regle_Metier
:Processus_Fonctionnel

// Couche 2 — Applicative
:Composant
:Point_Entree
:Interface_Utilisateur
:Job_Batch
:Unite_Execution
:Procedure_Reutilisable
:Domaine_Technique

// Couche 3 — Données
:Store_Donnees
:Store_Echange
:Table_Relationnelle
:Store_Hierarchique
:Structure_Partagee
:Entite_Donnees
:Canal_Messagerie

// Couche 4 — Intégration
:Interface
:Point_Integration
// Note : Flux et Dependance sont des RELATIONS dans le schéma par défaut.
// Les promouvoir en nœuds si la densité du graphe ou les besoins d'annotation l'exigent.

// Couche 5 — DDD
:Bounded_Context
:Aggregate
:Anti_Corruption_Layer
:Evenement_Domaine
:Context_Map

// Couche 6 — Risque & Qualité
:SPOF
:Communaute_Louvain
// Zone_Contention et Noeud_Articulation sont des propriétés (boolean) sur les nœuds existants.

// Couche 7 — Modernisation
:Declencheur
:Strategie_Transformation
:Decision_Architecture
:Zone_Incertitude
:Periode_Double_Run

// ── RELATIONS ──────────────────────────────────────────────────────────────
// (voir Partie B pour la liste complète)
// Propriété obligatoire sur toute relation : fiabilite: FAIT|HYPOTHÈSE|SUPPOSÉ

// ── PROPRIÉTÉ MÉTA-FIABILITÉ ───────────────────────────────────────────────
// Valeurs de la propriété `fiabilite` :
//   FAIT | HYPOTHÈSE | SUPPOSÉ | MANQUANT
```

---

## PARTIE E — Guide de paramétrage par contexte technologique

> Cette section permet d'adapter le vocabulaire des marqueurs d'identification (Couches 2 et 3) à la stack technologique du système source. Le schéma Neo4j (labels, relations, propriétés) **reste identique** — seul le mapping "marqueur → label" change.

### E.1 — Tableau de correspondance des concepts par technologie

| Concept générique | COBOL / z/OS | PACBASE / VisualAge | AS/400 / IBM i RPG | NATURAL / ADABAS | ABAP / SAP |
|-------------------|-------------|---------------------|--------------------|-----------------|-----------|
| **Composant** | Programme `.cbl` — `IDENTIFICATION DIVISION` | Programme Pacbase (`-P` lines) | Programme RPG `.rpg` / `.pgm` | Programme NATURAL | Programme ABAP — `PROGRAM-ID` |
| **Point_Entree** | CICS TranID 4 car. (`DEFINE TRANSACTION` CSD) | Écran Pacbase / Menu | Option de menu AS/400, Commande `CALL` | Map NATURAL / menu | T-code SAP (`SE93`) |
| **Interface_Utilisateur** | Mapset BMS `.bms` — `DFHMDI/DFHMDF` | Écran Pacbase (définition mapset) | Display file DDS `.dspf` — `DFTVAL` | Map NATURAL — `INPUT` / `OUTPUT` | Dynpro SAP / WebDynpro |
| **Job_Batch** | JCL `.jcl` — carte `//JOB` | Batch Pacbase / JCL généré | Batch job AS/400 — `SBMJOB` | Batch NATURAL — `STACK TOP COMMAND` | Job SAP (SM36) |
| **Unite_Execution** | Step JCL — `EXEC PGM=` | Step JCL / Step Pacbase | Step batch — programme appelé dans `CL` | Step NATURAL | Étape de job ABAP |
| **Structure_Partagee** | Copybook `.cpy` — `COPY` | Segment / Rubrique Pacbase — `COPY` | Data structure RPG — `/COPY` | Local data area — `DEFINE DATA LOCAL` | Include ABAP — `INCLUDE` |
| **Store_Donnees** | VSAM KSDS/ESDS/AIX — `DEFINE CLUSTER` | ADABAS file / VSAM | Physical file AS/400 — `CRTPF` | ADABAS file — `READ ISN` | Table SAP (SE11) / HANA table |
| **Store_Echange** | Dataset PS/GDG séquentiel | PS séquentiel / VSAM séquentiel | Source file AS/400 — `CPYSRCF` | Work file NATURAL | Dataset SAP / fichier ASCII |
| **Table_Relationnelle** | Db2 z/OS — `EXEC SQL` + DDL | Db2 z/OS (si hybride) | DB2 for i — `EXEC SQL` | Adabas SQL (si exposé) | Table SAP HANA — `SELECT` ABAP |
| **Store_Hierarchique** | IMS DL/I — `EXEC DLI GU/GNP/REPL` | VSAM / IMS (si hybride) | Non standard (rare sur AS/400) | ADABAS avec réseau logique | Non standard (rare SAP) |
| **Canal_Messagerie** | IBM MQ — `MQPUT` / `MQGET` + CSD | IBM MQ (si hybride) | MQ / Data queue AS/400 — `DTAQ` | Non standard (middleware externe) | qRFC / tRFC / ALE IDoc SAP |
| **Flux** | `CALL`, `EXEC CICS XCTL/LINK`, `OPEN/READ/WRITE`, `EXEC SQL`, `EXEC DLI` | Appels inter-programmes Pacbase, `LINK` | `CALL`, `CALLP`, `CHAIN/READ/READE` | `PERFORM`, `FETCH`, `READ ISN` | `CALL`, `SUBMIT`, `SELECT` ABAP |
| **Dependance (INCLUSION)** | `COPY nomcopybook` | `COPY rubrique` | `/COPY nomlib,membre` | `DEFINE DATA ... LOCAL USING` | `INCLUDE ZNomInclude` |

### E.2 — Propriété `technologie` — valeurs paramétrables

La propriété `technologie` sur les nœuds `Composant`, `Store_Donnees`, etc. doit être configurée avec les valeurs du stack cible. Exemples de valeurs :

```
// Stack mainframe IBM (z/OS)
COBOL_BATCH | COBOL_CICS | COBOL_PACBASE | JCL | REXX | HLASM | PL1
VSAM_KSDS | VSAM_ESDS | VSAM_AIX | DB2_ZOS | IMS_DLI | IBM_MQ | BMS

// Stack AS/400 / IBM i
RPG_FREE | RPG_FIXED | CL_PROGRAM | DDS_PHYSICAL | DDS_LOGICAL | DB2_400 | DTAQ

// Stack NATURAL / ADABAS
NATURAL_ONLINE | NATURAL_BATCH | ADABAS_FILE | ADABAS_DDM | PREDICT

// Stack ABAP / SAP
ABAP_REPORT | ABAP_FUNCTION | ABAP_CLASS | DYNPRO | SAP_TABLE | IDOC | BAPI

// Stack client-serveur / VB / PowerBuilder
VB6_FORM | VB6_MODULE | POWERBUILDER_DATAWINDOW | ORACLE_FORM | ORACLE_PROCEDURE
```

### E.3 — Paramètres de configuration `extract.py` par contexte

À renseigner dans la configuration du pipeline avant extraction :

```json
{
  "contexte": {
    "nom_systeme": "[NOM_DU_SYSTÈME]",
    "stack_primaire": "[COBOL_ZOS | NATURAL_ADABAS | RPG_AS400 | ABAP_SAP | ...]",
    "stacks_secondaires": ["[DB2_ZOS]", "[IBM_MQ]"],
    "langue_documentation": "[FR | EN]",
    "prefixe_ids": {
      "domaine_fonctionnel": "D",
      "fonction": "F",
      "regle_metier": "RG",
      "spof": "SPOF",
      "zone_incertitude": "INC",
      "decision_architecture": "ADR"
    },
    "seuils_analyse": {
      "fanin_alerte": 5,
      "fanout_alerte": 7,
      "criticite_alerte": 75,
      "betweenness_alerte": 0.5
    }
  }
}
```

---

## PARTIE F — Notes d'implémentation pour `extract.py`

### F.1 — Fragment de system prompt (injectable dans GPT-4o / Claude)

```
Tu es un extracteur d'entités pour un graphe de connaissances (GraphRAG Neo4j) 
dédié à l'analyse d'un système legacy en vue de sa modernisation.

Pour chaque document du corpus, tu dois extraire des entités JSON selon le 
schéma ci-dessous et les relations entre elles.

LABELS DE NŒUDS RECONNUS :
// Couche fonctionnelle
Domaine_Fonctionnel, Fonction, Regle_Metier, Processus_Fonctionnel,
// Couche applicative
Composant, Point_Entree, Interface_Utilisateur, Job_Batch, Unite_Execution,
Procedure_Reutilisable, Domaine_Technique,
// Couche données
Store_Donnees, Store_Echange, Table_Relationnelle, Store_Hierarchique,
Structure_Partagee, Entite_Donnees, Canal_Messagerie,
// Couche intégration & DDD
Interface, Point_Integration, Bounded_Context, Aggregate,
Anti_Corruption_Layer, Evenement_Domaine,
// Couche risque & modernisation
SPOF, Declencheur, Strategie_Transformation, Decision_Architecture, Zone_Incertitude

TYPES DE RELATIONS RECONNUS :
// Couche fonctionnelle — hiérarchie et gouvernance
CONTIENT (Domaine_Fonctionnel→Processus_Fonctionnel),
CATALOGUE (Domaine_Fonctionnel→Fonction),
ORCHESTRE (Processus_Fonctionnel→Fonction),        // many-to-many, propriété ordre:int
ORIENTE_PAR (Processus_Fonctionnel→Regle_Metier),  // routage/branchements du flux
PORTE_REGLE (Fonction→Regle_Metier),               // logique interne de la fonction
IMPLÉMENTE (Composant→Fonction),
ENCODE_REGLE (Composant→Regle_Metier),
// Autres couches
APPARTIENT_AU_CONTEXTE, APPELLE, INCLUT, ACCEDE_A, DÉCLENCHE, CONTIENT_STEP,
EXPOSE, CONSOMME, PROTEGE_PAR, CORRESPOND_A, EST_RACINE_DE,
DECLENCHE_DECISION, RÉSOUT_INCERTITUDE, GENERE_INCERTITUDE,
CANDIDATE_STRATEGIE, EST_SPOF, PRODUIT, CONSOMME_EVENEMENT

RÈGLE DE FIABILITÉ (obligatoire sur tout nœud et toute relation) :
- FAIT : information directement observable dans le texte source (instruction 
  de code, définition DDL, section de documentation formelle).
- HYPOTHÈSE : information déduite par raisonnement logique à partir de faits.
- SUPPOSÉ : inférence sans source fiable. Génère automatiquement une 
  Zone_Incertitude associée.
- MANQUANT : référence à un élément absent du corpus. Génère une 
  Zone_Incertitude avec mention du document ou de la source attendue.

RÈGLES D'EXTRACTION :
1. Ne jamais inventer un nom de composant, de store ou de fonction non cité 
   dans le document.
2. MODÈLE FONCTIONNEL — mémoriser impérativement :
   - Domaine_Fonctionnel CONTIENT Processus_Fonctionnel (structurellement).
   - Domaine_Fonctionnel CATALOGUE Fonction (logiquement, indépendamment des processus).
   - Processus_Fonctionnel ORCHESTRE Fonction (many-to-many, avec `ordre`).
   - Processus_Fonctionnel est ORIENTE_PAR Regle_Metier (pour ses branchements).
   - Fonction PORTE_REGLE Regle_Metier (pour sa logique interne).
   - Composant IMPLÉMENTE Fonction et peut ENCODE_REGLE une Regle_Metier.
3. RÉUTILISABILITÉ des Fonction : une même Fonction peut apparaître dans 
   plusieurs Processus_Fonctionnel différents. Créer autant de relations 
   ORCHESTRE que nécessaire — ne pas dédupliquer les fonctions.
4. Processus_Fonctionnel vs Fonction :
   - Processus = workflow déclenché par un événement ("Passer une commande", 
     "Traiter un virement", "Clôturer le mois"). Contient un ordre d'étapes.
   - Fonction = action élémentaire précise ("Calculer les frais de port", 
     "Valider le paiement", "Générer le relevé"). Pas d'ordre interne.
5. Regle_Metier — double rôle à distinguer :
   - PORTE_REGLE : la règle dicte le calcul ou la validation interne de la 
     fonction ("frais de port = 0 si commande > 50 €").
   - ORIENTE_PAR : la règle dicte un branchement dans le processus 
     ("si dossier incomplet → retour étape validation").
6. Une Structure_Partagee ne contient jamais de logique exécutable.
7. Store_Echange = transitoire, sans accès direct par clé.
   Store_Donnees = accès direct par clé (indexé).
8. Tout nœud fiabilite:MANQUANT ou fiabilite:SUPPOSÉ doit générer une 
   Zone_Incertitude avec propriété `description` expliquant ce qui manque.
9. Ne pas créer de nœuds Unite_Execution pour les steps de compilation — 
   uniquement pour les steps qui exécutent de la logique métier.

FORMAT DE SORTIE (JSON strict) :
{
  "nodes": [
    {
      "id": "comp:[NOM]",
      "label": "Composant",
      "properties": {
        "nom": "[NOM]",
        "fiabilite": "FAIT|HYPOTHÈSE|SUPPOSÉ|MANQUANT",
        "source": "[nom_fichier_source]",
        "technologie": "[COBOL_BATCH|...]",
        "typeExecution": "ONLINE|BATCH|UTILITAIRE|SERVICE",
        "description": "[description courte]"
      }
    },
    {
      "id": "fn:[IDENTIFIANT]",
      "label": "Fonction",
      "properties": {
        "nom": "[verbe + objet — ex: Calculer les frais de port]",
        "fiabilite": "FAIT|HYPOTHÈSE|SUPPOSÉ",
        "source": "[nom_fichier_source]",
        "description": "[description courte]"
      }
    },
    {
      "id": "proc:[IDENTIFIANT]",
      "label": "Processus_Fonctionnel",
      "properties": {
        "nom": "[libellé — ex: Passer une commande en ligne]",
        "declencheur": "[événement déclencheur — ex: clic Acheter]",
        "fiabilite": "FAIT|HYPOTHÈSE|SUPPOSÉ",
        "source": "[nom_fichier_source]"
      }
    }
  ],
  "relations": [
    {
      "from": "dom:[DOMAINE]",
      "to": "proc:[PROCESSUS]",
      "type": "CONTIENT",
      "properties": { "fiabilite": "FAIT" }
    },
    {
      "from": "dom:[DOMAINE]",
      "to": "fn:[FONCTION]",
      "type": "CATALOGUE",
      "properties": { "fiabilite": "FAIT" }
    },
    {
      "from": "proc:[PROCESSUS]",
      "to": "fn:[FONCTION]",
      "type": "ORCHESTRE",
      "properties": { "fiabilite": "FAIT", "ordre": 1, "conditionnel": false }
    },
    {
      "from": "proc:[PROCESSUS]",
      "to": "rg:[REGLE]",
      "type": "ORIENTE_PAR",
      "properties": { "fiabilite": "FAIT", "typeRoutage": "BRANCHEMENT" }
    },
    {
      "from": "fn:[FONCTION]",
      "to": "rg:[REGLE]",
      "type": "PORTE_REGLE",
      "properties": { "fiabilite": "FAIT", "typePortage": "EXPLICITE" }
    },
    {
      "from": "comp:[COMPOSANT]",
      "to": "fn:[FONCTION]",
      "type": "IMPLÉMENTE",
      "properties": { "fiabilite": "FAIT" }
    },
    {
      "from": "comp:[NOM_SOURCE]",
      "to": "store:[NOM_CIBLE]",
      "type": "ACCEDE_A",
      "properties": { "fiabilite": "FAIT", "mode": "R|W|RW", "contention": false }
    }
  ]
}
```

### F.2 — Règles de déduplication et idempotence (Phase 3 — import Neo4j)

- L'import en Phase 3 utilise `MERGE` sur la propriété `id` → les extractions multi-documents se combinent sans doublon.
- Les relations sont mergées sur le triplet `(from, type, to)` — deux documents citant le même flux enrichissent les propriétés plutôt que de créer deux arcs.
- En cas de conflit de `fiabilite` sur un même nœud entre deux documents, la règle de priorité est : `FAIT` > `HYPOTHÈSE` > `SUPPOSÉ` > `MANQUANT`.

### F.3 — Flux vs Dépendance — décision de modélisation

> ADR à trancher avant le premier import :

**Option A — Relations Neo4j (recommandée si < 5 000 flux)**
- `APPELLE`, `ACCEDE_A`, `INCLUT` sont des arcs du graphe.
- Avantage : performances GDS optimales (betweenness, Louvain).
- Inconvénient : impossible d'annoter individuellement un flux sans promouvoir en nœud.

**Option B — Nœuds `Flux` et `Dependance` (recommandée si annotation riche nécessaire)**
- Chaque flux devient un nœud avec ses propres propriétés (`fiabilite`, `mode`, `contention`, `volumetrie`).
- Avantage : filtrage et annotation granulaire (ex : "tous les flux SUPPOSÉ à valider").
- Inconvénient : graphe plus dense, requêtes GDS plus lentes.

---

## ANNEXE — Fiche d'instanciation par engagement

> Copier-coller cette fiche et remplir pour chaque nouveau contexte avant de lancer le pipeline.

```markdown
## Fiche d'instanciation — [NOM_DU_SYSTÈME]

**Date** :
**Responsable** :
**Stack primaire** : [COBOL_ZOS | RPG_AS400 | NATURAL_ADABAS | ABAP_SAP | ...]
**Stacks secondaires** : [...]
**Langue du corpus** : [FR | EN]

### Correspondances labels (Couche 2 — Applicative)
- Composant = [extension de fichier + instruction de déclaration]
- Point_Entree = [identifiant dans quel catalogue / runtime]
- Interface_Utilisateur = [technologie écran]
- Job_Batch = [extension/format + scheduler utilisé]
- Structure_Partagee = [instruction d'inclusion + extension]

### Correspondances labels (Couche 3 — Données)
- Store_Donnees = [technologie + format]
- Store_Echange = [extension/format des fichiers d'échange]
- Table_Relationnelle = [SGBDR utilisé]
- Store_Hierarchique = [technologie ou N/A]
- Canal_Messagerie = [middleware ou N/A]

### Valeurs de la propriété `technologie`
[liste des valeurs valides pour ce contexte]

### Préfixes d'identifiants
- Domaine_Fonctionnel : [D | DOM | ...]
- Fonction : [F | MF | PM | ...]
- Regle_Metier : [RG | BR | ...]
- Zone_Incertitude : [INC | UNK | ...]
- Decision_Architecture : [ADR | DEC | ...]

### Seuils d'alerte (Phase 4)
- fan-in alerte : [5]
- fan-out alerte : [7]
- criticiteScore alerte : [75]
- betweenness alerte : [0.5]

### Corpus disponible
| Fichier | Type | Contenu |
|---------|------|---------|
| | | |

### Zones d'incertitude initiales connues
| INC-NNN | Description | Détenteur de l'information |
|---------|-------------|---------------------------|
| | | |
```
