import json
import logging
import os
import re
import threading
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Literal

import httpx
from azure.search.documents import SearchClient
from fastapi import APIRouter, BackgroundTasks, HTTPException, Request
from openai import AzureOpenAI
from azure.identity import get_bearer_token_provider
from pydantic import BaseModel

from api.coverage import compute_coverage

router = APIRouter()
logger = logging.getLogger(__name__)

INDEX_NAME = "notebooklm-chunks"
_ADGM_BASE = os.environ.get(
    "ADGM_GRAPH_API_URL",
    "https://modernagent-adgm-dev.azurewebsites.net/api/graph",
).rstrip("/")

_jobs: dict[str, dict] = {}


class ExtractStatus(BaseModel):
    job_id: str
    status: Literal["pending", "running", "done", "error"]
    message: str = ""
    docs_total: int = 0
    docs_processed: int = 0
    entities_imported: dict = {}
    import_errors: int = 0
    coverage: dict = {}


# Fiche d'instanciation (taxonomie Partie E.3) — paramétrable par variable d'environnement
# pour permettre de réutiliser ce pipeline d'extraction sur des corpus documentaires
# différents (CardDemo par défaut). EXTRACT_SYSTEM_NAME doit être un identifiant stable
# sans espace/accent (utilisé tel quel dans l'id "sys:<EXTRACT_SYSTEM_NAME>").
_SYS_NAME = os.environ.get("EXTRACT_SYSTEM_NAME", "CardDemo")
_SYS_STACK_PRIMARY = os.environ.get("EXTRACT_STACK_PRIMARY", "COBOL_ZOS")
_SYS_STACK_SECONDARY = os.environ.get("EXTRACT_STACK_SECONDARY", "DB2_ZOS, IMS_DLI, IBM_MQ, BMS")
_SYS_DOC_LANG = os.environ.get("EXTRACT_DOC_LANGUAGE", "FR")

# ── Blocs partagés entre tous les prompts du pipeline (inventaire / enrichissement / complétion) ──

_COMMON_CONTEXT = """Tu es un extracteur d'entités pour un graphe de connaissances (GraphRAG Neo4j) dédié à
l'analyse du système legacy __SYS_NAME__ en vue de sa modernisation.

CONTEXTE D'ENGAGEMENT (fiche d'instanciation) :
- nom_systeme : __SYS_NAME__ (nœud System unique, id "sys:__SYS_NAME__")
- stack_primaire : __STACK_PRIMARY__
- stacks_secondaires : __STACK_SECONDARY__
- langue_documentation : __DOC_LANG__
"""

_ALL_LABELS_BLOCK = """LABELS DE NŒUDS RECONNUS DANS LE GRAPHE (id = "<préfixe>:<nom>") :
- System (sys:) — id fixe "sys:__SYS_NAME__", racine unique du graphe
- Domaine_Fonctionnel (df:) — ex "df:DF-01" ou "df:referentiel-article"
- Fonction (mf:) — ex "mf:MF-07" ou "mf:authentifier-l-utilisateur" (granularité = macro-fonction)
- Regle_Metier (rg:) — ex "rg:regle-plafond-retrait" (slug par défaut) ; "rg:RG-03" UNIQUEMENT si
  le texte source porte LITTÉRALEMENT ce code (ex "**RG-03** : ...")
- Processus_Fonctionnel (pm:) — ex "pm:PM-02" ou "pm:cloture-mensuelle"

RÈGLE D'ID POUR df:/mf:/rg:/pm: (priorité à 2 niveaux, à appliquer dans cet ordre) :
1. Si le corpus associe à cette entité un code/identifiant existant — quel que soit son format
   (ex "DF-01", "BC4", "MF-007", "PROC-12") — réutilise-le TEL QU'ÉCRIT comme suffixe d'id
   (ex "df:BC4", "rg:RG-015"). CE CODE LITTÉRAL PRIME TOUJOURS, même si le registre fourni
   contient déjà d'autres entités du même label avec un code de même format (ex registre
   contenant déjà rg:RG-01..rg:RG-16) : N'INVENTE JAMAIS un nouveau code en poursuivant cette
   numérotation (ex ne PAS produire "rg:RG-17" pour une entité dont le texte dit explicitement
   "RG-03") — utilise le code EXACTEMENT comme il apparaît dans CE fragment, quitte à créer un
   doublon apparent avec une autre entité au registre (ce sera fusionné par id).
2. Sinon, génère un slug déterministe à partir du NOM CANONIQUE de l'entité : minuscules,
   accents/diacritiques retirés, tout caractère non alphanumérique remplacé par "-", tirets
   multiples fusionnés, pas de tiret en début/fin. Ex : "Référentiel Article" -> "df:referentiel-article",
   "Authentifier l'utilisateur" -> "mf:authentifier-l-utilisateur".
   INTERDICTION ABSOLUE : n'utilise JAMAIS un format "XX-NN" (ex "RG-17", "MF-23") comme
   numérotation séquentielle de ton invention (ex "ceci est la 17e Regle_Metier du registre donc
   RG-17") — ce format n'est légitime QUE comme code LITTÉRAL recopié du texte (règle 1). Pour
   toute entité sans code explicite dans le texte, utilise TOUJOURS le slug du nom (règle 2),
   même si d'autres entités du même label ont, elles, un code "XX-NN" explicite.
   CRITIQUE : ce slug DOIT être déterministe — la MÊME entité citée dans des chunks ou documents
   différents doit produire EXACTEMENT le MÊME id, condition nécessaire à sa fusion correcte dans
   Neo4j (MERGE par id). Si plusieurs libellés désignent la même entité, choisis le plus
   stable/court et garde-le pour toutes ses occurrences.
- Composant (comp:) — ex "comp:COSGN00C" — nom EXACT du programme/module (ex COSGN00C, ACTRANET)
- Point_Entree (pe:) — ex "pe:CM00" — TranID CICS ou identifiant de déclenchement
- Interface_Utilisateur (ui:) — ex "ui:COSGN00" — mapset BMS
- Job_Batch (job:) — ex "job:JOB_CLOTURE_NUIT" — nom du job JCL
- Unite_Execution (step:) — step JCL exécutant de la LOGIQUE MÉTIER uniquement (jamais compilation/link)
- Procedure_Reutilisable (proc:) — procédure cataloguée invoquée par plusieurs jobs
- Structure_Partagee (struct:) — ex "struct:COCOM01Y" — copybook partagé (COMMAREA, etc.)
- Store_Donnees (store:) — fichier VSAM avec accès direct par clé
- Store_Echange (exch:) — fichier séquentiel/PS/GDG, sans accès par clé, transitoire
- Table_Relationnelle (tbl:) — table Db2 z/OS
- Store_Hierarchique (hier:) — segment IMS DL/I
- Entite_Donnees (ent:) — objet métier (ex "ent:Compte", "ent:Client", "ent:Carte", "ent:Transaction")
- Canal_Messagerie (mq:) — queue/topic IBM MQ
- Zone_Incertitude (inc:) — ex "inc:INC-001" — généré selon la règle de fiabilité ci-dessous"""

