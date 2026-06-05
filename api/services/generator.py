import os
from typing import Any, Literal, Optional

from azure.identity import DefaultAzureCredential, get_bearer_token_provider
from openai import AzureOpenAI
from tenacity import retry, stop_after_attempt, wait_exponential

from .retriever import RetrievedChunk

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
    def generate(
        self,
        query: str,
        chunks: list[RetrievedChunk],
        conversation_history: list[dict[str, Any]],
        mode: Literal["rapide", "standard", "approfondi"] = "standard",
        injected_notes: Optional[list[str]] = None,
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

        response = self.client.chat.completions.create(
            model=self.model,
            messages=messages,
            temperature=cfg["temperature"],
            max_tokens=cfg["max_tokens"],
            seed=42,
        )

        answer = response.choices[0].message.content
        total_tokens = response.usage.total_tokens
        return answer, total_tokens
