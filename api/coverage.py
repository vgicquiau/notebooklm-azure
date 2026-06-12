"""Rapport de couverture déterministe — compare les codes/programmes mentionnés dans le
corpus source (regex) aux ids effectivement importés dans le graphe ADG-M (/graph/nodes).

Utilisé par le pipeline d'extraction (routers/extract.py) pour mesurer objectivement ce qui
manque après une passe d'import, indépendamment de toute auto-évaluation du LLM.
"""

import os
import re

import httpx

_ADGM_BASE = os.environ.get(
    "ADGM_GRAPH_API_URL",
    "https://modernagent-adgm-dev.azurewebsites.net/api/graph",
).rstrip("/")

# Préfixes de codes métier réutilisés tels qu'écrits dans le corpus (taxonomie v2.0)
_CODE_PATTERNS = {
    "df": re.compile(r"\bDF-\d+\b"),
    "mf": re.compile(r"\bMF-\d+\b"),
    "rg": re.compile(r"\bRG-\d+\b"),
    "pm": re.compile(r"\bPM-\d+\b"),
    "dt": re.compile(r"\bDT-\d+\b"),
}

# Heuristique noms de programmes COBOL : token majuscule de 6-8 caractères contenant au
# moins un chiffre (ex COSGN00C, CBACT01C) — exclut les acronymes/mots-clés purement alpha.
_PROGRAM_PATTERN = re.compile(r"\b[A-Z][A-Z0-9]{5,7}\b")

_LABEL_BY_PREFIX = {
    "df": "Domaine_Fonctionnel",
    "mf": "Fonction",
    "rg": "Regle_Metier",
    "pm": "Processus_Fonctionnel",
    "dt": "Domaine_Technique",
    "comp": "Composant",
}


def scan_codes(text: str) -> dict[str, set[str]]:
    """Scanne un texte source et retourne les codes/noms trouvés par préfixe."""
    found = {prefix: set(pattern.findall(text)) for prefix, pattern in _CODE_PATTERNS.items()}
    found["comp"] = {
        tok for tok in _PROGRAM_PATTERN.findall(text) if any(c.isdigit() for c in tok)
    }
    return found


def _fetch_imported_ids(label: str) -> set[str]:
    """Récupère tous les ids importés pour un label donné via /graph/nodes (paginé)."""
    ids: set[str] = set()
    limit = 500
    offset = 0
    with httpx.Client(timeout=30.0) as http:
        while True:
            r = http.get(
                f"{_ADGM_BASE}/nodes",
                params={"label": label, "limit": limit, "offset": offset},
            )
            if not r.is_success:
                break
            data = r.json()
            for item in data.get("items", []):
                node_id = item.get("id", "")
                if ":" in node_id:
                    ids.add(node_id.split(":", 1)[1])
            total = data.get("total", 0)
            offset += limit
            if offset >= total:
                break
    return ids


def compute_coverage(source_texts: dict[str, str]) -> dict:
    """Calcule le rapport de couverture pour l'ensemble du corpus.

    `source_texts` : {nom_fichier: texte_complet}. Retourne, par préfixe :
    {"label", "found", "imported", "missing": [...]} (missing tronqué à 50 entrées).
    """
    all_found: dict[str, set[str]] = {prefix: set() for prefix in _LABEL_BY_PREFIX}
    for text in source_texts.values():
        for prefix, codes in scan_codes(text).items():
            all_found[prefix] |= codes

    report: dict[str, dict] = {}
    for prefix, codes in all_found.items():
        label = _LABEL_BY_PREFIX[prefix]
        imported_codes = _fetch_imported_ids(label)
        missing = sorted(codes - imported_codes)
        report[prefix] = {
            "label": label,
            "found": len(codes),
            "imported": len(codes & imported_codes),
            "missing": missing[:50],
        }
    return report