_FIABILITE_BLOCK = """RÈGLE DE FIABILITÉ (obligatoire sur TOUT nœud et TOUTE relation) :
- FAIT : observable directement dans le texte (instruction de code, DDL/JCL/BMS, doc formelle, ligne de matrice CRUD)
- HYPOTHÈSE : déduite par raisonnement logique à partir de faits ("N composants l'appellent -> probablement un hub")
- SUPPOSÉ : inférence sans source fiable ("probablement", "devrait", "on suppose que") -> génère une Zone_Incertitude
- MANQUANT : référence à un élément absent du corpus -> génère une Zone_Incertitude citant le document/la source attendue
RÈGLE ABSOLUE : sans source identifiable dans le corpus, jamais fiabilite=FAIT.
Tout élément fiabilite=MANQUANT ou SUPPOSÉ DOIT générer un nœud Zone_Incertitude (id "inc:INC-NNN",
propriété description) relié par GENERE_INCERTITUDE depuis l'élément concerné."""

_COMMON_PROPERTIES_BLOCK = """PROPRIÉTÉS COMMUNES À TOUS LES NŒUDS :
- nom (string, obligatoire) : nom canonique
- fiabilite (enum, obligatoire) : FAIT | HYPOTHÈSE | SUPPOSÉ | MANQUANT (voir règle de fiabilité)
- source (string, obligatoire) : nom du fichier document source
- description (string, optionnel) : 1-3 phrases

NE JAMAIS inclure de propriétés calculées côté serveur : criticiteScore, isSpof, betweennessScore,
communityId, fanIn, fanOut, isArticulationPoint, strategie7R, candidate7R."""

_REGISTRE_INSTRUCTIONS = """REGISTRE D'ENTITÉS DÉJÀ INVENTORIÉES :
Le message utilisateur fournit un registre JSON `{"entities": [{"id","label","nom"}, ...]}`
représentant les entités déjà identifiées dans CE document (tous chunks confondus, étape
"inventaire"). Réutilise ces ids EXACTEMENT (ne les renomme pas, n'en recrée pas de variantes)
pour tout nœud que tu enrichis ou toute relation qui les référence. Tu peux référencer des ids
du registre appartenant à d'autres couches (ex un Composant pour une relation IMPLEMENTE), mais
tu ne dois produire un nœud complet (objet "nodes") QUE pour les entités de TA couche."""


# ── Étape 1 — Inventaire (par chunk, sortie minimale, exhaustivité maximale) ──────────────────

_INVENTAIRE_SYSTEM_TEMPLATE = _COMMON_CONTEXT + """
Pour le fragment de document fourni, ta SEULE tâche est de répertorier de manière EXHAUSTIVE
toutes les entités identifiables, SANS détailler leurs propriétés ni leurs relations.

""" + _ALL_LABELS_BLOCK + """

CONSIGNES :
1. Répertorie TOUTE entité mentionnée dans ce fragment, même brièvement (un programme cité une
   seule fois en passant compte autant qu'un programme détaillé sur 10 lignes). Pour les entités
   df:/mf:/rg:/pm:, applique la règle d'id à 2 niveaux ci-dessus : réutilise un code/identifiant
   existant du corpus tel qu'écrit s'il y en a (quel que soit son format) ; sinon génère un slug
   déterministe à partir du nom canonique (minuscules, sans accents, non-alphanumériques -> "-").
   Le slug doit être STABLE : la même entité doit toujours produire le même id, y compris si elle
   est mentionnée dans plusieurs chunks ou documents (condition de fusion Neo4j).
2. N'invente JAMAIS un nom non présent dans le texte.
3. Ne PAS agréger les fonctions : chaque opération/traitement élémentaire identifiable est une
   Fonction distincte ("Consulter solde" et "Modifier plafond" = 2 Fonction). Ne PAS confondre
   Fonction (le "quoi", une opération) avec Processus_Fonctionnel (le "comment"/"quand", un
   enchaînement ordonné de plusieurs Fonction déclenché par un événement).
4. Indique pour chaque entité la/les "couches" d'enrichissement pertinentes parmi :
   - "fonctionnel" : Domaine_Fonctionnel, Fonction, Regle_Metier, Processus_Fonctionnel
   - "applicatif" : Composant, Point_Entree, Interface_Utilisateur, Job_Batch, Unite_Execution,
     Procedure_Reutilisable
   - "donnees" : Store_Donnees, Store_Echange, Table_Relationnelle, Store_Hierarchique,
     Structure_Partagee, Entite_Donnees, Canal_Messagerie
   La couche d'une entité se déduit directement de son label (table ci-dessus) — indique dans
   "couches" l'ensemble (dédupliqué) des couches couvertes par les entités de CE fragment.
5. Ne produis NI propriétés détaillées, NI relations, NI fiabilité, NI Zone_Incertitude —
   uniquement id/label/nom. Le registre fourni en entrée (entités des chunks précédents de ce
   même document) ne doit PAS être répété dans ta sortie : ne liste que les entités NOUVELLES
   trouvées dans ce fragment (nouvel id non présent dans le registre).

FORMAT DE SORTIE (JSON strict, clés EXACTES "entities"/"couches") :
{
  "entities": [
    {"id": "df:DF-01", "label": "Domaine_Fonctionnel", "nom": "Gestion des comptes"},
    {"id": "mf:MF-07", "label": "Fonction", "nom": "Authentifier l'utilisateur"},
    {"id": "comp:COSGN00C", "label": "Composant", "nom": "COSGN00C"}
  ],
  "couches": ["fonctionnel", "applicatif"]
}"""


# ── Étape 2 — Enrichissement (par chunk × couche, parallélisable) ────────────────────────────

_ENRICH_OUTPUT_FORMAT = """FORMAT DE SORTIE (JSON strict, clés EXACTES "nodes"/"relations", tableaux vides si rien à
produire pour cette couche dans ce fragment) :
{
  "nodes": [
    {"id": "<id du registre>", "label": "<Label>",
     "properties": {"nom": "...", "fiabilite": "FAIT", "source": "...", "description": "..."}}
  ],
  "relations": [
    {"from": "<id>", "to": "<id>", "type": "<TYPE>", "properties": {"fiabilite": "FAIT", ...}}
  ]
}"""

