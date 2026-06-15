import json
import logging
import os
from typing import Any, Literal, Optional

from azure.identity import DefaultAzureCredential, get_bearer_token_provider
from openai import AzureOpenAI
from tenacity import retry, stop_after_attempt, wait_exponential

from .retriever import RetrievedChunk
from .graph_tools import LEGACYKB_TOOL_DEFINITIONS, execute_legacykb_tool

logger = logging.getLogger(__name__)


def _extract_graph_refs(tool_name: str, result: dict[str, Any]) -> list[dict[str, Any]]:
    """Extrait les références (id/kind/type/nom) des nœuds de la legacy KB effectivement
    consultés via un appel de tool, pour traçabilité (`ChatResponse.graph_references`)."""
    if "error" in result:
        return []
    if tool_name == "legacykb_get_entity":
        if result.get("id"):
            return [{"id": result["id"], "kind": result.get("kind"), "type": result.get("type"), "nom": result.get("nom")}]
        return []
    if tool_name == "legacykb_get_relations":
        center = result.get("center")
        if center and center.get("id"):
            return [{"id": center["id"], "kind": center.get("kind"), "type": center.get("type"), "nom": center.get("nom")}]
        return []
    return []


def _extract_graph_action(tool_name: str, result: dict[str, Any]) -> Optional[dict[str, Any]]:
    """Construit le payload de pilotage du canvas (`ChatResponse.graph_action`) à partir
    du résultat d'un appel à legacykb_highlight/legacykb_impact_paths. `None` pour les
    autres tools (ou en cas d'erreur du tool)."""
    if "error" in result:
        return None
    if tool_name == "legacykb_highlight":
        return {
            "type": "highlight",
            "node_ids": result.get("node_ids", []),
            "edges": [],
            "reason": result.get("reason", ""),
            "query_info": None,
        }
    if tool_name == "legacykb_impact_paths":
        center = result.get("center") or {}
        neighbors = [n for n in result.get("nodes", []) if n.get("id")]
        nodes = [center, *neighbors] if center.get("id") else neighbors
        node_ids = [n["id"] for n in nodes]
        return {
            "type": "impact_paths",
            "node_ids": node_ids,
            "nodes": nodes,
            "edges": result.get("edges", []),
            "reason": f"Impact de {center.get('nom', '?')}",
            "query_info": {"cypher": result.get("cypher"), "params": result.get("params")},
        }
    return None


# Bloc décrivant la base de connaissances legacy CardDemo (neo4j-legacykb), accessible
# via les tools legacykb_search / legacykb_get_entity / legacykb_get_relations.
_LEGACYKB_TOOLS_BLOCK = """

## Base de connaissances legacy (outils)

En complément des documents fournis en contexte, tu as accès en lecture à la base de
connaissances legacy du système CardDemo (graphe issu d'une analyse GraphRAG du code COBOL) :
programmes, copybooks, batch jobs, fichiers/tables, et domaines fonctionnels, avec leurs
descriptions et leurs relations (appels entre programmes, inclusions de copybooks, accès aux
fichiers en lecture/écriture, appartenance à un domaine fonctionnel, exécution par un job).

Utilise les outils `legacykb_search`, `legacykb_get_entity` et `legacykb_get_relations` quand
l'utilisateur mentionne un nom (même partiel) de programme/copybook/job/fichier, ou pose une
question sur des dépendances, chaînes d'appel, accès aux données ou domaines fonctionnels du
système CardDemo. Commence par `legacykb_search` pour retrouver l'identifiant, puis
`legacykb_get_entity`/`legacykb_get_relations` pour le détail.

Si l'utilisateur est sur la vue Legacy KB et demande de **montrer/surligner/isoler** des
éléments dans le graphe, utilise `legacykb_highlight` après les avoir identifiés. Pour une
question d'**impact** ("qu'est-ce qui dépend de X", "que casse-t-on si on modifie X"), utilise
`legacykb_impact_paths`. Ces deux outils pilotent directement le canvas — pas besoin de lister
leur résultat en détail dans ta réponse texte, une courte phrase de confirmation suffit.

Quand un fait provient de cette base de connaissances, signale-le par `(base de connaissances : NOM)`
— ne le numérote pas comme une source documentaire `[n]`."""

_LEGACYKB_TOOLS_BLOCK_RAPIDE = """

## Base de connaissances legacy (outils)

Si la question porte sur un programme/copybook/job/fichier nommé du système CardDemo, ou sur ses
dépendances/appels/accès aux données, utilise `legacykb_search` puis `legacykb_get_entity`/
`legacykb_get_relations` pour répondre précisément. Pour montrer/surligner des éléments dans le
graphe, utilise `legacykb_highlight` ; pour une question d'impact, `legacykb_impact_paths`.
Signale ces faits par `(base de connaissances : NOM)`."""

