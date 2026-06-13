from fastapi import APIRouter, Request, Response

from api.routers.graph import _forward

router = APIRouter()

# Le proxy générique de graph.py ne relaie que GET/PATCH/DELETE vers fn-adgm-graph
# (POST /admin/analyze y est volontairement exclu). Le module Exploration a besoin
# de POST (création de nœuds/relations, bulk-tag) — ce routeur ajoute donc le relais
# POST, restreint au sous-chemin /graph/exploration/*. Les GET/PATCH/DELETE
# /graph/exploration/* sont déjà couverts par /graph/{path:path} dans graph.py.


@router.post("/graph/exploration/{path:path}")
async def proxy_exploration_post(path: str, request: Request):
    return await _forward("POST", f"exploration/{path}", request)