_ENRICH_FONCTIONNEL_DOMAINES_TEMPLATE = _COMMON_CONTEXT + """
Étape "enrichissement", couche FONCTIONNELLE — DOMAINES & PROCESSUS. Pour les entités
Domaine_Fonctionnel et Processus_Fonctionnel (et System) présentes dans le registre, produis
leurs propriétés complètes et les relations structurelles ci-dessous. NE PRODUIS AUCUN nœud
Fonction ni Regle_Metier : ils sont traités dans une étape séparée (catalogue).

DÉFINITIONS CLÉS (distinctions centrales, à appliquer rigoureusement) :
- Domaine_Fonctionnel : grand ensemble cohérent de l'activité métier (un périmètre, ex "Gestion
  des comptes"). C'est le SEUL label de regroupement de niveau "domaine"/"bounded context" :
  tout domaine identifié dans le document — y compris ceux qualifiés de "générique",
  "technique", "transverse" ou "support" (ex un domaine de reporting, d'interfaces ou
  d'exploitation) — est un Domaine_Fonctionnel, sans distinction de label selon sa nature.
  CONTIENT structurellement les Processus_Fonctionnel qui lui appartiennent.
- Processus_Fonctionnel : enchaînement ordonné de Fonction, déclenché par un événement
  identifiable, produisant un résultat de valeur — le "comment"/"quand". Ex : "Clôture
  mensuelle" = processus ; "Calcul des intérêts" seul = Fonction. Ne crée PAS de
  Processus_Fonctionnel pour une action simple, même complexe.

""" + _COMMON_PROPERTIES_BLOCK + """

TYPES DE RELATIONS DE CETTE ÉTAPE (from → to : propriétés) :
- CONTIENT : Domaine_Fonctionnel→Processus_Fonctionnel | System→Domaine_Fonctionnel  → {fiabilite}
- DEPEND_DE : Domaine_Fonctionnel→Domaine_Fonctionnel | Processus_Fonctionnel→Processus_Fonctionnel
  → {fiabilite, nature: DONNEES|ORDONNANCEMENT|APPEL|DECLENCHEMENT|GOUVERNANCE, description (optionnel)}
  - entre deux Domaine_Fonctionnel : DONNEES (flux de données entre les deux domaines),
    ORDONNANCEMENT (un domaine conditionne l'exécution de l'autre) ou GOUVERNANCE (un domaine
    gouverne/pilote l'autre, sans flux de données)
  - entre deux Processus_Fonctionnel : DECLENCHEMENT (un processus déclenche un autre processus)

""" + _FIABILITE_BLOCK + """

RÈGLES :
1. N'invente JAMAIS un nom de domaine/processus non cité dans le document.
2. EXHAUSTIVITÉ : produis un nœud complet pour CHAQUE Domaine_Fonctionnel et CHAQUE
   Processus_Fonctionnel du registre mentionné (même brièvement) dans ce fragment — ne te limite
   PAS à un sous-ensemble même si le registre en contient beaucoup.
3. Le nœud System (sys:__SYS_NAME__) ne doit être émis que si le document permet de le relier à
   un Domaine_Fonctionnel via CONTIENT (il sera fusionné par id entre documents/chunks).
4. Ne produis un nœud complet QUE pour les ids du registre portant un label
   Domaine_Fonctionnel, Processus_Fonctionnel ou System.
5. N'établis une relation DEPEND_DE QUE si la dépendance entre les deux entités de MÊME label est
   explicitement déductible du document — n'invente JAMAIS ce type de lien.

""" + _REGISTRE_INSTRUCTIONS + """

""" + _ENRICH_OUTPUT_FORMAT


_CATALOGUE_DEFINITIONS = """DÉFINITIONS CLÉS :
- Fonction : action élémentaire et réutilisable ("Calculer la TVA", "Valider un paiement") — le
  "quoi", à la granularité d'une opération précise. Une même Fonction peut être ORCHESTRE par
  plusieurs Processus_Fonctionnel : crée une relation ORCHESTRE distincte par processus, ne
  jamais dédupliquer/fusionner.
- Regle_Metier : contrainte/calcul/directive métier, double rôle selon le contexte —
  (1) logique interne d'une Fonction (calcul, critère de validation) → relation
  Fonction PORTE_REGLE Regle_Metier ; (2) condition de branchement/routage d'un
  Processus_Fonctionnel (ex "si dossier incomplet → retour à l'étape précédente") → relation
  Processus_Fonctionnel ORIENTE_PAR Regle_Metier (avec typeRoutage). Une même règle peut porter
  les deux rôles à la fois (deux relations distinctes)."""

_CATALOGUE_RELATION_TYPES = """TYPES DE RELATIONS DE CETTE ÉTAPE (from → to : propriétés) :
- CATALOGUE : Domaine_Fonctionnel→Fonction  → {fiabilite}
  (rattachement logique au catalogue du domaine, indépendant de l'exécution — crée cette relation
  dès qu'une Fonction est présentée comme appartenant à un domaine, y compris implicitement via
  un regroupement/titre/tableau/diagramme — ex un nœud de diagramme imbriqué dans le groupe d'un
  domaine appartient au catalogue de ce domaine)
- PORTE_REGLE : Fonction→Regle_Metier  → {fiabilite, typePortage: EXPLICITE|IMPLICITE}
- ORCHESTRE : Processus_Fonctionnel→Fonction  → {fiabilite, ordre: integer, conditionnel: boolean}
- ORIENTE_PAR : Processus_Fonctionnel→Regle_Metier  → {fiabilite, typeRoutage: BRANCHEMENT|BOUCLE|CONDITION_SORTIE}
- DEPEND_DE : Fonction→Fonction  → {fiabilite, nature: APPEL, description (optionnel)}
  (une fonction appelle/invoque une autre fonction)"""


# Sous-étape "catalogue" scindée en appels nœuds seuls / relations seules : un appel unique
# alterne entre "tous les nœuds, 0 relation" et "0 nœud, toutes les relations" selon les runs
# (cf. diagnostic) — jamais les deux exhaustivement à la fois. Les nœuds sont en outre scindés par
# label (Fonction / Regle_Metier) : un registre combinant ~150 Fonction + ~60 Regle_Metier pour un
# même document fait que le modèle privilégie les Fonction et sous-produit les Regle_Metier
# (cf. diagnostic RG-01..06 absentes malgré présence au registre).
_ENRICH_FONCTIONNEL_CATALOGUE_FONCTION_NODES_TEMPLATE = _COMMON_CONTEXT + """
Étape "enrichissement", couche FONCTIONNELLE — CATALOGUE, NŒUDS FONCTION. Ta SEULE tâche : pour
CHAQUE entité Fonction du registre mentionnée (même dans un tableau récapitulatif, une liste à
puces, un diagramme ou une simple énumération) dans ce fragment, produis un nœud complet. C'EST
UNE TÂCHE D'ÉNUMÉRATION EXHAUSTIVE : si le registre contient 30 Fonction pour ce document et que ce
fragment les mentionne, produis-en la quasi-totalité — ne t'arrête PAS après les 5-10 premières. Ne
produis AUCUNE relation (tableau "relations" vide), AUCUN nœud Regle_Metier (traité dans une autre
étape) et AUCUN nœud Domaine_Fonctionnel/Processus_Fonctionnel (traités ailleurs).

""" + _CATALOGUE_DEFINITIONS + """

""" + _COMMON_PROPERTIES_BLOCK + """

""" + _FIABILITE_BLOCK + """

RÈGLES :
1. N'invente JAMAIS un nom de fonction non cité dans le document.
2. EXHAUSTIVITÉ avant tout : préfère des descriptions courtes (1 phrase, voire reprise du libellé
   du document) mais COUVRE TOUTES les Fonction du registre présentes dans ce fragment, plutôt que
   de détailler longuement quelques-unes seulement.
3. Ne produis un nœud complet QUE pour les ids du registre portant le label Fonction.
4. "relations" DOIT être un tableau vide [] — les relations sont traitées dans une autre étape.

""" + _REGISTRE_INSTRUCTIONS + """

""" + _ENRICH_OUTPUT_FORMAT