_PROMPT_RAPIDE = """Tu es un assistant documentaire concis.
Réponds en 2-4 phrases maximum, directement au point, sans introduction ni conclusion.
Pour citer une source, utilise uniquement son numéro entre crochets : [1], [2]… (les numéros correspondent aux sources du contexte).
Si l'information est absente, dis-le en une phrase.
Langue : français.""" + _LEGACYKB_TOOLS_BLOCK_RAPIDE

_PROMPT_STANDARD = """Tu es un assistant expert en analyse documentaire pour une équipe de modernisation d'applications métier.
Tu analyses un corpus de documents techniques et fonctionnels : cahiers des charges, spécifications, règles métier, documentation legacy.

Pour chaque question :
- Synthétise et raisonne : relie les informations entre elles, tire des conclusions.
- Cite tes sources avec leur numéro entre crochets [1], [2]… aux points clés, sans surcharger chaque phrase.
- Utilise des listes ou sections ## pour les réponses complexes.
- Si une information manque, dis-le brièvement puis apporte ce que tu peux déduire du contexte.
- Si tu fais une inférence, signale-la avec *(déduit du contexte)*.
Langue : français.""" + _LEGACYKB_TOOLS_BLOCK

_PROMPT_APPROFONDI = """Tu es un analyste expert en modernisation d'applications métier. Tu travailles sur un corpus documentaire fourni en contexte (cahiers des charges, spécifications fonctionnelles, règles métier, documentation technique, annexes).

## Posture analytique

Tu ne te contentes pas de restituer — tu **raisonnes**. Avant de répondre, tu passes mentalement en revue chaque source disponible pour :
- extraire tous les éléments pertinents à la question, même implicites
- détecter les corrélations et dépendances entre sources
- repérer les contradictions, redondances ou zones d'ombre
- organiser l'information de la manière la plus utile pour l'équipe

## Règles de réponse

**Exhaustivité** : pour toute demande de type "liste", "inventaire", "quels sont les X" — sois systématique. Passe en revue toutes les sources disponibles. Mieux vaut une liste longue et complète qu'une synthèse trop rapide qui oublie des éléments.

**Corrélation** : quand un élément apparaît dans plusieurs sources, relie-les explicitement. Exemple : "Ce flux est mentionné dans [1] comme obligatoire et confirmé dans [3] avec un détail technique supplémentaire."

**Structure adaptée** : choisis le format qui sert le mieux la réponse —
- tableau (comparaison, inventaire structuré)
- liste hiérarchique (arborescence, dépendances)
- sections ## (analyse multi-thèmes)
- prose (explication d'un concept, contexte)

**Sources** : cite les sources avec leur numéro [1], [2]… après les faits factuels clés. N'encombre pas chaque phrase — cite aux points critiques. N'utilise jamais le nom de fichier, uniquement le numéro.

**Inférence signalée** : si tu déduis quelque chose qui n'est pas explicitement écrit, signale-le avec *(déduit du contexte)* ou *"On peut en inférer que..."*

**Lacunes utiles** : si une information manque dans le corpus, dis-le en une phrase puis continue avec ce que tu peux apporter. Ne t'arrête jamais sur un "je n'ai pas trouvé".

**Contradictions** : signale explicitement toute incohérence entre documents avec les deux numéros de source en regard.

**Langue** : français. Conserve les termes métier du corpus tels quels.""" + _LEGACYKB_TOOLS_BLOCK

_MODE_CONFIG = {
    "rapide":     {"prompt": _PROMPT_RAPIDE,     "max_tokens": 600,  "temperature": 0.2},
    "standard":   {"prompt": _PROMPT_STANDARD,   "max_tokens": 2000, "temperature": 0.3},
    "approfondi": {"prompt": _PROMPT_APPROFONDI, "max_tokens": 4000, "temperature": 0.3},
}

_PROMPT_SUMMARY = """Tu résumes un échange entre un utilisateur et un assistant documentaire.
Produis un résumé factuel en 5 à 8 puces maximum : sujets abordés, faits importants évoqués, décisions, questions restées sans réponse.
Sois concis, ne reformule pas les politesses. Français."""

