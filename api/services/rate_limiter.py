"""Rate limiting en mémoire pour /api/chat (glissement de fenêtre de 60 s)."""

import time
from collections import defaultdict

from fastapi import HTTPException, Request

_RATE_LIMIT = 20    # requêtes max par fenêtre
_RATE_WINDOW = 60   # fenêtre en secondes
_STALE_TTL   = 300  # bucket supprimé après 5 min d'inactivité
_MAX_IPS     = 10_000  # cap pour éviter une OOM par flood d'IPs éphémères

_windows: dict[str, list[float]] = defaultdict(list)
_last_seen: dict[str, float] = {}


def check_rate_limit(request: Request) -> None:
    ip = request.client.host if request.client else "unknown"
    now = time.time()
    cutoff = now - _RATE_WINDOW
    stale_cutoff = now - _STALE_TTL

    # Éviction des buckets inactifs depuis plus de _STALE_TTL secondes.
    # Effectuée à chaque requête pour rester O(1) amorti sans thread dédié.
    if len(_windows) > _MAX_IPS // 2:
        stale_ips = [k for k, t in _last_seen.items() if t < stale_cutoff]
        for k in stale_ips:
            _windows.pop(k, None)
            _last_seen.pop(k, None)

    # Si après éviction le dict est toujours au-dessus du cap, on refuse de
    # tracer de nouvelles IPs — les IPs existantes continuent d'être limitées.
    if ip not in _windows and len(_windows) >= _MAX_IPS:
        raise HTTPException(status_code=429, detail="Trop de requêtes simultanées.")

    bucket = _windows[ip]
    while bucket and bucket[0] < cutoff:
        bucket.pop(0)

    if len(bucket) >= _RATE_LIMIT:
        raise HTTPException(
            status_code=429,
            detail=f"Trop de requêtes. Limite : {_RATE_LIMIT} appels par {_RATE_WINDOW}s.",
        )

    bucket.append(now)
    _last_seen[ip] = now