_ENRICH_FONCTIONNEL_CATALOGUE_REGLE_NODES_TEMPLATE = _COMMON_CONTEXT + """
Étape "enrichissement", couche FONCTIONNELLE — CATALOGUE, NŒUDS REGLE_METIER. Ta SEULE tâche : pour
CHAQUE entité Regle_Metier du registre mentionnée (même dans un tableau récapitulatif, une liste à
puces, un diagramme ou une simple énumération, y compris les règles identifiées par un code comme
"RG-01") dans ce fragment, produis un nœud complet. C'EST UNE TÂCHE D'ÉNUMÉRATION EXHAUSTIVE : si
le registre contient 20 Regle_Metier pour ce document et que ce fragment les mentionne,
produis-en la quasi-totalité — ne t'arrête PAS après les 5-10 premières. Ne produis AUCUNE
relation (tableau "relations" vide), AUCUN nœud Fonction (traité dans une autre étape) et AUCUN
nœud Domaine_Fonctionnel/Processus_Fonctionnel (traités ailleurs).

""" + _CATALOGUE_DEFINITIONS + """

""" + _COMMON_PROPERTIES_BLOCK + """

""" + _FIABILITE_BLOCK + """

RÈGLES :
1. N'invente JAMAIS un nom/code de règle non cité dans le document.
2. EXHAUSTIVITÉ avant tout : préfère des descriptions courtes (1 phrase, voire reprise du libellé
   du document) mais COUVRE TOUTES les Regle_Metier du registre présentes dans ce fragment, plutôt
   que de détailler longuement quelques-unes seulement.
3. Ne produis un nœud complet QUE pour les ids du registre portant le label Regle_Metier.
4. "relations" DOIT être un tableau vide [] — les relations sont traitées dans une autre étape.

""" + _REGISTRE_INSTRUCTIONS + """

""" + _ENRICH_OUTPUT_FORMAT


_ENRICH_FONCTIONNEL_CATALOGUE_RELATIONS_TEMPLATE = _COMMON_CONTEXT + """
Étape "enrichissement", couche FONCTIONNELLE — CATALOGUE, RELATIONS (Fonction & Regle_Metier).
Ta SEULE tâche : identifier TOUTES les relations ci-dessous impliquant les Fonction/Regle_Metier
du registre mentionnées dans ce fragment. C'EST UNE TÂCHE D'ÉNUMÉRATION EXHAUSTIVE : si le
registre contient 30 Fonction rattachées à des domaines dans ce fragment (même implicitement, via
un regroupement/titre/tableau/diagramme), produis les 30 relations CATALOGUE correspondantes — ne
t'arrête PAS après les 5-10 premières. Ne produis AUCUN nœud (tableau "nodes" vide).

""" + _CATALOGUE_DEFINITIONS + """

""" + _CATALOGUE_RELATION_TYPES + """

""" + _FIABILITE_BLOCK + """

RÈGLES :
1. N'invente AUCUNE relation non déductible du document.
2. EXHAUSTIVITÉ avant tout : une relation CATALOGUE par Fonction rattachée à un domaine dans ce
   fragment, même si le rattachement n'est que structurel (ex regroupement dans un diagramme, une
   section, un tableau).
3. "nodes" DOIT être un tableau vide [] — les nœuds sont traités dans une autre étape. Référence
   uniquement des ids déjà présents dans le registre.

""" + _REGISTRE_INSTRUCTIONS + """

""" + _ENRICH_OUTPUT_FORMAT


# Scindé en nœuds seuls / relations seules — même pattern que le catalogue fonctionnel : un appel
# unique combinant ~150 Composant + relations alterne entre "tous les nœuds, 0 relation" et
# l'inverse (cf. diagnostic, Composant 151 au registre / 25 importés).
_ENRICH_APPLICATIF_NODES_TEMPLATE = _COMMON_CONTEXT + """
Étape "enrichissement", couche APPLICATIVE — NŒUDS. Ta SEULE tâche : pour CHAQUE entité de TA
couche présente dans le registre (Composant, Point_Entree, Interface_Utilisateur, Job_Batch,
Unite_Execution, Procedure_Reutilisable) mentionnée (même dans un tableau récapitulatif, une liste
à puces, un diagramme ou une simple énumération) dans ce fragment, produis un nœud complet. C'EST
UNE TÂCHE D'ÉNUMÉRATION EXHAUSTIVE : si le registre contient 100 Composant pour ce document et que
ce fragment en mentionne 30, produis-en la quasi-totalité — ne t'arrête PAS après les 5-10
premiers. Ne produis AUCUNE relation (tableau "relations" vide).

""" + _COMMON_PROPERTIES_BLOCK + """

PROPRIÉTÉS SUPPLÉMENTAIRES (optionnelles, n'inclure que si déductible du document) :
- Composant : technologie (COBOL_BATCH|COBOL_CICS|JCL|VSAM_KSDS|VSAM_ESDS|VSAM_AIX|DB2_ZOS|IMS_DLI|IBM_MQ|BMS),
  typeExecution (ONLINE|BATCH|UTILITAIRE|SERVICE)

""" + _FIABILITE_BLOCK + """

RÈGLES :
1. N'invente JAMAIS un nom de programme/job/step non cité dans le document.
2. Ne crée PAS de Unite_Execution pour les steps de compilation/link-edit — seulement pour la
   logique métier.
3. EXHAUSTIVITÉ avant tout : préfère des descriptions courtes (1 phrase, voire reprise du libellé
   du document) mais COUVRE TOUS les ids de cette couche du registre présents dans ce fragment,
   plutôt que de détailler longuement quelques-uns seulement.
4. Ne produis un nœud complet QUE pour les ids du registre portant un label de cette couche
   (Composant, Point_Entree, Interface_Utilisateur, Job_Batch, Unite_Execution,
   Procedure_Reutilisable).
5. "relations" DOIT être un tableau vide [] — les relations sont traitées dans une autre étape.

""" + _REGISTRE_INSTRUCTIONS + """

""" + _ENRICH_OUTPUT_FORMAT