# Bloc de fiabilité réutilisé du système d'extraction GraphRAG
# (voir prompts-extraction-graphrag-legacy.md, "BLOC COUCHE 0 — Fiabilité")
_RELIABILITY_BLOCK = """## Fiabilité de l'information

Pour chaque élément extrait, indique son niveau de fiabilité dans le champ "fiabilite" :
- "FAIT" : écrit explicitement, noir sur blanc, dans la source.
- "HYPOTHESE" : déduit logiquement d'éléments explicites de la source, mais non formulé tel quel.
- "SUPPOSE" : plausible au vu du contexte mais non confirmé par le texte — à vérifier.
- "MANQUANT" : information demandée par la question mais absente de cette source.

En cas de doublon entre plusieurs sources avec des fiabilités différentes pour le même élément, la fusion conserve la plus fiable selon l'ordre : FAIT > HYPOTHESE > SUPPOSE > MANQUANT."""

_PROMPT_EXTRACTION_BATCH = f"""Tu es un analyste qui extrait systématiquement des informations d'un lot de sources documentaires, pour répondre à une question d'inventaire/extraction posée par un utilisateur.

## Tâche

Passe en revue **chaque source du lot** et extrais tous les éléments pertinents par rapport à la question posée — même partiels, même implicites. Ne résume pas, ne synthétise pas : liste chaque élément distinct.

{_RELIABILITY_BLOCK}

## Format de sortie

Réponds UNIQUEMENT avec un objet JSON de cette forme :
```json
{{"items": [
  {{"label": "intitulé court de l'élément", "description": "détail factuel", "fiabilite": "FAIT", "source": 1}}
]}}
```
- "source" est le numéro de la source (entier) tel qu'indiqué dans l'en-tête "--- [Source N] ---".
- Si aucun élément pertinent n'est trouvé dans ce lot, réponds `{{"items": []}}`."""

_PROMPT_SYNTHESIS_FINAL = """Tu es un analyste expert en modernisation d'applications métier. On t'a fourni une liste structurée d'éléments déjà extraits du corpus documentaire (avec leur fiabilité et leur source d'origine), en réponse à une demande d'extraction/inventaire de l'utilisateur.

## Tâche

Rédige la réponse finale à partir de cette liste structurée :
- Choisis le format le plus lisible (tableau, liste hiérarchique, sections ##) selon la nature de la demande.
- Regroupe les éléments par thème si pertinent.
- Cite la source de chaque élément avec son numéro entre crochets [n].
- Si un élément a la fiabilité "HYPOTHESE" ou "SUPPOSE", signale-le avec *(déduit du contexte)* ou *(à vérifier)*.
- Si des éléments sont marqués "MANQUANT", regroupe-les dans une section finale "Lacunes identifiées".
- Sois exhaustif : n'omets aucun élément de la liste fournie.

Langue : français."""

_PROMPT_CLASSIFY = """Tu classes une question utilisateur posée à un assistant documentaire en deux catégories :
- "extraction" : la question demande une liste, un inventaire, un recensement exhaustif, "tous les / toutes les", "extrais", "liste-moi", "quelles sont toutes les...".
- "synthese" : toute autre question (analyse, explication, comparaison, opinion, question ponctuelle).

Réponds avec un seul mot : extraction ou synthese."""

# Taille des lots de chunks pour le pipeline d'extraction multi-passes (mode "approfondi")
_EXTRACTION_BATCH_SIZE = 5

_RELIABILITY_ORDER = {"FAIT": 0, "HYPOTHESE": 1, "SUPPOSE": 2, "MANQUANT": 3}


