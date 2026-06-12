import json
import logging
import os
from typing import Any, Literal, Optional

from azure.identity import DefaultAzureCredential, get_bearer_token_provider
from openai import AzureOpenAI
from tenacity import retry, stop_after_attempt, wait_exponential

from .retriever import RetrievedChunk

logger = logging.getLogger(__name__)

_PROMPT_RAPIDE = """Tu es un assistant documentaire concis.
Réponds en 2-4 phrases maximum, directement au point, sans introduction ni conclusion.
Pour citer une source, utilise uniquement son numéro entre crochets : [1], [2]… (les numéros correspondent aux sources du contexte).
Si l'information est absente, dis-le en une phrase.
Langue : français."""

_PROMPT_STANDARD = """Tu es un assistant expert en analyse documentaire pour une équipe de modernisation d'applications métier.
Tu analyses un corpus de documents techniques et fonctionnels : cahiers des charges, spécifications, règles métier, documentation legacy.

Pour chaque question :
- Synthétise et raisonne : relie les informations entre elles, tire des conclusions.
- Cite tes sources avec leur numéro entre crochets [1], [2]… aux points clés, sans surcharger chaque phrase.
- Utilise des listes ou sections ## pour les réponses complexes.
- Si une information manque, dis-le brièvement puis apporte ce que tu peux déduire du contexte.
- Si tu fais une inférence, signale-la avec *(déduit du contexte)*.
Langue : français."""

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

**Langue** : français. Conserve les termes métier du corpus tels quels."""

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

    def generate(
        self,
        query: str,
        chunks: list[RetrievedChunk],
        conversation_history: list[dict[str, Any]],
        mode: Literal["rapide", "standard", "approfondi"] = "standard",
        injected_notes: Optional[list[str]] = None,
    ) -> tuple[str, int]:
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
    ) -> tuple[str, int]:
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

        return self._complete(messages, temperature=cfg["temperature"], max_tokens=cfg["max_tokens"])

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
    ) -> tuple[str, int]:
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
        return answer, total_tokens