_ENRICH_APPLICATIF_RELATIONS_TEMPLATE = _COMMON_CONTEXT + """
Étape "enrichissement", couche APPLICATIVE — RELATIONS. Ta SEULE tâche : identifier TOUTES les
relations ci-dessous impliquant les entités de cette couche (Composant, Point_Entree,
Interface_Utilisateur, Job_Batch, Unite_Execution, Procedure_Reutilisable) du registre mentionnées
dans ce fragment. C'EST UNE TÂCHE D'ÉNUMÉRATION EXHAUSTIVE : ne t'arrête PAS après les 5-10
premières relations. Ne produis AUCUN nœud (tableau "nodes" vide).

TYPES DE RELATIONS DE CETTE COUCHE (from → to : propriétés) :
- APPELLE : Composant→Composant  → {fiabilite, typeAppel: STATIQUE|DYNAMIQUE|REDIRECT, conditionnel: boolean}
- DECLENCHE : {Unite_Execution,Point_Entree}→Composant  → {fiabilite}
- CONTIENT_STEP : Job_Batch→Unite_Execution  → {fiabilite, ordre: integer}

""" + _FIABILITE_BLOCK + """

RÈGLES :
1. N'invente AUCUNE relation non déductible du document.
2. EXHAUSTIVITÉ avant tout : couvre toutes les relations APPELLE/DECLENCHE/CONTIENT_STEP
   déductibles de ce fragment pour les entités du registre, même si le lien n'est que structurel
   (ex un diagramme d'appels, un tableau de steps de job).
3. "nodes" DOIT être un tableau vide [] — les nœuds sont traités dans une autre étape. Référence
   uniquement des ids déjà présents dans le registre (peuvent appartenir à d'autres couches).

""" + _REGISTRE_INSTRUCTIONS + """

""" + _ENRICH_OUTPUT_FORMAT


_ENRICH_DONNEES_TEMPLATE = _COMMON_CONTEXT + """
Étape "enrichissement", couche DONNÉES. Pour les entités de TA couche présentes dans le registre
(Store_Donnees, Store_Echange, Table_Relationnelle, Store_Hierarchique, Structure_Partagee,
Entite_Donnees, Canal_Messagerie), produis leurs propriétés complètes et les relations de cette
couche.

""" + _COMMON_PROPERTIES_BLOCK + """

PROPRIÉTÉS SUPPLÉMENTAIRES (optionnelles, n'inclure que si déductible du document) :
- Store_Donnees / Table_Relationnelle / Store_Hierarchique : technologie, modeAcces (R|W|RW|RW_CONTENTION)
- Entite_Donnees / Table_Relationnelle / Store_Donnees : regpd (boolean) — données à caractère personnel

TYPES DE RELATIONS DE CETTE COUCHE (from → to : propriétés) :
- ACCEDE_A : Composant→{Store_Donnees,Store_Echange,Table_Relationnelle,Store_Hierarchique,Canal_Messagerie}
  → {fiabilite, mode: R|W|RW, operations: sous-ensemble de ["C","R","U","D"], contention: boolean}
  (operations = lecture d'une matrice CRUD si disponible ; mode se déduit : uniquement "R" -> "R",
   uniquement parmi C/U/D -> "W", mélange lecture+écriture -> "RW")
- INCLUT : Composant→Structure_Partagee  → {fiabilite}
- CORRESPOND_A : Entite_Donnees→{Store_Donnees,Table_Relationnelle,Store_Hierarchique}  → {fiabilite}

""" + _FIABILITE_BLOCK + """

RÈGLES :
1. N'invente JAMAIS un nom de fichier/table/structure non cité dans le document.
2. Une Structure_Partagee ne contient jamais de logique exécutable (uniquement des données).
3. Store_Echange = transitoire, sans accès par clé. Store_Donnees = accès direct par clé.
4. Ne produis un nœud complet QUE pour les ids du registre portant un label de cette couche
   (Store_Donnees, Store_Echange, Table_Relationnelle, Store_Hierarchique, Structure_Partagee,
   Entite_Donnees, Canal_Messagerie). Les relations peuvent référencer des ids d'autres couches
   (ex un Composant) présents dans le registre.

""" + _REGISTRE_INSTRUCTIONS + """

""" + _ENRICH_OUTPUT_FORMAT


_ENRICH_TRANSVERSE_TEMPLATE = _COMMON_CONTEXT + """
Étape "enrichissement", couche TRANSVERSE. Cette couche ne produit AUCUN nœud des couches
fonctionnelle/applicative/données : elle relie un Composant à une Fonction ou une Regle_Metier
(implémentation), et matérialise les zones d'incertitude.

""" + _COMMON_PROPERTIES_BLOCK + """

PROPRIÉTÉS SUPPLÉMENTAIRES :
- Zone_Incertitude : description (obligatoire) explicitant ce qui manque ou est supposé

TYPES DE RELATIONS / NŒUDS DE CETTE COUCHE :
- IMPLEMENTE : Composant→Fonction  → {fiabilite}
- ENCODE_REGLE : Composant→Regle_Metier  → {fiabilite, typeEncodage: EXPLICITE|IMPLICITE}
- Zone_Incertitude (inc:) — nœud, ex "inc:INC-001"
- GENERE_INCERTITUDE : <n'importe quel nœud du registre>→Zone_Incertitude  → {fiabilite}

""" + _FIABILITE_BLOCK + """

RÈGLES :
1. N'établis une relation IMPLEMENTE/ENCODE_REGLE QUE si le lien Composant↔Fonction/Regle_Metier
   est explicitement déductible du fragment (ex le programme implémente cette logique).
2. Ne produis un nœud complet QUE pour les Zone_Incertitude que TU identifies dans ce fragment
   (id "inc:INC-NNN" — poursuis la numérotation du registre s'il en contient déjà). Les relations
   IMPLEMENTE/ENCODE_REGLE/GENERE_INCERTITUDE référencent des ids du registre (autres couches).

""" + _REGISTRE_INSTRUCTIONS + """

""" + _ENRICH_OUTPUT_FORMAT


# "fonctionnel" est scindé en 3 sous-étapes : un appel unique couvrant les 4 labels + 6 types de
# relation négligeait systématiquement le catalogue Fonction/Regle_Metier (cf. diagnostic — 0
# nœud Fonction produit malgré 37 au registre). Même séparé, un appel "catalogue" combinant
# nœuds+relations alterne entre "tous les nœuds, 0 relation" et l'inverse selon les runs — d'où
# la scission nœuds/relations. Chaque sous-étape porte sur un périmètre disjoint (nœuds) ou ne
# produit que des relations référençant le registre, donc aucun risque de doublon à l'import.
_ENRICH_TEMPLATES = {
    "fonctionnel": [
        _ENRICH_FONCTIONNEL_DOMAINES_TEMPLATE,
        _ENRICH_FONCTIONNEL_CATALOGUE_FONCTION_NODES_TEMPLATE,
        _ENRICH_FONCTIONNEL_CATALOGUE_REGLE_NODES_TEMPLATE,
        _ENRICH_FONCTIONNEL_CATALOGUE_RELATIONS_TEMPLATE,
    ],
    "applicatif": [
        _ENRICH_APPLICATIF_NODES_TEMPLATE,
        _ENRICH_APPLICATIF_RELATIONS_TEMPLATE,
    ],
    "donnees": _ENRICH_DONNEES_TEMPLATE,
    "transverse": _ENRICH_TRANSVERSE_TEMPLATE,
}


# ── Étape 3 — Complétion (par document, relations inter-chunks) ──────────────────────────────