class Generator:
    def __init__(self, credential: DefaultAzureCredential):
        token_provider = get_bearer_token_provider(
            credential, "https://cognitiveservices.azure.com/.default"
        )
        self.client = AzureOpenAI(
            azure_endpoint=os.environ["AZURE_OPENAI_ENDPOINT"],
            azure_ad_token_provider=token_provider,
            api_version="2024-10-21",
        )
        self.model = os.environ["AZURE_OPENAI_GPT4O_DEPLOYMENT"]

    def _build_context(
        self,
        chunks: list[RetrievedChunk],
        injected_notes: Optional[list[str]] = None,
    ) -> str:
        parts = []
        # Notes injectées par l'utilisateur (priorité haute — placées en premier)
        if injected_notes:
            for i, text in enumerate(injected_notes, 1):
                parts.append(f"--- [Note utilisateur {i}] ---\n{text}")
        # Chunks récupérés par la recherche hybride
        for i, chunk in enumerate(chunks, 1):
            header = f"--- [Source {i}] {chunk.source_file}, page {chunk.page_number}"
            if chunk.section:
                header += f" | Section : {chunk.section}"
            header += " ---"
            parts.append(f"{header}\n{chunk.content}")
        return "\n\n".join(parts)

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=2, max=20))
    def _complete(self, messages: list[dict[str, Any]], temperature: float, max_tokens: int, **kwargs) -> tuple[str, int]:
        response = self.client.chat.completions.create(
            model=self.model,
            messages=messages,
            temperature=temperature,
            max_tokens=max_tokens,
            seed=42,
            **kwargs,
        )
        return response.choices[0].message.content, response.usage.total_tokens

    def _complete_with_tools(
        self, messages: list[dict[str, Any]], temperature: float, max_tokens: int, max_rounds: int = 3
    ) -> tuple[str, int, list[dict[str, Any]], Optional[dict[str, Any]]]:
        """Comme `_complete`, mais autorise le LLM à appeler les tools de la legacy KB
        (`legacykb_search`/`legacykb_get_entity`/`legacykb_get_relations`/
        `legacykb_highlight`/`legacykb_impact_paths`) en boucle, jusqu'à `max_rounds`
        aller-retours. Renvoie en plus `graph_refs` (entités/domaines consultés) et
        `graph_action` (dernier payload de pilotage du canvas, ou None)."""
        total_tokens = 0
        graph_refs: dict[str, dict[str, Any]] = {}
        graph_action: Optional[dict[str, Any]] = None

        for _ in range(max_rounds):
            response = self.client.chat.completions.create(
                model=self.model,
                messages=messages,
                temperature=temperature,
                max_tokens=max_tokens,
                seed=42,
                tools=LEGACYKB_TOOL_DEFINITIONS,
                tool_choice="auto",
            )
            total_tokens += response.usage.total_tokens
            message = response.choices[0].message

            if not message.tool_calls:
                return message.content, total_tokens, list(graph_refs.values()), graph_action

            messages.append(message.model_dump(exclude_unset=True))
            for tool_call in message.tool_calls:
                try:
                    arguments = json.loads(tool_call.function.arguments)
                except (json.JSONDecodeError, TypeError):
                    arguments = {}
                result = execute_legacykb_tool(tool_call.function.name, arguments)
                messages.append({
                    "role": "tool",
                    "tool_call_id": tool_call.id,
                    "content": json.dumps(result, ensure_ascii=False),
                })
                for ref in _extract_graph_refs(tool_call.function.name, result):
                    graph_refs[ref["id"]] = ref
                action = _extract_graph_action(tool_call.function.name, result)
                if action is not None:
                    graph_action = action

        # Dernier essai sans tools pour forcer une réponse texte si max_rounds est atteint
        response = self.client.chat.completions.create(
            model=self.model,
            messages=messages,
            temperature=temperature,
            max_tokens=max_tokens,
            seed=42,
        )
        total_tokens += response.usage.total_tokens
        return response.choices[0].message.content, total_tokens, list(graph_refs.values()), graph_action

    def generate(
        self,
        query: str,
        chunks: list[RetrievedChunk],
        conversation_history: list[dict[str, Any]],
        mode: Literal["rapide", "standard", "approfondi"] = "standard",
        injected_notes: Optional[list[str]] = None,
    ) -> tuple[str, int, list[dict[str, Any]], Optional[dict[str, Any]]]:
        if mode == "approfondi" and self.classify_query(query) == "extraction":
            return self.generate_deep_extraction(query, chunks, conversation_history, injected_notes)
        return self._generate_single_pass(query, chunks, conversation_history, mode, injected_notes)

    def _generate_single_pass(
        self,
        query: str,
        chunks: list[RetrievedChunk],
        conversation_history: list[dict[str, Any]],
        mode: Literal["rapide", "standard", "approfondi"],
        injected_notes: Optional[list[str]],
    ) -> tuple[str, int, list[dict[str, Any]], Optional[dict[str, Any]]]:
        cfg = _MODE_CONFIG[mode]
        context = self._build_context(chunks, injected_notes)

        user_message = f"""Contexte documentaire :
{context}

---
Question : {query}"""

        messages = [
            {"role": "system", "content": cfg["prompt"]},
            *conversation_history[-8:],
            {"role": "user", "content": user_message},
        ]

        return self._complete_with_tools(messages, temperature=cfg["temperature"], max_tokens=cfg["max_tokens"])

    def summarize(self, messages: list[dict[str, str]], existing_summary: Optional[str]) -> str:
        """Résume un lot de messages, fusionné avec un résumé existant éventuel."""
        transcript = "\n".join(f"{m['role']}: {m['content']}" for m in messages)
        user_content = transcript
        if existing_summary:
            user_content = f"Résumé précédent :\n{existing_summary}\n\nNouvel échange à intégrer :\n{transcript}"

        completion_messages = [
            {"role": "system", "content": _PROMPT_SUMMARY},
            {"role": "user", "content": user_content},
        ]
        summary, _ = self._complete(completion_messages, temperature=0.1, max_tokens=300)
        return summary

    def classify_query(self, query: str) -> Literal["synthese", "extraction"]:
        """Classifie une question en 'extraction' (inventaire exhaustif) ou 'synthese'."""
        try:
            messages = [
                {"role": "system", "content": _PROMPT_CLASSIFY},
                {"role": "user", "content": query},
            ]
            answer, _ = self._complete(messages, temperature=0.0, max_tokens=5)
            return "extraction" if "extraction" in (answer or "").lower() else "synthese"
        except Exception:
            logger.exception("Échec de la classification de requête — repli sur 'synthese'.")
            return "synthese"

    def _extract_batch(self, query: str, batch: list[RetrievedChunk], offset: int) -> tuple[list[dict[str, Any]], int]:
        """Extrait les éléments pertinents d'un lot de chunks. `offset` = index de départ pour la numérotation des sources."""
        context = self._build_context(batch)
        # Renumérote l'en-tête des sources pour qu'il corresponde au numéro global (offset + position locale)
        for local_i, chunk in enumerate(batch, 1):
            context = context.replace(f"[Source {local_i}]", f"[Source {offset + local_i}]", 1)

        messages = [
            {"role": "system", "content": _PROMPT_EXTRACTION_BATCH},
            {"role": "user", "content": f"Question de l'utilisateur : {query}\n\n{context}"},
        ]
        try:
            raw, tokens = self._complete(
                messages, temperature=0.0, max_tokens=2000, response_format={"type": "json_object"}
            )
            data = json.loads(raw)
            items = data.get("items", [])
            if not isinstance(items, list):
                return [], tokens
            return items, tokens
        except Exception:
            logger.exception("Échec de l'extraction d'un lot — lot ignoré.")
            return [], 0

    def _merge_extractions(self, all_items: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Déduplique par label normalisé, en conservant la fiabilité la plus haute."""
        merged: dict[str, dict[str, Any]] = {}
        for item in all_items:
            label = str(item.get("label", "")).strip()
            if not label:
                continue
            key = label.lower()
            reliability = str(item.get("fiabilite", "SUPPOSE")).upper()
            if reliability not in _RELIABILITY_ORDER:
                reliability = "SUPPOSE"
            item["fiabilite"] = reliability

            existing = merged.get(key)
            if existing is None or _RELIABILITY_ORDER[reliability] < _RELIABILITY_ORDER[existing["fiabilite"]]:
                merged[key] = item
        return list(merged.values())

    def _synthesize_final(
        self,
        query: str,
        merged_items: list[dict[str, Any]],
        conversation_history: list[dict[str, Any]],
    ) -> tuple[str, int]:
        items_json = json.dumps(merged_items, ensure_ascii=False, indent=2)
        user_message = f"""Éléments extraits du corpus (format JSON) :
{items_json}

---
Question initiale de l'utilisateur : {query}"""

        messages = [
            {"role": "system", "content": _PROMPT_SYNTHESIS_FINAL},
            *conversation_history[-8:],
            {"role": "user", "content": user_message},
        ]
        return self._complete(messages, temperature=0.3, max_tokens=4000)

    def generate_deep_extraction(
        self,
        query: str,
        chunks: list[RetrievedChunk],
        conversation_history: list[dict[str, Any]],
        injected_notes: Optional[list[str]] = None,
    ) -> tuple[str, int, list[dict[str, Any]], Optional[dict[str, Any]]]:
        """Pipeline map-reduce pour les requêtes d'extraction/inventaire en mode 'approfondi' :
        extraction par lots de chunks (avec tag de fiabilité) -> fusion -> synthèse finale."""
        total_tokens = 0
        all_items: list[dict[str, Any]] = []

        for offset in range(0, len(chunks), _EXTRACTION_BATCH_SIZE):
            batch = chunks[offset:offset + _EXTRACTION_BATCH_SIZE]
            items, tokens = self._extract_batch(query, batch, offset)
            all_items.extend(items)
            total_tokens += tokens

        # Les notes injectées sont traitées comme une source supplémentaire de fiabilité "FAIT"
        for i, text in enumerate(injected_notes or [], 1):
            all_items.append({"label": f"Note utilisateur {i}", "description": text, "fiabilite": "FAIT", "source": f"Note {i}"})

        merged_items = self._merge_extractions(all_items)

        if not merged_items:
            return self._generate_single_pass(query, chunks, conversation_history, "approfondi", injected_notes)

        answer, tokens = self._synthesize_final(query, merged_items, conversation_history)
        total_tokens += tokens
        return answer, total_tokens, [], None
