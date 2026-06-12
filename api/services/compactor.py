"""Compaction de l'historique de conversation ("résumé glissant").

Quand l'historique non compacté dépasse `COMPACT_THRESHOLD_TURNS`, les
`COMPACT_BATCH_TURNS` tours les plus anciens sont résumés par le LLM
(mode peu coûteux) et fusionnés dans `sessions.summary_text`. Les
messages résumés restent en base pour l'affichage/export mais ne sont
plus envoyés au LLM via `session_store.get_history_for_llm`.
"""

import logging

from . import session_store
from .generator import Generator

logger = logging.getLogger(__name__)

COMPACT_THRESHOLD_TURNS = 12  # 24 messages non compactés
COMPACT_BATCH_TURNS = 4       # résume les 8 plus anciens messages


def should_compact(session_id: str) -> bool:
    uncompacted = session_store.get_uncompacted_message_ids(session_id)
    return len(uncompacted) > COMPACT_THRESHOLD_TURNS * 2


def compact_session(session_id: str, generator: Generator) -> None:
    """Résume le plus ancien lot de messages et marque-les comme compactés.

    Échec silencieux : la compaction est un best-effort, elle ne doit
    jamais faire échouer une requête de chat.
    """
    try:
        uncompacted = session_store.get_uncompacted_message_ids(session_id)
        batch_size = COMPACT_BATCH_TURNS * 2
        if len(uncompacted) <= batch_size:
            return

        batch = uncompacted[:batch_size]
        batch_messages = [{"role": role, "content": content} for (_id, role, content) in batch]

        existing_summary = session_store.get_summary(session_id)
        new_summary = generator.summarize(batch_messages, existing_summary)

        session_store.set_summary(session_id, new_summary)
        session_store.mark_compacted(session_id, [msg_id for (msg_id, _role, _content) in batch])
        logger.debug("Session %s compactée : %d messages résumés.", session_id, len(batch))
    except Exception:
        logger.exception("Échec de la compaction pour la session %s — ignoré.", session_id)