_COMPLETION_SYSTEM_TEMPLATE = _COMMON_CONTEXT + """
Étape "complétion" — dernière passe sur le document complet. Le registre fourni en entrée
contient TOUTES les entités inventoriées dans ce document (tous chunks confondus, avec leurs
ids/labels/noms). Ta tâche : identifier les relations qui traversent plusieurs chunks et qui
n'ont donc pas pu être détectées lors de l'enrichissement par fragment (ex une Fonction décrite
au début du document, liée à une Regle_Metier décrite à la fin).

""" + _ALL_LABELS_BLOCK + """

TYPES DE RELATIONS RECONNUS (from → to : propriétés) — identiques aux étapes précédentes :
- CONTIENT : Domaine_Fonctionnel→Processus_Fonctionnel | System→Domaine_Fonctionnel  → {fiabilite}
- CATALOGUE : Domaine_Fonctionnel→Fonction  → {fiabilite}
- PORTE_REGLE : Fonction→Regle_Metier  → {fiabilite, typePortage: EXPLICITE|IMPLICITE}
- ORCHESTRE : Processus_Fonctionnel→Fonction  → {fiabilite, ordre: integer, conditionnel: boolean}
- ORIENTE_PAR : Processus_Fonctionnel→Regle_Metier  → {fiabilite, typeRoutage: BRANCHEMENT|BOUCLE|CONDITION_SORTIE}
- IMPLEMENTE : Composant→Fonction  → {fiabilite}
- ENCODE_REGLE : Composant→Regle_Metier  → {fiabilite, typeEncodage: EXPLICITE|IMPLICITE}
- APPELLE : Composant→Composant  → {fiabilite, typeAppel: STATIQUE|DYNAMIQUE|REDIRECT, conditionnel: boolean}
- INCLUT : Composant→Structure_Partagee  → {fiabilite}
- ACCEDE_A : Composant→{Store_Donnees,Store_Echange,Table_Relationnelle,Store_Hierarchique,Canal_Messagerie}
  → {fiabilite, mode: R|W|RW, operations: sous-ensemble de ["C","R","U","D"], contention: boolean}
- DECLENCHE : {Unite_Execution,Point_Entree}→Composant  → {fiabilite}
- CONTIENT_STEP : Job_Batch→Unite_Execution  → {fiabilite, ordre: integer}
- CORRESPOND_A : Entite_Donnees→{Store_Donnees,Table_Relationnelle,Store_Hierarchique}  → {fiabilite}
- GENERE_INCERTITUDE : <n'importe quel nœud>→Zone_Incertitude  → {fiabilite}
- DEPEND_DE : Domaine_Fonctionnel→Domaine_Fonctionnel | Fonction→Fonction | Processus_Fonctionnel→Processus_Fonctionnel
  → {fiabilite, nature: DONNEES|ORDONNANCEMENT|APPEL|DECLENCHEMENT|GOUVERNANCE, description (optionnel)}
  - entre deux Domaine_Fonctionnel : DONNEES (flux de données), ORDONNANCEMENT (dépendance
    d'exécution/ordonnancement) ou GOUVERNANCE (un domaine gouverne/pilote l'autre)
  - entre deux Fonction : APPEL (une fonction appelle/invoque une autre fonction)
  - entre deux Processus_Fonctionnel : DECLENCHEMENT (un processus déclenche un autre processus)
  Particulièrement pertinent à cette étape : capture les dépendances entre entités décrites dans
  des chunks différents (ex deux Domaine_Fonctionnel présentés dans des sections séparées).

""" + _FIABILITE_BLOCK + """

RÈGLES :
1. Ne crée AUCUN nouveau nœud sauf des Zone_Incertitude (id "inc:INC-NNN", poursuis la
   numérotation du registre). N'utilise QUE des ids "from"/"to" présents dans le registre fourni
   (ou un nouvel id "inc:..." que tu crées).
2. Ne RECRÉE PAS une relation déjà évidente dans un seul fragment (ex Fonction↔Regle_Metier du
   même paragraphe) — concentre-toi sur les liens qui traversent le document (Domaine_Fonctionnel
   du début ↔ Fonction décrite plus loin, Composant ↔ Fonction/Regle_Metier mentionnés dans des
   sections différentes, etc.).
3. N'invente AUCUNE relation non déductible du document.

FORMAT DE SORTIE (JSON strict, clés EXACTES "nodes"/"relations" ; "nodes" ne contient QUE des
Zone_Incertitude éventuelles, tableaux vides si rien à ajouter) :
{
  "nodes": [
    {"id": "inc:INC-003", "label": "Zone_Incertitude",
     "properties": {"nom": "...", "fiabilite": "MANQUANT", "source": "...", "description": "..."}}
  ],
  "relations": [
    {"from": "df:DF-01", "to": "mf:MF-12", "type": "CATALOGUE", "properties": {"fiabilite": "FAIT"}},
    {"from": "df:BC4", "to": "df:BC1", "type": "DEPEND_DE", "properties": {"fiabilite": "FAIT", "nature": "DONNEES"}}
  ]
}"""


# Configuration corpus persistée (modale "Configuration corpus" du frontend) — surcharge les
# valeurs par défaut issues des variables d'environnement ci-dessus, sans nécessiter de redémarrage.
_CONFIG_PATH = os.path.join(os.path.dirname(__file__), "..", "extract_config.json")


class ExtractConfig(BaseModel):
    nom_systeme: str = _SYS_NAME
    stack_primaire: str = _SYS_STACK_PRIMARY
    stacks_secondaires: str = _SYS_STACK_SECONDARY
    langue_documentation: str = _SYS_DOC_LANG
    contexte_libre: str = ""


def _load_extract_config() -> ExtractConfig:
    if os.path.exists(_CONFIG_PATH):
        try:
            with open(_CONFIG_PATH, "r", encoding="utf-8") as f:
                return ExtractConfig(**json.load(f))
        except Exception as exc:
            logger.warning("Lecture de extract_config.json impossible (%s) — valeurs par défaut.", exc)
    return ExtractConfig()


def _save_extract_config(config: ExtractConfig) -> None:
    with open(_CONFIG_PATH, "w", encoding="utf-8") as f:
        json.dump(config.model_dump(), f, ensure_ascii=False, indent=2)


def _render(template: str, config: ExtractConfig) -> str:
    text = (
        template
        .replace("__SYS_NAME__", config.nom_systeme)
        .replace("__STACK_PRIMARY__", config.stack_primaire)
        .replace("__STACK_SECONDARY__", config.stacks_secondaires)
        .replace("__DOC_LANG__", config.langue_documentation)
    )
    if config.contexte_libre.strip():
        text += (
            "\n\nCONTEXTE MÉTIER ADDITIONNEL FOURNI PAR L'UTILISATEUR (à prendre en compte en"
            " priorité pour orienter l'extraction) :\n" + config.contexte_libre.strip()
        )
    return text


# ── Chunking par section Markdown (T4) ────────────────────────────────────────────────────────

_CHUNK_MAX_CHARS = 18000
_SECTION_HEADER_RE = re.compile(r"^#{1,4}\s+.*$", re.MULTILINE)


