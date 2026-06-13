// src/explorationApi.js — Client API du module Exploration (CRUD ArchiMate 3.x)
//
// Relaie vers /api/graph/exploration/* (api/routers/exploration.py + graph.py →
// fn-adgm-graph). Chaque fonction reçoit `apiFetch` (wrapper _apiFetch de App.jsx,
// injecte X-API-Key) et le `role` courant (VIEWER/ARCHITECT/ADMIN), transmis via
// l'en-tête X-User-Role — cf. resolve_role()/require_role() dans function_app.py.
// Voir notebooklm-azure/docs/specs/SDD_Exploration_v1.md.

const EXPLORATION_API_BASE = window.location.origin + '/api/graph/exploration';
const EXPLORATION_ROLE_KEY = 'nlaz-exploration-role';
const EXPLORATION_ROLES = ['VIEWER', 'ARCHITECT', 'ADMIN'];

// ── Persistance du rôle courant (sélecteur dev/démo, cf. ExplorationPage) ─────
const useCurrentRole = () => {
  const [role, setRole] = React.useState(() => {
    const stored = localStorage.getItem(EXPLORATION_ROLE_KEY);
    return EXPLORATION_ROLES.includes(stored) ? stored : 'VIEWER';
  });

  const updateRole = React.useCallback((next) => {
    if (!EXPLORATION_ROLES.includes(next)) return;
    setRole(next);
    localStorage.setItem(EXPLORATION_ROLE_KEY, next);
  }, []);

  return [role, updateRole];
};

// ── Requête générique ──────────────────────────────────────────────────────
const _request = async (apiFetch, role, method, path, { params, body } = {}) => {
  let url = `${EXPLORATION_API_BASE}${path}`;
  if (params) {
    const qs = new URLSearchParams(
      Object.entries(params).filter(([, v]) => v !== undefined && v !== null && v !== '')
    ).toString();
    if (qs) url += `?${qs}`;
  }

  const headers = { 'X-User-Role': role };
  if (body !== undefined) headers['Content-Type'] = 'application/json';

  const res = await apiFetch(url, {
    method,
    headers,
    body: body !== undefined ? JSON.stringify(body) : undefined,
  });

  const data = await res.json().catch(() => ({}));
  if (!res.ok) {
    const err = new Error(data.error || data.detail || `HTTP ${res.status}`);
    err.status = res.status;
    err.body = data;
    err.retryAfter = res.headers.get('Retry-After');
    throw err;
  }
  return data;
};

// ── Gestion centralisée des erreurs (T4-F-02, SDD §7) ──────────────────────
// Normalise une erreur levée par _request (ou une erreur réseau sans réponse)
// en { message, retryable, retryAfter } pour affichage toast/bannière.
const handleApiError = (err) => {
  const status = err.status;
  const retryAfter = err.retryAfter || err.body?.retryAfter || null;
  let message = err.body?.error || err.message || 'Erreur inconnue';
  let retryable = false;

  if (status === undefined) {
    message = 'Connexion impossible — vérifiez votre réseau et réessayez';
    retryable = true;
  } else if (status === 429) {
    message = retryAfter
      ? `Trop de requêtes — réessayez dans ${retryAfter}s`
      : 'Trop de requêtes — réessayez plus tard';
  } else if (status === 500 || status === 503) {
    message = status === 503
      ? 'Base de données temporairement indisponible — réessayez'
      : 'Erreur serveur — réessayez';
    retryable = true;
  }

  return { status, code: err.body?.code, message, retryable, retryAfter };
};

const explorationApi = {
  // ── Nœuds ──────────────────────────────────────────────────────────────
  fetchNodes: (apiFetch, role, params) => _request(apiFetch, role, 'GET', '/nodes', { params }),
  fetchNode: (apiFetch, role, id) => _request(apiFetch, role, 'GET', `/nodes/${id}`),
  createNode: (apiFetch, role, payload) => _request(apiFetch, role, 'POST', '/nodes', { body: payload }),
  updateNode: (apiFetch, role, id, payload) => _request(apiFetch, role, 'PATCH', `/nodes/${id}`, { body: payload }),
  deleteNode: (apiFetch, role, id, cascade = false) =>
    _request(apiFetch, role, 'DELETE', `/nodes/${id}`, { params: cascade ? { cascade: 'true' } : undefined }),
  fetchOrphans: (apiFetch, role, params) => _request(apiFetch, role, 'GET', '/orphans', { params }),
  bulkTagNodes: (apiFetch, role, payload) => _request(apiFetch, role, 'POST', '/nodes/bulk-tag', { body: payload }),

  // ── Relations ──────────────────────────────────────────────────────────
  fetchRelations: (apiFetch, role, params) => _request(apiFetch, role, 'GET', '/relations', { params }),
  fetchRelation: (apiFetch, role, id) => _request(apiFetch, role, 'GET', `/relations/${id}`),
  createRelation: (apiFetch, role, payload) => _request(apiFetch, role, 'POST', '/relations', { body: payload }),
  updateRelation: (apiFetch, role, id, payload) => _request(apiFetch, role, 'PATCH', `/relations/${id}`, { body: payload }),
  deleteRelation: (apiFetch, role, id) => _request(apiFetch, role, 'DELETE', `/relations/${id}`),

  // ── Audit (ADMIN) ──────────────────────────────────────────────────────
  fetchAudit: (apiFetch, role, params) => _request(apiFetch, role, 'GET', '/audit', { params }),

  // ── Health ─────────────────────────────────────────────────────────────
  fetchHealth: (apiFetch, role) => _request(apiFetch, role, 'GET', '/health'),
};

Object.assign(window, {
  explorationApi,
  useCurrentRole,
  EXPLORATION_ROLES,
  handleApiError,
});