def _split_into_chunks(text: str, max_chars: int = _CHUNK_MAX_CHARS) -> list[str]:
    """Découpe un document sur ses titres `#`-`####` en fragments <= max_chars.

    Une section qui dépasse max_chars à elle seule est découpée brutalement (rare en
    pratique sur le corpus actuel). Les documents courts restent en un seul fragment.
    """
    if len(text) <= max_chars:
        return [text]

    boundaries = [m.start() for m in _SECTION_HEADER_RE.finditer(text)]
    if not boundaries or boundaries[0] != 0:
        boundaries = [0] + boundaries

    sections = [
        text[start:(boundaries[i + 1] if i + 1 < len(boundaries) else len(text))]
        for i, start in enumerate(boundaries)
    ]

    chunks: list[str] = []
    current = ""
    for section in sections:
        if len(section) > max_chars:
            if current:
                chunks.append(current)
                current = ""
            for i in range(0, len(section), max_chars):
                chunks.append(section[i:i + max_chars])
            continue
        if current and len(current) + len(section) > max_chars:
            chunks.append(current)
            current = section
        else:
            current += section
    if current:
        chunks.append(current)
    return chunks


# ── Pipeline d'extraction par document (T4) ───────────────────────────────────────────────────

# Préfixes de noms de déploiement traités comme modèles de raisonnement (GPT-5.x, o-series) :
# ceux-ci exigent max_completion_tokens + reasoning_effort et ne supportent pas temperature.
_REASONING_MODEL_PREFIXES = tuple(
    p.strip().lower()
    for p in os.environ.get("AZURE_OPENAI_REASONING_MODELS", "gpt-5,o1,o3,o4").split(",")
    if p.strip()
)


def _is_reasoning_model(model: str) -> bool:
    name = model.lower()
    return any(name.startswith(p) for p in _REASONING_MODEL_PREFIXES)


def _llm_json_call(
    oai: AzureOpenAI,
    model: str,
    system: str,
    user: str,
    max_tokens: int,
    reasoning_effort: str = "medium",
    temperature: float = 0.1,
) -> dict:
    """Appel JSON au modèle. Les modèles de raisonnement (GPT-5.x, o-series) consomment leur
    budget de sortie avec des reasoning_tokens cachés en plus du JSON produit, d'où le ×2
    sur max_completion_tokens par rapport au max_tokens des modèles non-raisonnants."""
    kwargs: dict = dict(
        model=model,
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        response_format={"type": "json_object"},
    )
    if _is_reasoning_model(model):
        kwargs["max_completion_tokens"] = max_tokens * 2
        # reasoning_effort n'est pas encore un kwarg typé dans openai==1.57.0 — passé via extra_body.
        kwargs["extra_body"] = {"reasoning_effort": reasoning_effort}
    else:
        kwargs["max_tokens"] = max_tokens
        kwargs["temperature"] = temperature

    resp = oai.chat.completions.create(**kwargs)
    return json.loads(resp.choices[0].message.content)


def _import_entities(payload: dict) -> dict[str, int]:
    with httpx.Client(timeout=30.0) as http:
        r = http.post(
            f"{_ADGM_BASE}/admin/import-entities",
            json=payload,
            headers={"Content-Type": "application/json"},
        )
        r.raise_for_status()
        return r.json().get("imported", {})


def _process_document(
    source_file: str,
    full_text: str,
    oai: AzureOpenAI,
    model: str,
    inv_model: str,
    system_prompts: dict,
) -> tuple[dict[str, int], int]:
    """Pipeline complet pour un document : inventaire (registre cumulatif par chunk),
    enrichissement par chunk × couche, puis complétion des relations inter-chunks.

    Retourne (entités importées par type, nombre d'erreurs)."""
    chunks = _split_into_chunks(full_text)

    registry: list[dict] = []
    registry_ids: set[str] = set()
    chunk_couches: list[list[str]] = []
    imported: dict[str, int] = {}
    errors = 0

    # Étape 1 — inventaire (séquentiel, registre cumulatif)
    for chunk in chunks:
        registre_json = json.dumps({"entities": registry}, ensure_ascii=False)
        user_content = (
            f"Document: {source_file}\n\n"
            f"Registre actuel (entités déjà inventoriées dans ce document) :\n{registre_json}\n\n"
            f"Fragment à analyser :\n{chunk}"
        )
        try:
            # temperature=0 — l'inventaire doit être déterministe : un même fragment doit
            # toujours produire le même découpage en domaines/entités (cf. diagnostic, même
            # texte source produisant tantôt 8 domaines BC1-8 tantôt 4 domaines génériques).
            result = _llm_json_call(
                oai, inv_model, system_prompts["inventaire"], user_content, 4000,
                reasoning_effort="low", temperature=0.0,
            )
        except Exception as exc:
            logger.warning("Inventaire échoué pour %s: %s", source_file, exc)
            errors += 1
            chunk_couches.append([])
            continue

        for entity in result.get("entities", []):
            eid = entity.get("id")
            if eid and eid not in registry_ids:
                registry_ids.add(eid)
                registry.append({"id": eid, "label": entity.get("label"), "nom": entity.get("nom")})
        chunk_couches.append(result.get("couches", []))

    # Étape 2 — enrichissement par chunk × couche identifiée (1 ou plusieurs sous-prompts/couche)
    for chunk, couches in zip(chunks, chunk_couches):
        registre_json = json.dumps({"entities": registry}, ensure_ascii=False)
        for couche in dict.fromkeys(couches):
            prompts = system_prompts["enrich"].get(couche)
            if prompts is None:
                continue
            if not isinstance(prompts, list):
                prompts = [prompts]
            user_content = (
                f"Document: {source_file}\n\n"
                f"Registre (entités de ce document) :\n{registre_json}\n\n"
                f"Fragment à enrichir :\n{chunk}"
            )
            for system_prompt in prompts:
                try:
                    # temperature=0 — l'exhaustivité d'une étape d'énumération (couvrir TOUS les
                    # ids du registre pour cette couche/sous-tâche) ne doit pas dépendre du tirage
                    # aléatoire ; cf. variance observée entre runs (Regle_Metier 0/6/0, Composant
                    # 35/49/35 sur le même document avec un prompt inchangé).
                    result = _llm_json_call(oai, model, system_prompt, user_content, 8000, temperature=0.0)
                    for k, v in _import_entities(result).items():
                        imported[k] = imported.get(k, 0) + v
                except Exception as exc:
                    logger.warning("Enrichissement '%s' échoué pour %s: %s", couche, source_file, exc)
                    errors += 1

    # Étape 3 — complétion (relations inter-chunks, sur le registre complet du document)
    if registry:
        registre_json = json.dumps({"entities": registry}, ensure_ascii=False)
        user_content = f"Document: {source_file}\n\nRegistre complet :\n{registre_json}"
        try:
            result = _llm_json_call(oai, model, system_prompts["completion"], user_content, 6000)
            for k, v in _import_entities(result).items():
                imported[k] = imported.get(k, 0) + v
        except Exception as exc:
            logger.warning("Complétion échouée pour %s: %s", source_file, exc)
            errors += 1

    return imported, errors


def _run_extract_job(job_id: str, credential) -> None:
    _jobs[job_id]["status"] = "running"
    _jobs[job_id]["message"] = "Nettoyage de la couche fonctionnelle existante…"
    try:
        # 0. Clear functional layer before rebuild — garantit la cohérence du graphe
        # en supprimant les entités stales (FunctionalDomain/MacroFunction/Program/DataEntity)
        # avant de recréer depuis l'intégralité des documents. Les TechnicalNode et leurs
        # annotations candidate7R sont préservés par cet endpoint.
        try:
            with httpx.Client(timeout=30.0) as http:
                r = http.delete(f"{_ADGM_BASE}/admin/functional-entities")
                if r.is_success:
                    logger.info("Functional entities cleared: %s deleted", r.json().get("deleted", "?"))
                else:
                    logger.warning("clear-functional-entities returned %s — continuing anyway", r.status_code)
        except Exception as exc:
            logger.warning("clear-functional-entities call failed: %s — continuing anyway", exc)

        _jobs[job_id]["message"] = "Lecture des documents indexés…"

        # 1. Fetch all chunks from Azure AI Search, grouped by source_file
        search_client = SearchClient(
            endpoint=os.environ["AZURE_SEARCH_ENDPOINT"],
            index_name=INDEX_NAME,
            credential=credential,
        )
        source_files: dict[str, list[tuple[int, str]]] = {}
        for result in search_client.search(
            search_text="*",
            select=["source_file", "chunk_index", "content"],
            order_by=["chunk_index asc"],
            top=5000,
        ):
            sf = result["source_file"]
            if sf not in source_files:
                source_files[sf] = []
            source_files[sf].append((result.get("chunk_index", 0), result.get("content", "")))

        docs_total = len(source_files)
        _jobs[job_id]["docs_total"] = docs_total
        _jobs[job_id]["message"] = f"{docs_total} documents trouvés — extraction en cours…"

        if docs_total == 0:
            _jobs[job_id].update(status="done", message="Aucun document trouvé dans l'index.")
            return

        full_texts: dict[str, str] = {
            sf: "\n\n".join(c for _, c in sorted(chunks, key=lambda x: x[0]))
            for sf, chunks in source_files.items()
        }

        # 2. GPT-4o client via managed identity / DefaultAzureCredential
        token_provider = get_bearer_token_provider(
            credential, "https://cognitiveservices.azure.com/.default"
        )
        # api_version récente requise pour max_completion_tokens / reasoning_effort
        # (modèles de raisonnement GPT-5.x) — sans impact sur gpt-4o, qui reste compatible.
        oai = AzureOpenAI(
            azure_endpoint=os.environ["AZURE_OPENAI_ENDPOINT"],
            azure_ad_token_provider=token_provider,
            api_version=os.environ.get("AZURE_OPENAI_API_VERSION", "2025-04-01-preview"),
        )
        model = os.environ["AZURE_OPENAI_GPT4O_DEPLOYMENT"]
        # Modèle dédié à l'inventaire (étape courte/économique) — par défaut le même modèle,
        # surchargeable une fois une stratégie à deux niveaux validée (T2).
        inv_model = os.environ.get("AZURE_OPENAI_INVENTAIRE_DEPLOYMENT", model)

        config = _load_extract_config()
        system_prompts = {
            "inventaire": _render(_INVENTAIRE_SYSTEM_TEMPLATE, config),
            "enrich": {
                couche: (
                    [_render(t, config) for t in tpl] if isinstance(tpl, list) else _render(tpl, config)
                )
                for couche, tpl in _ENRICH_TEMPLATES.items()
            },
            "completion": _render(_COMPLETION_SYSTEM_TEMPLATE, config),
        }

        total_imported: dict[str, int] = {}
        import_errors = 0
        docs_done = 0
        lock = threading.Lock()

        # 3. Traite chaque document via le pipeline inventaire → enrichissement → complétion,
        # avec une concurrence bornée entre documents (4-6 en parallèle).
        with ThreadPoolExecutor(max_workers=5) as pool:
            futures = {
                pool.submit(_process_document, sf, text, oai, model, inv_model, system_prompts): sf
                for sf, text in full_texts.items()
            }
            for future in as_completed(futures):
                source_file = futures[future]
                try:
                    imported, errors = future.result()
                except Exception as exc:
                    logger.exception("Extraction du document %s a échoué: %s", source_file, exc)
                    imported, errors = {}, 1

                with lock:
                    docs_done += 1
                    for k, v in imported.items():
                        total_imported[k] = total_imported.get(k, 0) + v
                    import_errors += errors
                    _jobs[job_id]["docs_processed"] = docs_done
                    _jobs[job_id]["message"] = (
                        f"Extraction ({docs_done}/{docs_total}) : {source_file} terminé."
                    )

        # 4. Rapport de couverture déterministe (regex codes vs ids importés)
        _jobs[job_id]["message"] = "Calcul du rapport de couverture…"
        try:
            coverage_report = compute_coverage(full_texts)
        except Exception as exc:
            logger.warning("Calcul de couverture impossible: %s", exc)
            coverage_report = {}

        total_entities = sum(total_imported.values())
        done_msg = f"Extraction terminée — {docs_total} documents, {total_entities} entités importées."
        if import_errors:
            done_msg += f" ({import_errors} erreur(s) — voir logs serveur)"
        _jobs[job_id].update(
            status="done",
            docs_processed=docs_total,
            message=done_msg,
            entities_imported=total_imported,
            import_errors=import_errors,
            coverage=coverage_report,
        )

    except Exception as exc:
        logger.exception("Extraction job %s failed: %s", job_id, exc)
        _jobs[job_id].update(status="error", message=f"Erreur : {exc}")


@router.post("/extract/graph", response_model=ExtractStatus, status_code=202)
async def start_extract(background_tasks: BackgroundTasks, request: Request):
    """Lance l'extraction asynchrone : lit l'index Search, appelle GPT-4o,
    pousse les entités dans Neo4j via fn-adgm-graph/admin/import-entities."""
    job_id = str(uuid.uuid4())
    _jobs[job_id] = {
        "status": "pending",
        "message": "En file d'attente…",
        "docs_total": 0,
        "docs_processed": 0,
        "entities_imported": {},
        "import_errors": 0,
        "coverage": {},
    }
    background_tasks.add_task(_run_extract_job, job_id, request.app.state.credential)
    return ExtractStatus(job_id=job_id, **_jobs[job_id])


@router.get("/extract/graph/{job_id}", response_model=ExtractStatus)
async def get_extract_status(job_id: str):
    """Retourne l'état courant d'un job d'extraction."""
    if job_id not in _jobs:
        raise HTTPException(status_code=404, detail="Job introuvable.")
    return ExtractStatus(job_id=job_id, **_jobs[job_id])


@router.get("/extract/config", response_model=ExtractConfig)
async def get_extract_config():
    """Retourne la configuration corpus courante (fichier local ou défauts/env)."""
    return _load_extract_config()


@router.put("/extract/config", response_model=ExtractConfig)
async def put_extract_config(config: ExtractConfig):
    """Persiste la configuration corpus — utilisée par les prochaines extractions."""
    _save_extract_config(config)
    return config
