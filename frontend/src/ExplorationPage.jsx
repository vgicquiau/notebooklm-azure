// src/ExplorationPage.jsx — Page du module Exploration (CRUD ArchiMate 3.x)
// Props: apiFetch(url, options) — wrapper _apiFetch (injecte X-API-Key), fourni par App
//
// Phase 0 (T0-F-01) : sélecteur de rôle + bandeau santé.
// Phase 1 (T1-F-01..05) : vues CRUD nœuds — NodeListView, NodeDetailView,
// NodeFormView, OrphanListView, DeleteConfirmModal (cf. PLAN_EXPLORATION_v1.md,
// wireframes SDD_Exploration_v1.md §5).

const _ROLE_LABELS = {
  VIEWER: 'Lecteur',
  ARCHITECT: 'Architecte',
  ADMIN: 'Administrateur',
};

const RoleSelector = ({ role, onChange }) => (
  <label style={{ display: 'flex', alignItems: 'center', gap: 8, fontSize: 13, color: T.sub }}>
    Rôle
    <select
      value={role}
      onChange={e => onChange(e.target.value)}
      style={{
        height: 32, padding: '0 10px',
        borderRadius: T.radiusSm, border: `1px solid ${T.border}`,
        background: T.white, color: T.ink,
        fontFamily: T.font, fontSize: 13, fontWeight: 500, cursor: 'pointer',
      }}
    >
      {EXPLORATION_ROLES.map(r => (
        <option key={r} value={r}>{_ROLE_LABELS[r] || r}</option>
      ))}
    </select>
  </label>
);

const HealthBanner = ({ apiFetch, role }) => {
  const [status, setStatus] = React.useState('loading'); // 'loading' | 'ok' | 'error'

  React.useEffect(() => {
    let cancelled = false;
    explorationApi.fetchHealth(apiFetch, role)
      .then(data => { if (!cancelled) setStatus(data?.status === 'ok' ? 'ok' : 'error'); })
      .catch(() => { if (!cancelled) setStatus('error'); });
    return () => { cancelled = true; };
  }, [apiFetch, role]);

  if (status === 'loading') return null;

  const ok = status === 'ok';
  return (
    <div style={{
      padding: '8px 14px', borderRadius: T.radiusSm, fontSize: 12.5, lineHeight: 1.4,
      background: ok ? '#eafaf0' : '#fdecec',
      color: ok ? T.success : T.danger,
      border: `1px solid ${ok ? '#bfead0' : '#f6c9c9'}`,
    }}>
      {ok ? 'Connexion Neo4j (module Exploration) : OK' : 'Connexion Neo4j (module Exploration) indisponible.'}
    </div>
  );
};

// ── Styles partagés ─────────────────────────────────────────────
const _ctl = {
  height: 34, padding: '0 10px',
  borderRadius: T.radiusSm, border: `1px solid ${T.border}`,
  background: T.white, color: T.ink,
  fontFamily: T.font, fontSize: 13,
};

const _btn = (variant = 'default') => {
  const base = {
    ..._ctl, display: 'inline-flex', alignItems: 'center', gap: 6,
    cursor: 'pointer', fontWeight: 600, whiteSpace: 'nowrap',
  };
  if (variant === 'primary') {
    return { ...base, background: T.azure, color: T.white, border: `1px solid ${T.azure}` };
  }
  if (variant === 'danger') {
    return { ...base, background: T.white, color: T.danger, border: `1px solid #f6c9c9` };
  }
  return base;
};

const _label = { fontSize: 12, fontWeight: 600, color: T.sub, marginBottom: 4, display: 'block' };

const ExpPill = ({ children, tone = 'default' }) => {
  const tones = {
    default: { background: T.panel2, color: T.ink, border: `1px solid ${T.border}` },
    azure:   { background: T.azureSoft, color: T.azureInk, border: `1px solid ${T.azureBorder}` },
    danger:  { background: '#fdecec', color: T.danger, border: '1px solid #f6c9c9' },
  };
  return (
    <span style={{
      display: 'inline-flex', alignItems: 'center',
      padding: '2px 8px', borderRadius: T.radiusPill,
      fontSize: 11.5, fontWeight: 600, lineHeight: 1.6,
      ...(tones[tone] || tones.default),
    }}>
      {children}
    </span>
  );
};

const _fmtDate = (iso) => {
  if (!iso) return '—';
  try { return new Date(iso).toLocaleString('fr-FR'); } catch { return iso; }
};

// Notifie les autres onglets (Graphe ADG-M) qu'une mutation Exploration a eu
// lieu, pour invalidation cross-onglets (T3-F-03).
const _notifyGraphChanged = () => {
  window.dispatchEvent(new CustomEvent('adgm:graph-changed'));
};

const ErrorBanner = ({ message, onRetry }) => {
  if (!message) return null;
  return (
    <div style={{
      display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 12,
      padding: '8px 14px', borderRadius: T.radiusSm, fontSize: 12.5,
      background: '#fdecec', color: T.danger, border: '1px solid #f6c9c9',
    }}>
      <span>{message}</span>
      {onRetry && (
        <button style={{ ..._btn(), padding: '4px 8px', height: 'auto', flexShrink: 0 }} onClick={onRetry}>
          <Ic.Refresh s={12} /> Réessayer
        </button>
      )}
    </div>
  );
};

// Affiche un toast transversal (T4-F-02) — consommé par <ToastStack> dans
// ExplorationPage. Découplé via CustomEvent pour éviter le prop-drilling,
// même convention que adgm:graph-changed (T3-F-03).
const _pushToast = (tone, message) => {
  window.dispatchEvent(new CustomEvent('adgm:toast', { detail: { tone, message } }));
};

const ToastStack = ({ toasts, onDismiss }) => {
  if (toasts.length === 0) return null;
  const tones = {
    error: { background: '#fdecec', color: T.danger, border: '1px solid #f6c9c9' },
    warning: { background: '#fff7e6', color: '#b45309', border: '1px solid #fde0a8' },
    info: { background: T.azureSoft, color: T.azureInk, border: `1px solid ${T.azureBorder}` },
  };
  return (
    <div style={{
      position: 'fixed', bottom: 20, right: 20, display: 'flex',
      flexDirection: 'column', gap: 8, zIndex: 1000, maxWidth: 360,
    }}>
      {toasts.map(t => (
        <div key={t.id} style={{
          display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 12,
          padding: '10px 14px', borderRadius: T.radiusSm, fontSize: 13, boxShadow: '0 2px 8px rgba(0,0,0,0.12)',
          ...(tones[t.tone] || tones.error),
        }}>
          <span>{t.message}</span>
          <button onClick={() => onDismiss(t.id)} style={{
            border: 'none', background: 'none', cursor: 'pointer', color: 'inherit',
            fontSize: 16, lineHeight: 1, padding: 0,
          }}>×</button>
        </div>
      ))}
    </div>
  );
};

// ── NodeListView (T1-F-01) ───────────────────────────────────────
const NodeListView = ({ apiFetch, role, canWrite, onView, onEdit, onDelete, onCreate, refreshKey }) => {
  const LIMIT = 50;
  const [filters, setFilters] = React.useState({
    layer: '', elementType: '', aspect: '', name: '', tags: '', orphansOnly: false,
  });
  const [skip, setSkip] = React.useState(0);
  const [items, setItems] = React.useState([]);
  const [total, setTotal] = React.useState(0);
  const [loading, setLoading] = React.useState(false);
  const [error, setError] = React.useState(null);
  const [retryable, setRetryable] = React.useState(false);
  const [selected, setSelected] = React.useState(() => new Set());
  const [bulkTag, setBulkTag] = React.useState('');
  const [bulkBusy, setBulkBusy] = React.useState(false);
  const [bulkError, setBulkError] = React.useState(null);

  const updateFilter = (patch) => {
    setSkip(0);
    setFilters(f => ({ ...f, ...patch }));
  };

  const load = React.useCallback(() => {
    setLoading(true);
    setError(null);
    explorationApi.fetchNodes(apiFetch, role, {
      layer: filters.layer || undefined,
      elementType: filters.elementType || undefined,
      aspect: filters.aspect || undefined,
      name: filters.name || undefined,
      tags: filters.tags || undefined,
      orphansOnly: filters.orphansOnly ? 'true' : undefined,
      skip, limit: LIMIT,
    })
      .then(data => { setItems(data.items || []); setTotal(data.total || 0); setRetryable(false); })
      .catch(err => {
        const info = handleApiError(err);
        setError(info.message);
        setRetryable(info.retryable);
        if (info.retryable) _pushToast('error', info.message);
      })
      .finally(() => setLoading(false));
  }, [apiFetch, role, filters, skip]);

  React.useEffect(() => { load(); }, [load, refreshKey]);

  React.useEffect(() => { setSelected(new Set()); }, [refreshKey, skip, filters]);

  const toggleSelected = (id) => {
    setSelected(s => {
      const next = new Set(s);
      if (next.has(id)) next.delete(id); else next.add(id);
      return next;
    });
  };

  const toggleSelectAll = () => {
    setSelected(s => (s.size === items.length ? new Set() : new Set(items.map(i => i.id))));
  };

  const applyBulkTag = async (action) => {
    if (!bulkTag.trim() || selected.size === 0) return;
    setBulkBusy(true);
    setBulkError(null);
    try {
      await explorationApi.bulkTagNodes(apiFetch, role, {
        nodeIds: Array.from(selected), action, tag: bulkTag.trim(),
      });
      setSelected(new Set());
      setBulkTag('');
      load();
      _notifyGraphChanged();
    } catch (err) {
      const info = handleApiError(err);
      setBulkError(info.message);
      _pushToast('error', info.message);
    } finally {
      setBulkBusy(false);
    }
  };

  const elementTypeOptions = filters.layer
    ? (ARCHIMATE_ELEMENT_TYPES_BY_LAYER[filters.layer] || [])
    : Array.from(ARCHIMATE_ALL_ELEMENT_TYPES).sort();

  const totalPages = Math.max(1, Math.ceil(total / LIMIT));
  const page = Math.floor(skip / LIMIT) + 1;

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 14 }}>
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
        <h2 style={{ margin: 0, fontSize: 15, fontWeight: 700, color: T.ink }}>Nœuds</h2>
        {canWrite && (
          <button style={_btn('primary')} onClick={onCreate}>
            <Ic.Plus s={14} /> Nouveau nœud
          </button>
        )}
      </div>

      <div style={{ display: 'flex', flexWrap: 'wrap', gap: 8, alignItems: 'center' }}>
        <select style={_ctl} value={filters.layer}
          onChange={e => updateFilter({ layer: e.target.value, elementType: '' })}>
          <option value="">Toutes les couches</option>
          {ARCHIMATE_LAYERS.map(l => <option key={l} value={l}>{l}</option>)}
        </select>

        <select style={_ctl} value={filters.elementType}
          onChange={e => updateFilter({ elementType: e.target.value })}>
          <option value="">Tous les types</option>
          {elementTypeOptions.map(t => <option key={t} value={t}>{t}</option>)}
        </select>

        <select style={_ctl} value={filters.aspect}
          onChange={e => updateFilter({ aspect: e.target.value })}>
          <option value="">Tous les aspects</option>
          {ARCHIMATE_ASPECTS.map(a => <option key={a} value={a}>{a}</option>)}
        </select>

        <input style={{ ..._ctl, minWidth: 200 }} placeholder="🔍 Rechercher par nom…"
          value={filters.name} onChange={e => updateFilter({ name: e.target.value })} />

        <input style={{ ..._ctl, minWidth: 160 }} placeholder="Tags (séparés par ,)"
          value={filters.tags} onChange={e => updateFilter({ tags: e.target.value })} />

        <label style={{ display: 'flex', alignItems: 'center', gap: 6, fontSize: 13, color: T.sub }}>
          <input type="checkbox" checked={filters.orphansOnly}
            onChange={e => updateFilter({ orphansOnly: e.target.checked })} />
          Orphelins uniquement
        </label>

        {(filters.layer || filters.elementType || filters.aspect || filters.name || filters.tags || filters.orphansOnly) && (
          <button style={_btn()} onClick={() => updateFilter({
            layer: '', elementType: '', aspect: '', name: '', tags: '', orphansOnly: false,
          })}>
            <Ic.Close s={12} /> Effacer les filtres
          </button>
        )}

        <button style={_btn()} onClick={load} title="Rafraîchir">
          <Ic.Refresh s={14} />
        </button>
      </div>

      <ErrorBanner message={error} onRetry={retryable ? load : undefined} />

      {canWrite && selected.size > 0 && (
        <div style={{
          display: 'flex', alignItems: 'center', gap: 10, flexWrap: 'wrap',
          padding: '8px 12px', borderRadius: T.radiusSm, fontSize: 12.5,
          background: T.panel, border: `1px solid ${T.border}`,
        }}>
          <strong>Sélection : {selected.size} nœud{selected.size === 1 ? '' : 's'}</strong>
          <input style={{ ..._ctl, minWidth: 140 }} placeholder="Tag…"
            value={bulkTag} onChange={e => setBulkTag(e.target.value)} disabled={bulkBusy} />
          <button style={_btn('primary')} disabled={bulkBusy || !bulkTag.trim()}
            onClick={() => applyBulkTag('add')}>
            + Ajouter le tag
          </button>
          <button style={_btn()} disabled={bulkBusy || !bulkTag.trim()}
            onClick={() => applyBulkTag('remove')}>
            − Retirer le tag
          </button>
          <button style={_btn()} disabled={bulkBusy} onClick={() => setSelected(new Set())}>
            Annuler la sélection
          </button>
          {bulkError && <span style={{ color: T.danger }}>{bulkError}</span>}
        </div>
      )}

      <div style={{ border: `1px solid ${T.border}`, borderRadius: T.radiusMd, overflow: 'hidden' }}>
        <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 13 }}>
          <thead>
            <tr style={{ background: T.panel, textAlign: 'left' }}>
              {canWrite && (
                <th style={{ padding: '8px 12px', width: 28 }}>
                  <input type="checkbox" checked={items.length > 0 && selected.size === items.length}
                    onChange={toggleSelectAll} />
                </th>
              )}
              <th style={{ padding: '8px 12px' }}>Nom</th>
              <th style={{ padding: '8px 12px' }}>Layer</th>
              <th style={{ padding: '8px 12px' }}>Type</th>
              <th style={{ padding: '8px 12px', textAlign: 'right' }}>Relations</th>
              <th style={{ padding: '8px 12px', textAlign: 'right' }}>Actions</th>
            </tr>
          </thead>
          <tbody>
            {items.map(item => (
              <tr key={item.id} style={{ borderTop: `1px solid ${T.border}` }}>
                {canWrite && (
                  <td style={{ padding: '8px 12px' }}>
                    <input type="checkbox" checked={selected.has(item.id)}
                      onChange={() => toggleSelected(item.id)} />
                  </td>
                )}
                <td style={{ padding: '8px 12px', fontWeight: 600, color: T.ink }}>{item.name}</td>
                <td style={{ padding: '8px 12px', color: T.sub }}>{item.layer}</td>
                <td style={{ padding: '8px 12px', color: T.sub }}>{item.elementType}</td>
                <td style={{ padding: '8px 12px', textAlign: 'right', color: T.sub }}>{item.relCount}</td>
                <td style={{ padding: '8px 12px', textAlign: 'right', whiteSpace: 'nowrap' }}>
                  <button style={{ ..._btn(), padding: '4px 8px', height: 'auto' }}
                    onClick={() => onView(item.id)}>Voir</button>
                  {canWrite && (
                    <>
                      <button style={{ ..._btn(), padding: '4px 8px', height: 'auto', marginLeft: 6 }}
                        onClick={() => onEdit(item)}>
                        <Ic.Edit s={12} /> Modifier
                      </button>
                      <button style={{ ..._btn('danger'), padding: '4px 8px', height: 'auto', marginLeft: 6 }}
                        onClick={() => onDelete(item, item.relCount)}>
                        <Ic.Close s={12} /> Supprimer
                      </button>
                    </>
                  )}
                </td>
              </tr>
            ))}
            {!loading && items.length === 0 && (
              <tr><td colSpan={canWrite ? 6 : 5} style={{ padding: 20, textAlign: 'center', color: T.muted }}>
                Aucun nœud ne correspond aux filtres.
              </td></tr>
            )}
          </tbody>
        </table>
      </div>

      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', fontSize: 12.5, color: T.sub }}>
        <span>{total} résultat{total === 1 ? '' : 's'}</span>
        <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
          <button style={_btn()} disabled={skip <= 0} onClick={() => setSkip(s => Math.max(0, s - LIMIT))}>
            ← Préc.
          </button>
          <span>Page {page} / {totalPages}</span>
          <button style={_btn()} disabled={skip + LIMIT >= total} onClick={() => setSkip(s => s + LIMIT)}>
            Suiv. →
          </button>
        </div>
      </div>
    </div>
  );
};

// ── OrphanListView (T1-F-04) ─────────────────────────────────────
const OrphanListView = ({ apiFetch, role, onView, refreshKey }) => {
  const LIMIT = 50;
  const [skip, setSkip] = React.useState(0);
  const [items, setItems] = React.useState([]);
  const [total, setTotal] = React.useState(0);
  const [error, setError] = React.useState(null);
  const [retryable, setRetryable] = React.useState(false);

  const load = React.useCallback(() => {
    setError(null);
    explorationApi.fetchOrphans(apiFetch, role, { skip, limit: LIMIT })
      .then(data => { setItems(data.items || []); setTotal(data.total || 0); setRetryable(false); })
      .catch(err => {
        const info = handleApiError(err);
        setError(info.message);
        setRetryable(info.retryable);
        if (info.retryable) _pushToast('error', info.message);
      });
  }, [apiFetch, role, skip]);

  React.useEffect(() => { load(); }, [load, refreshKey]);

  const totalPages = Math.max(1, Math.ceil(total / LIMIT));
  const page = Math.floor(skip / LIMIT) + 1;

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 14 }}>
      <h2 style={{ margin: 0, fontSize: 15, fontWeight: 700, color: T.ink }}>
        Nœuds orphelins (sans relation)
      </h2>

      <ErrorBanner message={error} onRetry={retryable ? load : undefined} />

      <div style={{ border: `1px solid ${T.border}`, borderRadius: T.radiusMd, overflow: 'hidden' }}>
        <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 13 }}>
          <thead>
            <tr style={{ background: T.panel, textAlign: 'left' }}>
              <th style={{ padding: '8px 12px' }}>Nom</th>
              <th style={{ padding: '8px 12px' }}>Layer</th>
              <th style={{ padding: '8px 12px' }}>Type</th>
              <th style={{ padding: '8px 12px' }}>Créé le</th>
              <th style={{ padding: '8px 12px', textAlign: 'right' }}>Actions</th>
            </tr>
          </thead>
          <tbody>
            {items.map(item => (
              <tr key={item.id} style={{ borderTop: `1px solid ${T.border}` }}>
                <td style={{ padding: '8px 12px', fontWeight: 600, color: T.ink }}>{item.name}</td>
                <td style={{ padding: '8px 12px', color: T.sub }}>{item.layer}</td>
                <td style={{ padding: '8px 12px', color: T.sub }}>{item.elementType}</td>
                <td style={{ padding: '8px 12px', color: T.sub }}>{_fmtDate(item.createdAt)}</td>
                <td style={{ padding: '8px 12px', textAlign: 'right' }}>
                  <button style={{ ..._btn(), padding: '4px 8px', height: 'auto' }}
                    onClick={() => onView(item.id)}>Voir</button>
                </td>
              </tr>
            ))}
            {items.length === 0 && (
              <tr><td colSpan={5} style={{ padding: 20, textAlign: 'center', color: T.muted }}>
                Aucun nœud orphelin 🎉
              </td></tr>
            )}
          </tbody>
        </table>
      </div>

      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', fontSize: 12.5, color: T.sub }}>
        <span>{total} résultat{total === 1 ? '' : 's'}</span>
        <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
          <button style={_btn()} disabled={skip <= 0} onClick={() => setSkip(s => Math.max(0, s - LIMIT))}>
            ← Préc.
          </button>
          <span>Page {page} / {totalPages}</span>
          <button style={_btn()} disabled={skip + LIMIT >= total} onClick={() => setSkip(s => s + LIMIT)}>
            Suiv. →
          </button>
        </div>
      </div>
    </div>
  );
};

// ── AuditListView (T4-F-01) ──────────────────────────────────────
const AUDIT_OPERATIONS = ['CREATE', 'UPDATE', 'DELETE', 'DELETE_CASCADE'];
const AUDIT_ENTITY_TYPES = ['NODE', 'RELATION'];

const _auditOpTone = (op) => {
  if (op === 'CREATE') return 'azure';
  if (op === 'DELETE' || op === 'DELETE_CASCADE') return 'danger';
  return 'default';
};

const AuditListView = ({ apiFetch, role, refreshKey, onViewNode }) => {
  const LIMIT = 50;
  const [skip, setSkip] = React.useState(0);
  const [items, setItems] = React.useState([]);
  const [total, setTotal] = React.useState(0);
  const [error, setError] = React.useState(null);
  const [retryable, setRetryable] = React.useState(false);
  const [expanded, setExpanded] = React.useState(null);
  const [filters, setFilters] = React.useState({ operation: '', entityType: '', entityId: '', since: '' });

  const load = React.useCallback(() => {
    setError(null);
    const params = { skip, limit: LIMIT };
    if (filters.operation) params.operation = filters.operation;
    if (filters.entityType) params.entityType = filters.entityType;
    if (filters.entityId) params.entityId = filters.entityId;
    if (filters.since) params.since = new Date(filters.since).toISOString();
    explorationApi.fetchAudit(apiFetch, role, params)
      .then(data => { setItems(data.items || []); setTotal(data.total || 0); setRetryable(false); })
      .catch(err => {
        const info = handleApiError(err);
        setError(info.message);
        setRetryable(info.retryable);
        if (info.retryable) _pushToast('error', info.message);
      });
  }, [apiFetch, role, skip, filters]);

  React.useEffect(() => { load(); }, [load, refreshKey]);
  React.useEffect(() => { setSkip(0); }, [filters]);

  const updateFilter = (key, value) => setFilters(f => ({ ...f, [key]: value }));

  const totalPages = Math.max(1, Math.ceil(total / LIMIT));
  const page = Math.floor(skip / LIMIT) + 1;

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 14 }}>
      <h2 style={{ margin: 0, fontSize: 15, fontWeight: 700, color: T.ink }}>
        Journal d'audit
      </h2>

      <ErrorBanner message={error} onRetry={retryable ? load : undefined} />

      <div style={{ display: 'flex', gap: 12, flexWrap: 'wrap' }}>
        <div>
          <span style={_label}>Opération</span>
          <select style={_ctl} value={filters.operation} onChange={e => updateFilter('operation', e.target.value)}>
            <option value="">Toutes</option>
            {AUDIT_OPERATIONS.map(op => <option key={op} value={op}>{op}</option>)}
          </select>
        </div>
        <div>
          <span style={_label}>Type d'entité</span>
          <select style={_ctl} value={filters.entityType} onChange={e => updateFilter('entityType', e.target.value)}>
            <option value="">Tous</option>
            {AUDIT_ENTITY_TYPES.map(t => <option key={t} value={t}>{t}</option>)}
          </select>
        </div>
        <div>
          <span style={_label}>ID entité</span>
          <input style={_ctl} value={filters.entityId} onChange={e => updateFilter('entityId', e.target.value)}
            placeholder="id exact" />
        </div>
        <div>
          <span style={_label}>Depuis</span>
          <input type="datetime-local" style={_ctl} value={filters.since}
            onChange={e => updateFilter('since', e.target.value)} />
        </div>
      </div>

      <div style={{ border: `1px solid ${T.border}`, borderRadius: T.radiusMd, overflow: 'hidden' }}>
        <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 13 }}>
          <thead>
            <tr style={{ background: T.panel, textAlign: 'left' }}>
              <th style={{ padding: '8px 12px' }}>Date</th>
              <th style={{ padding: '8px 12px' }}>Opération</th>
              <th style={{ padding: '8px 12px' }}>Entité</th>
              <th style={{ padding: '8px 12px' }}>ID</th>
              <th style={{ padding: '8px 12px' }}>Utilisateur</th>
              <th style={{ padding: '8px 12px' }}>IP</th>
              <th style={{ padding: '8px 12px', textAlign: 'right' }}>Détail</th>
            </tr>
          </thead>
          <tbody>
            {items.map(item => (
              <React.Fragment key={item.id}>
                <tr style={{ borderTop: `1px solid ${T.border}` }}>
                  <td style={{ padding: '8px 12px', color: T.sub, whiteSpace: 'nowrap' }}>{_fmtDate(item.timestamp)}</td>
                  <td style={{ padding: '8px 12px' }}><ExpPill tone={_auditOpTone(item.operation)}>{item.operation}</ExpPill></td>
                  <td style={{ padding: '8px 12px', color: T.sub }}>{item.entityType}</td>
                  <td style={{ padding: '8px 12px', fontFamily: 'monospace', fontSize: 12 }}>
                    {item.entityType === 'NODE' && onViewNode ? (
                      <a href="#" onClick={(e) => { e.preventDefault(); onViewNode(item.entityId); }}
                        style={{ color: T.azureInk }}>{item.entityId}</a>
                    ) : item.entityId}
                  </td>
                  <td style={{ padding: '8px 12px', color: T.sub }}>{item.userId || '—'} ({item.userRole || '—'})</td>
                  <td style={{ padding: '8px 12px', color: T.sub }}>{item.ipAddress || '—'}</td>
                  <td style={{ padding: '8px 12px', textAlign: 'right' }}>
                    <button style={{ ..._btn(), padding: '4px 8px', height: 'auto' }}
                      onClick={() => setExpanded(e => e === item.id ? null : item.id)}>
                      {expanded === item.id ? 'Masquer' : 'Voir'}
                    </button>
                  </td>
                </tr>
                {expanded === item.id && (
                  <tr style={{ borderTop: `1px solid ${T.border}` }}>
                    <td colSpan={7} style={{ padding: '8px 12px', background: T.panel }}>
                      <pre style={{ margin: 0, fontSize: 11.5, whiteSpace: 'pre-wrap', wordBreak: 'break-all', color: T.sub }}>
                        {JSON.stringify(item.payload, null, 2)}
                      </pre>
                    </td>
                  </tr>
                )}
              </React.Fragment>
            ))}
            {items.length === 0 && (
              <tr><td colSpan={7} style={{ padding: 20, textAlign: 'center', color: T.muted }}>
                Aucune entrée d'audit
              </td></tr>
            )}
          </tbody>
        </table>
      </div>

      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', fontSize: 12.5, color: T.sub }}>
        <span>{total} résultat{total === 1 ? '' : 's'}</span>
        <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
          <button style={_btn()} disabled={skip <= 0} onClick={() => setSkip(s => Math.max(0, s - LIMIT))}>
            ← Préc.
          </button>
          <span>Page {page} / {totalPages}</span>
          <button style={_btn()} disabled={skip + LIMIT >= total} onClick={() => setSkip(s => s + LIMIT)}>
            Suiv. →
          </button>
        </div>
      </div>
    </div>
  );
};

// ── NodeDetailView (T1-F-02, relations étendues en T2-F-03) ──────
const NodeDetailView = ({
  apiFetch, role, canWrite, nodeId, onEdit, onDelete, onBack, onSelect, refreshKey,
  onAddRelation, onEditRelation, onDeleteRelation,
}) => {
  const [data, setData] = React.useState(null);
  const [error, setError] = React.useState(null);
  const [retryable, setRetryable] = React.useState(false);

  const load = React.useCallback(() => {
    setError(null);
    explorationApi.fetchNode(apiFetch, role, nodeId)
      .then(data => { setData(data); setRetryable(false); })
      .catch(err => {
        const info = handleApiError(err);
        setError(info.message);
        setRetryable(info.retryable);
        _pushToast('error', info.message);
        if (info.status === 404) onBack();
      });
  }, [apiFetch, role, nodeId]);

  React.useEffect(() => { load(); }, [load, refreshKey]);

  if (error) {
    return (
      <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
        <button style={_btn()} onClick={onBack}>← Retour</button>
        <ErrorBanner message={error} onRetry={retryable ? load : undefined} />
      </div>
    );
  }

  if (!data) return <div style={{ color: T.muted, fontSize: 13 }}>Chargement…</div>;

  const { node, outgoing = [], incoming = [] } = data;
  const relations = [
    ...outgoing.map(r => ({ ...r, direction: 'OUT' })),
    ...incoming.map(r => ({ ...r, direction: 'IN' })),
  ];

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 14 }}>
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
        <div>
          <button style={{ ..._btn(), marginBottom: 8 }} onClick={onBack}>← Retour à la liste</button>
          <h2 style={{ margin: 0, fontSize: 16, fontWeight: 700, color: T.ink }}>{node.name}</h2>
          <div style={{ display: 'flex', gap: 6, marginTop: 6 }}>
            <ExpPill tone="azure">{node.elementType}</ExpPill>
            <ExpPill>{node.layer}</ExpPill>
            {node.aspect && <ExpPill>{node.aspect}</ExpPill>}
          </div>
        </div>
        {canWrite && (
          <div style={{ display: 'flex', gap: 8 }}>
            <button style={_btn()} onClick={() => onEdit(node)}>
              <Ic.Edit s={13} /> Modifier
            </button>
            <button style={_btn('danger')} onClick={() => onDelete(node, outgoing.length + incoming.length)}>
              <Ic.Close s={13} /> Supprimer
            </button>
          </div>
        )}
      </div>

      <div style={{
        border: `1px solid ${T.border}`, borderRadius: T.radiusMd, padding: 16,
        display: 'flex', flexDirection: 'column', gap: 10, fontSize: 13,
      }}>
        <div style={{ color: T.muted, fontSize: 11.5 }}>id&nbsp;&nbsp;{node.id}</div>
        <div><strong>Description</strong><br />{node.description || '—'}</div>
        <div><strong>Tags</strong><br />
          {node.tags && node.tags.length
            ? node.tags.map(t => <ExpPill key={t}>{t}</ExpPill>)
            : '—'}
        </div>
        <div><strong>Stéréotype</strong><br />{node.stereotype || '—'}</div>
        <div style={{ display: 'flex', gap: 24, color: T.sub }}>
          <span>Créé le {_fmtDate(node.createdAt)}</span>
          <span>Modifié le {_fmtDate(node.updatedAt)}</span>
        </div>
      </div>

      <div>
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 8 }}>
          <h3 style={{ margin: 0, fontSize: 14, fontWeight: 700, color: T.ink }}>
            Relations ({relations.length})
          </h3>
          {canWrite && (
            <button style={_btn('primary')} onClick={() => onAddRelation(node)}>
              <Ic.Plus s={13} /> Nouvelle relation
            </button>
          )}
        </div>
        <div style={{ border: `1px solid ${T.border}`, borderRadius: T.radiusMd, overflow: 'hidden' }}>
          <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 13 }}>
            <thead>
              <tr style={{ background: T.panel, textAlign: 'left' }}>
                <th style={{ padding: '8px 12px' }}>Direction</th>
                <th style={{ padding: '8px 12px' }}>Type</th>
                <th style={{ padding: '8px 12px' }}>Nœud lié</th>
                <th style={{ padding: '8px 12px', textAlign: 'right' }}>Actions</th>
              </tr>
            </thead>
            <tbody>
              {relations.map((r, i) => (
                <tr key={r.relId || i} style={{ borderTop: `1px solid ${T.border}` }}>
                  <td style={{ padding: '8px 12px', color: T.sub }}>
                    {r.direction === 'OUT' ? '→ Sortant' : '← Entrant'}
                  </td>
                  <td style={{ padding: '8px 12px' }}>
                    <ExpPill>{r.relType}</ExpPill>
                    {r.relProps?.accessType && <span style={{ marginLeft: 6, fontSize: 11.5, color: T.sub }}>{r.relProps.accessType}</span>}
                  </td>
                  <td style={{ padding: '8px 12px' }}>
                    {r.linkedNode?.name} <span style={{ color: T.muted }}>({r.linkedNode?.elementType})</span>
                  </td>
                  <td style={{ padding: '8px 12px', textAlign: 'right', whiteSpace: 'nowrap' }}>
                    {r.linkedNode?.id && (
                      <button style={{ ..._btn(), padding: '4px 8px', height: 'auto' }}
                        onClick={() => onSelect(r.linkedNode.id)}>Voir</button>
                    )}
                    {canWrite && r.relProps?.id && (
                      <>
                        <button style={{ ..._btn(), padding: '4px 8px', height: 'auto', marginLeft: 6 }}
                          onClick={() => onEditRelation(r.relProps.id)}>
                          <Ic.Edit s={12} /> Modifier
                        </button>
                        <button style={{ ..._btn('danger'), padding: '4px 8px', height: 'auto', marginLeft: 6 }}
                          onClick={() => onDeleteRelation({
                            id: r.relProps.id,
                            relationType: r.relType,
                            sourceName: r.direction === 'OUT' ? node.name : r.linkedNode?.name,
                            targetName: r.direction === 'OUT' ? r.linkedNode?.name : node.name,
                          })}>
                          <Ic.Close s={12} /> Supprimer
                        </button>
                      </>
                    )}
                  </td>
                </tr>
              ))}
              {relations.length === 0 && (
                <tr><td colSpan={4} style={{ padding: 20, textAlign: 'center', color: T.muted }}>
                  Ce nœud n'a aucune relation.
                </td></tr>
              )}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
};

// ── NodeFormView (T1-F-03) ────────────────────────────────────────
const NodeFormView = ({ apiFetch, role, mode, node, onSaved, onCancel }) => {
  const isEdit = mode === 'edit';

  const [layer, setLayer] = React.useState(node?.layer || '');
  const [elementType, setElementType] = React.useState(node?.elementType || '');
  const [name, setName] = React.useState(node?.name || '');
  const [description, setDescription] = React.useState(node?.description || '');
  const [aspect, setAspect] = React.useState(node?.aspect || '');
  const [tags, setTags] = React.useState((node?.tags || []).join(', '));
  const [stereotype, setStereotype] = React.useState(node?.stereotype || '');
  const [metadata, setMetadata] = React.useState(node?.metadata || '');
  const [saving, setSaving] = React.useState(false);
  const [error, setError] = React.useState(null);

  const elementTypeOptions = layer ? (ARCHIMATE_ELEMENT_TYPES_BY_LAYER[layer] || []) : [];

  const handleLayerChange = (newLayer) => {
    setLayer(newLayer);
    const options = ARCHIMATE_ELEMENT_TYPES_BY_LAYER[newLayer] || [];
    setElementType(options[0] || '');
  };

  const handleSubmit = async (e) => {
    e.preventDefault();
    setError(null);
    setSaving(true);
    try {
      const tagsList = tags.split(',').map(t => t.trim()).filter(Boolean);
      let result;
      if (isEdit) {
        result = await explorationApi.updateNode(apiFetch, role, node.id, {
          name, description: description || null, aspect: aspect || null,
          stereotype: stereotype || null, tags: tagsList, metadata: metadata || null,
        });
      } else {
        result = await explorationApi.createNode(apiFetch, role, {
          layer, elementType, name,
          description: description || undefined,
          aspect: aspect || undefined,
          stereotype: stereotype || undefined,
          tags: tagsList.length ? tagsList : undefined,
          metadata: metadata || undefined,
        });
      }
      _notifyGraphChanged();
      onSaved(result);
    } catch (err) {
      const info = handleApiError(err);
      if (info.status === 403 || info.status === 404) {
        _pushToast('error', info.message);
        if (info.status === 404) _notifyGraphChanged();
        onCancel();
        return;
      }
      setError(info.message);
    } finally {
      setSaving(false);
    }
  };

  return (
    <form onSubmit={handleSubmit} style={{ display: 'flex', flexDirection: 'column', gap: 16, maxWidth: 640 }}>
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
        <h2 style={{ margin: 0, fontSize: 16, fontWeight: 700, color: T.ink }}>
          {isEdit ? `Modifier « ${node.name} »` : 'Nouveau nœud'}
        </h2>
        <button type="button" style={_btn()} onClick={onCancel}>
          <Ic.Close s={13} /> Fermer
        </button>
      </div>

      <ErrorBanner message={error} />

      <div style={{ display: 'flex', gap: 12 }}>
        <div style={{ flex: 1 }}>
          <label style={_label}>Couche *</label>
          <select style={{ ..._ctl, width: '100%' }} value={layer} disabled={isEdit}
            onChange={e => handleLayerChange(e.target.value)} required>
            <option value="">— Sélectionner —</option>
            {ARCHIMATE_LAYERS.map(l => <option key={l} value={l}>{l}</option>)}
          </select>
        </div>
        <div style={{ flex: 1 }}>
          <label style={_label}>Type *</label>
          <select style={{ ..._ctl, width: '100%' }} value={elementType} disabled={isEdit || !layer}
            onChange={e => setElementType(e.target.value)} required>
            <option value="">— Sélectionner —</option>
            {(isEdit ? [node.elementType] : elementTypeOptions).map(t => <option key={t} value={t}>{t}</option>)}
          </select>
        </div>
      </div>

      <div>
        <label style={_label}>Nom * (1-256 caractères)</label>
        <input style={{ ..._ctl, width: '100%' }} value={name} maxLength={256}
          onChange={e => setName(e.target.value)} required />
      </div>

      <div>
        <label style={_label}>Description</label>
        <textarea style={{ ..._ctl, width: '100%', height: 80, padding: 10, fontFamily: T.font, resize: 'vertical' }}
          value={description} onChange={e => setDescription(e.target.value)} />
      </div>

      <div style={{ display: 'flex', gap: 12 }}>
        <div style={{ flex: 1 }}>
          <label style={_label}>Aspect</label>
          <select style={{ ..._ctl, width: '100%' }} value={aspect} onChange={e => setAspect(e.target.value)}>
            <option value="">—</option>
            {ARCHIMATE_ASPECTS.map(a => <option key={a} value={a}>{a}</option>)}
          </select>
        </div>
        <div style={{ flex: 1 }}>
          <label style={_label}>Tags (séparés par ,)</label>
          <input style={{ ..._ctl, width: '100%' }} value={tags} onChange={e => setTags(e.target.value)} />
        </div>
        <div style={{ flex: 1 }}>
          <label style={_label}>Stéréotype</label>
          <input style={{ ..._ctl, width: '100%' }} value={stereotype} onChange={e => setStereotype(e.target.value)} />
        </div>
      </div>

      <div>
        <label style={_label}>Métadonnées (JSON libre, optionnel)</label>
        <textarea style={{ ..._ctl, width: '100%', height: 60, padding: 10, fontFamily: T.mono, fontSize: 12, resize: 'vertical' }}
          value={metadata} onChange={e => setMetadata(e.target.value)} placeholder='{"clé": "valeur"}' />
      </div>

      <div style={{ display: 'flex', justifyContent: 'flex-end', gap: 8 }}>
        <button type="button" style={_btn()} onClick={onCancel}>Annuler</button>
        <button type="submit" style={_btn('primary')} disabled={saving}>
          {saving ? 'Enregistrement…' : (isEdit ? 'Enregistrer' : 'Créer le nœud →')}
        </button>
      </div>
    </form>
  );
};

// ── DeleteConfirmModal (T1-F-05) ──────────────────────────────────
const DeleteConfirmModal = ({ node, relCount, role, onConfirm, onCancel }) => {
  const [cascade, setCascade] = React.useState(false);
  const [deleting, setDeleting] = React.useState(false);
  const [error, setError] = React.useState(null);

  const isAdmin = role === 'ADMIN';
  const blocked = relCount > 0 && !(cascade && isAdmin);

  const handleConfirm = async () => {
    setDeleting(true);
    setError(null);
    try {
      await onConfirm(cascade && isAdmin);
    } catch (err) {
      setError(err.body?.error || err.message);
      setDeleting(false);
    }
  };

  return (
    <div style={{
      position: 'fixed', inset: 0, background: 'rgba(28,27,24,0.35)',
      display: 'flex', alignItems: 'center', justifyContent: 'center', zIndex: 1000,
    }}>
      <div style={{
        background: T.white, borderRadius: T.radiusMd, padding: 24,
        width: 420, display: 'flex', flexDirection: 'column', gap: 14,
        fontFamily: T.font,
      }}>
        <h3 style={{ margin: 0, fontSize: 15, fontWeight: 700, color: T.ink }}>
          <Ic.Close s={14} /> Supprimer le nœud
        </h3>

        <div style={{ fontSize: 13 }}>
          Vous allez supprimer : <strong>« {node.name} »</strong><br />
          <span style={{ color: T.sub }}>{node.elementType} · {node.layer}</span>
        </div>

        {relCount > 0 && (
          <div style={{
            padding: '8px 12px', borderRadius: T.radiusSm, fontSize: 12.5,
            background: '#fff7e6', color: '#a15c00', border: '1px solid #ffe1a8',
          }}>
            ⚠ Ce nœud possède {relCount} relation{relCount === 1 ? '' : 's'} active{relCount === 1 ? '' : 's'}.
          </div>
        )}

        {relCount > 0 && (
          isAdmin ? (
            <label style={{ display: 'flex', alignItems: 'flex-start', gap: 8, fontSize: 12.5, color: T.sub }}>
              <input type="checkbox" checked={cascade} onChange={e => setCascade(e.target.checked)} style={{ marginTop: 2 }} />
              <span>
                Supprimer aussi les {relCount} relation{relCount === 1 ? '' : 's'} (cascade)<br />
                <em>Irréversible — non restaurable.</em>
              </span>
            </label>
          ) : (
            <div style={{ fontSize: 12.5, color: T.muted }}>
              Suppression impossible : ce nœud a des relations. La suppression en cascade requiert le rôle Administrateur.
            </div>
          )
        )}

        <ErrorBanner message={error} />

        <div style={{ fontSize: 12, color: T.muted }}>Cette action est définitive.</div>

        <div style={{ display: 'flex', justifyContent: 'flex-end', gap: 8 }}>
          <button style={_btn()} onClick={onCancel} disabled={deleting}>Annuler</button>
          <button style={_btn('danger')} onClick={handleConfirm} disabled={deleting || blocked}>
            {deleting ? 'Suppression…' : 'Confirmer la suppression'}
          </button>
        </div>
      </div>
    </div>
  );
};

// ── RelListView (T2-F-01) ─────────────────────────────────────────
const RelListView = ({ apiFetch, role, canWrite, onViewNode, onEdit, onDelete, onCreate, refreshKey }) => {
  const LIMIT = 50;
  const [filters, setFilters] = React.useState({ relationType: '', sourceLayer: '', targetLayer: '' });
  const [skip, setSkip] = React.useState(0);
  const [items, setItems] = React.useState([]);
  const [total, setTotal] = React.useState(0);
  const [loading, setLoading] = React.useState(false);
  const [error, setError] = React.useState(null);
  const [retryable, setRetryable] = React.useState(false);

  const updateFilter = (patch) => {
    setSkip(0);
    setFilters(f => ({ ...f, ...patch }));
  };

  const load = React.useCallback(() => {
    setLoading(true);
    setError(null);
    explorationApi.fetchRelations(apiFetch, role, {
      relationType: filters.relationType || undefined,
      sourceLayer: filters.sourceLayer || undefined,
      targetLayer: filters.targetLayer || undefined,
      skip, limit: LIMIT,
    })
      .then(data => { setItems(data.items || []); setTotal(data.total || 0); setRetryable(false); })
      .catch(err => {
        const info = handleApiError(err);
        setError(info.message);
        setRetryable(info.retryable);
        if (info.retryable) _pushToast('error', info.message);
      })
      .finally(() => setLoading(false));
  }, [apiFetch, role, filters, skip]);

  React.useEffect(() => { load(); }, [load, refreshKey]);

  const totalPages = Math.max(1, Math.ceil(total / LIMIT));
  const page = Math.floor(skip / LIMIT) + 1;

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 14 }}>
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
        <h2 style={{ margin: 0, fontSize: 15, fontWeight: 700, color: T.ink }}>Relations</h2>
        {canWrite && (
          <button style={_btn('primary')} onClick={() => onCreate()}>
            <Ic.Plus s={14} /> Nouvelle relation
          </button>
        )}
      </div>

      <div style={{ display: 'flex', flexWrap: 'wrap', gap: 8, alignItems: 'center' }}>
        <select style={_ctl} value={filters.relationType}
          onChange={e => updateFilter({ relationType: e.target.value })}>
          <option value="">Tous les types</option>
          {ARCHIMATE_RELATION_TYPES.map(t => <option key={t} value={t}>{t}</option>)}
        </select>

        <select style={_ctl} value={filters.sourceLayer}
          onChange={e => updateFilter({ sourceLayer: e.target.value })}>
          <option value="">Couche source : toutes</option>
          {ARCHIMATE_LAYERS.map(l => <option key={l} value={l}>{l}</option>)}
        </select>

        <select style={_ctl} value={filters.targetLayer}
          onChange={e => updateFilter({ targetLayer: e.target.value })}>
          <option value="">Couche cible : toutes</option>
          {ARCHIMATE_LAYERS.map(l => <option key={l} value={l}>{l}</option>)}
        </select>

        {(filters.relationType || filters.sourceLayer || filters.targetLayer) && (
          <button style={_btn()} onClick={() => updateFilter({ relationType: '', sourceLayer: '', targetLayer: '' })}>
            <Ic.Close s={12} /> Effacer les filtres
          </button>
        )}

        <button style={_btn()} onClick={load} title="Rafraîchir">
          <Ic.Refresh s={14} />
        </button>
      </div>

      <ErrorBanner message={error} onRetry={retryable ? load : undefined} />

      <div style={{ border: `1px solid ${T.border}`, borderRadius: T.radiusMd, overflow: 'hidden' }}>
        <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 13 }}>
          <thead>
            <tr style={{ background: T.panel, textAlign: 'left' }}>
              <th style={{ padding: '8px 12px' }}>Type</th>
              <th style={{ padding: '8px 12px' }}>Source</th>
              <th style={{ padding: '8px 12px' }}>Cible</th>
              <th style={{ padding: '8px 12px' }}>Détails</th>
              <th style={{ padding: '8px 12px', textAlign: 'right' }}>Actions</th>
            </tr>
          </thead>
          <tbody>
            {items.map(item => (
              <tr key={item.id} style={{ borderTop: `1px solid ${T.border}` }}>
                <td style={{ padding: '8px 12px' }}><ExpPill tone="azure">{item.relationType}</ExpPill></td>
                <td style={{ padding: '8px 12px' }}>
                  <button style={{ ..._btn(), padding: '2px 6px', height: 'auto' }}
                    onClick={() => onViewNode(item.source.id)}>{item.source.name}</button>
                  <div style={{ fontSize: 11, color: T.muted }}>{item.source.layer}</div>
                </td>
                <td style={{ padding: '8px 12px' }}>
                  <button style={{ ..._btn(), padding: '2px 6px', height: 'auto' }}
                    onClick={() => onViewNode(item.target.id)}>{item.target.name}</button>
                  <div style={{ fontSize: 11, color: T.muted }}>{item.target.layer}</div>
                </td>
                <td style={{ padding: '8px 12px', color: T.sub }}>
                  {item.accessType && <ExpPill>{item.accessType}</ExpPill>}
                  {item.weight != null && <span style={{ marginLeft: 6 }}>poids {item.weight}</span>}
                  {item.name && <div>{item.name}</div>}
                </td>
                <td style={{ padding: '8px 12px', textAlign: 'right', whiteSpace: 'nowrap' }}>
                  {canWrite && (
                    <>
                      <button style={{ ..._btn(), padding: '4px 8px', height: 'auto' }}
                        onClick={() => onEdit(item.id)}>
                        <Ic.Edit s={12} /> Modifier
                      </button>
                      <button style={{ ..._btn('danger'), padding: '4px 8px', height: 'auto', marginLeft: 6 }}
                        onClick={() => onDelete({
                          id: item.id, relationType: item.relationType,
                          sourceName: item.source.name, targetName: item.target.name,
                        })}>
                        <Ic.Close s={12} /> Supprimer
                      </button>
                    </>
                  )}
                </td>
              </tr>
            ))}
            {!loading && items.length === 0 && (
              <tr><td colSpan={5} style={{ padding: 20, textAlign: 'center', color: T.muted }}>
                Aucune relation ne correspond aux filtres.
              </td></tr>
            )}
          </tbody>
        </table>
      </div>

      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', fontSize: 12.5, color: T.sub }}>
        <span>{total} résultat{total === 1 ? '' : 's'}</span>
        <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
          <button style={_btn()} disabled={skip <= 0} onClick={() => setSkip(s => Math.max(0, s - LIMIT))}>
            ← Préc.
          </button>
          <span>Page {page} / {totalPages}</span>
          <button style={_btn()} disabled={skip + LIMIT >= total} onClick={() => setSkip(s => s + LIMIT)}>
            Suiv. →
          </button>
        </div>
      </div>
    </div>
  );
};

// ── RelFormView (T2-F-02) ─────────────────────────────────────────
const RelFormView = ({ apiFetch, role, mode, relId, initialSourceId, onSaved, onCancel }) => {
  const isEdit = mode === 'edit';

  const [loading, setLoading] = React.useState(isEdit);
  const [nodeOptions, setNodeOptions] = React.useState([]);
  const [relationType, setRelationType] = React.useState('');
  const [sourceId, setSourceId] = React.useState(initialSourceId || '');
  const [targetId, setTargetId] = React.useState('');
  const [sourceInfo, setSourceInfo] = React.useState(null);
  const [targetInfo, setTargetInfo] = React.useState(null);
  const [accessType, setAccessType] = React.useState('');
  const [weight, setWeight] = React.useState('');
  const [name, setName] = React.useState('');
  const [description, setDescription] = React.useState('');
  const [warnings, setWarnings] = React.useState([]);
  const [confirmWarnings, setConfirmWarnings] = React.useState(false);
  const [saving, setSaving] = React.useState(false);
  const [error, setError] = React.useState(null);

  React.useEffect(() => {
    if (isEdit) return;
    explorationApi.fetchNodes(apiFetch, role, { limit: 200 })
      .then(data => setNodeOptions(data.items || []))
      .catch(() => {});
  }, [apiFetch, role, isEdit]);

  React.useEffect(() => {
    if (!isEdit) return;
    let cancelled = false;
    explorationApi.fetchRelation(apiFetch, role, relId)
      .then(data => {
        if (cancelled) return;
        setRelationType(data.relationType);
        setSourceInfo(data.source);
        setTargetInfo(data.target);
        setAccessType(data.accessType || '');
        setWeight(data.weight != null ? String(data.weight) : '');
        setName(data.name || '');
        setDescription(data.description || '');
      })
      .catch(err => {
        const info = handleApiError(err);
        setError(info.message);
        _pushToast('error', info.message);
        if (info.status === 404) onCancel();
      })
      .finally(() => { if (!cancelled) setLoading(false); });
    return () => { cancelled = true; };
  }, [isEdit, relId, apiFetch, role]);

  if (loading) return <div style={{ color: T.muted, fontSize: 13 }}>Chargement…</div>;

  const handleSubmit = async (e) => {
    e.preventDefault();
    setError(null);
    setSaving(true);
    try {
      let weightValue;
      if (weight !== '') {
        const parsed = parseFloat(weight);
        if (!Number.isNaN(parsed)) weightValue = parsed;
      }

      if (isEdit) {
        const payload = {
          name: name || null,
          description: description || null,
          weight: weightValue !== undefined ? weightValue : null,
        };
        if (relationType === 'Access') payload.accessType = accessType || null;
        const result = await explorationApi.updateRelation(apiFetch, role, relId, payload);
        _notifyGraphChanged();
        onSaved(result);
      } else {
        const payload = {
          relationType, sourceId, targetId,
          name: name || undefined,
          description: description || undefined,
          confirmWarnings,
        };
        if (relationType === 'Access') payload.accessType = accessType || undefined;
        if (weightValue !== undefined) payload.weight = weightValue;
        const result = await explorationApi.createRelation(apiFetch, role, payload);
        _notifyGraphChanged();
        onSaved(result);
      }
    } catch (err) {
      if (err.status === 422 && err.body?.code === 'ARCHIMATE_WARN') {
        setWarnings(err.body.warnings || []);
      } else {
        const info = handleApiError(err);
        if (info.status === 403 || info.status === 404) {
          _pushToast('error', info.message);
          if (info.status === 404) _notifyGraphChanged();
          onCancel();
          return;
        }
        setError(info.message);
      }
    } finally {
      setSaving(false);
    }
  };

  const submitBlocked = !isEdit && warnings.length > 0 && !confirmWarnings;

  return (
    <form onSubmit={handleSubmit} style={{ display: 'flex', flexDirection: 'column', gap: 16, maxWidth: 640 }}>
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
        <h2 style={{ margin: 0, fontSize: 16, fontWeight: 700, color: T.ink }}>
          {isEdit ? 'Modifier la relation' : 'Nouvelle relation'}
        </h2>
        <button type="button" style={_btn()} onClick={onCancel}>
          <Ic.Close s={13} /> Fermer
        </button>
      </div>

      <ErrorBanner message={error} />

      {isEdit ? (
        <div style={{ display: 'flex', alignItems: 'center', gap: 10, fontSize: 13 }}>
          <ExpPill tone="azure">{relationType}</ExpPill>
          <span>{sourceInfo?.name}</span>
          <span style={{ color: T.muted }}>→</span>
          <span>{targetInfo?.name}</span>
        </div>
      ) : (
        <>
          <div>
            <label style={_label}>Type de relation *</label>
            <select style={{ ..._ctl, width: '100%' }} value={relationType}
              onChange={e => { setRelationType(e.target.value); setWarnings([]); setConfirmWarnings(false); }} required>
              <option value="">— Sélectionner —</option>
              {ARCHIMATE_RELATION_TYPES.map(t => <option key={t} value={t}>{t}</option>)}
            </select>
          </div>

          <div style={{ display: 'flex', gap: 12 }}>
            <div style={{ flex: 1 }}>
              <label style={_label}>Source *</label>
              <select style={{ ..._ctl, width: '100%' }} value={sourceId}
                onChange={e => { setSourceId(e.target.value); setWarnings([]); setConfirmWarnings(false); }} required>
                <option value="">— Sélectionner —</option>
                {nodeOptions.map(n => (
                  <option key={n.id} value={n.id}>{n.name} ({n.elementType}, {n.layer})</option>
                ))}
              </select>
            </div>
            <div style={{ flex: 1 }}>
              <label style={_label}>Cible *</label>
              <select style={{ ..._ctl, width: '100%' }} value={targetId}
                onChange={e => { setTargetId(e.target.value); setWarnings([]); setConfirmWarnings(false); }} required>
                <option value="">— Sélectionner —</option>
                {nodeOptions.map(n => (
                  <option key={n.id} value={n.id}>{n.name} ({n.elementType}, {n.layer})</option>
                ))}
              </select>
            </div>
          </div>
        </>
      )}

      {relationType === 'Access' && (
        <div>
          <label style={_label}>Type d'accès *</label>
          <select style={{ ..._ctl, width: '100%' }} value={accessType}
            onChange={e => setAccessType(e.target.value)} required>
            <option value="">— Sélectionner —</option>
            {ARCHIMATE_ACCESS_TYPES.map(a => <option key={a} value={a}>{a}</option>)}
          </select>
        </div>
      )}

      <div style={{ display: 'flex', gap: 12 }}>
        <div style={{ flex: 1 }}>
          <label style={_label}>Nom</label>
          <input style={{ ..._ctl, width: '100%' }} value={name} onChange={e => setName(e.target.value)} />
        </div>
        <div style={{ flex: 1 }}>
          <label style={_label}>Poids (0.0 - 1.0)</label>
          <input style={{ ..._ctl, width: '100%' }} type="number" step="0.1" min="0" max="1"
            value={weight} onChange={e => setWeight(e.target.value)} />
        </div>
      </div>

      <div>
        <label style={_label}>Description</label>
        <textarea style={{ ..._ctl, width: '100%', height: 80, padding: 10, fontFamily: T.font, resize: 'vertical' }}
          value={description} onChange={e => setDescription(e.target.value)} />
      </div>

      {warnings.length > 0 && (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
          {warnings.map((w, i) => (
            <div key={i} style={{
              padding: '8px 12px', borderRadius: T.radiusSm, fontSize: 12.5,
              background: w.level === 'INFO' ? '#eaf3fb' : '#fff7e6',
              color: w.level === 'INFO' ? '#1c5d8a' : '#a15c00',
              border: `1px solid ${w.level === 'INFO' ? '#bcdcf2' : '#ffe1a8'}`,
              display: 'flex', alignItems: 'center', gap: 8,
            }}>
              <ExpPill>{w.code}</ExpPill> {w.message}
            </div>
          ))}
          <label style={{ display: 'flex', alignItems: 'center', gap: 8, fontSize: 12.5, color: T.sub }}>
            <input type="checkbox" checked={confirmWarnings} onChange={e => setConfirmWarnings(e.target.checked)} />
            Créer quand même malgré les avertissements
          </label>
        </div>
      )}

      <div style={{ display: 'flex', justifyContent: 'flex-end', gap: 8 }}>
        <button type="button" style={_btn()} onClick={onCancel}>Annuler</button>
        <button type="submit" style={_btn('primary')} disabled={saving || submitBlocked}>
          {saving ? 'Enregistrement…' : (isEdit ? 'Enregistrer' : 'Créer la relation →')}
        </button>
      </div>
    </form>
  );
};

// ── DeleteRelationConfirmModal (T2-F-03) ──────────────────────────
const DeleteRelationConfirmModal = ({ rel, onConfirm, onCancel }) => {
  const [deleting, setDeleting] = React.useState(false);
  const [error, setError] = React.useState(null);

  const handleConfirm = async () => {
    setDeleting(true);
    setError(null);
    try {
      await onConfirm();
    } catch (err) {
      setError(err.body?.error || err.message);
      setDeleting(false);
    }
  };

  return (
    <div style={{
      position: 'fixed', inset: 0, background: 'rgba(28,27,24,0.35)',
      display: 'flex', alignItems: 'center', justifyContent: 'center', zIndex: 1000,
    }}>
      <div style={{
        background: T.white, borderRadius: T.radiusMd, padding: 24,
        width: 420, display: 'flex', flexDirection: 'column', gap: 14,
        fontFamily: T.font,
      }}>
        <h3 style={{ margin: 0, fontSize: 15, fontWeight: 700, color: T.ink }}>
          <Ic.Close s={14} /> Supprimer la relation
        </h3>

        <div style={{ fontSize: 13 }}>
          <ExpPill tone="azure">{rel.relationType}</ExpPill>
          <div style={{ marginTop: 8 }}>
            <strong>{rel.sourceName}</strong> <span style={{ color: T.muted }}>→</span> <strong>{rel.targetName}</strong>
          </div>
        </div>

        <ErrorBanner message={error} />

        <div style={{ fontSize: 12, color: T.muted }}>Cette action est définitive.</div>

        <div style={{ display: 'flex', justifyContent: 'flex-end', gap: 8 }}>
          <button style={_btn()} onClick={onCancel} disabled={deleting}>Annuler</button>
          <button style={_btn('danger')} onClick={handleConfirm} disabled={deleting}>
            {deleting ? 'Suppression…' : 'Confirmer la suppression'}
          </button>
        </div>
      </div>
    </div>
  );
};

// ── ExplorationPage ────────────────────────────────────────────────
const ExplorationPage = ({ apiFetch }) => {
  const [role, setRole] = useCurrentRole();
  const [section, setSection] = React.useState('nodes'); // 'nodes' | 'orphans' | 'relations'
  const [view, setView] = React.useState({ mode: 'list' });
  const [refreshKey, setRefreshKey] = React.useState(0);
  const [deleteTarget, setDeleteTarget] = React.useState(null); // { node, relCount }
  const [deleteRelTarget, setDeleteRelTarget] = React.useState(null); // { id, relationType, sourceName, targetName }

  const canWrite = role === 'ARCHITECT' || role === 'ADMIN';

  React.useEffect(() => {
    if (section === 'audit' && role !== 'ADMIN') {
      setSection('nodes');
      setView({ mode: 'list' });
    }
  }, [role, section]);

  const [toasts, setToasts] = React.useState([]);
  React.useEffect(() => {
    const onToast = (e) => {
      const id = Date.now() + Math.random();
      setToasts(ts => [...ts, { id, ...e.detail }]);
      setTimeout(() => setToasts(ts => ts.filter(t => t.id !== id)), 6000);
    };
    window.addEventListener('adgm:toast', onToast);
    return () => window.removeEventListener('adgm:toast', onToast);
  }, []);
  const dismissToast = (id) => setToasts(ts => ts.filter(t => t.id !== id));

  const goToSection = (s) => { setSection(s); setView({ mode: 'list' }); };
  const goToList = () => setView({ mode: 'list' });
  const goToDetail = (id) => setView({ mode: 'detail', id });
  const goToCreate = () => setView({ mode: 'create' });
  const goToEdit = (node) => setView({ mode: 'edit', node });

  const goToCreateRelation = (sourceNode, returnTo) => setView({
    mode: 'rel-create', initialSourceId: sourceNode?.id, returnTo: returnTo || view,
  });
  const goToEditRelation = (relId, returnTo) => setView({
    mode: 'rel-edit', relId, returnTo: returnTo || view,
  });

  const handleSaved = (savedNode) => {
    setRefreshKey(k => k + 1);
    setView({ mode: 'detail', id: savedNode.id });
  };

  const handleRelationSaved = () => {
    setRefreshKey(k => k + 1);
    setView(view.returnTo || { mode: 'list' });
  };

  const handleRelationCancel = () => {
    setView(view.returnTo || { mode: 'list' });
  };

  const handleDeleteConfirm = async (cascade) => {
    try {
      await explorationApi.deleteNode(apiFetch, role, deleteTarget.node.id, cascade);
      _notifyGraphChanged();
      setRefreshKey(k => k + 1);
      setDeleteTarget(null);
      setView({ mode: 'list' });
    } catch (err) {
      const { message, status } = handleApiError(err);
      _pushToast('error', message);
      setDeleteTarget(null);
      if (status === 404) {
        setRefreshKey(k => k + 1);
        setView({ mode: 'list' });
      }
    }
  };

  const handleDeleteRelationConfirm = async () => {
    try {
      await explorationApi.deleteRelation(apiFetch, role, deleteRelTarget.id);
      _notifyGraphChanged();
      setRefreshKey(k => k + 1);
      setDeleteRelTarget(null);
    } catch (err) {
      const { message, status } = handleApiError(err);
      _pushToast('error', message);
      setDeleteRelTarget(null);
      if (status === 404) setRefreshKey(k => k + 1);
    }
  };

  const navBtn = (key, label) => (
    <button
      onClick={() => goToSection(key)}
      style={{
        ..._ctl, width: '100%', textAlign: 'left', cursor: 'pointer',
        background: section === key ? T.azureSoft : T.white,
        color: section === key ? T.azureInk : T.ink,
        border: `1px solid ${section === key ? T.azureBorder : T.border}`,
        fontWeight: section === key ? 700 : 500,
      }}
    >
      {label}
    </button>
  );

  return (
    <div style={{
      flex: 1, display: 'flex', flexDirection: 'column', gap: 16,
      overflow: 'auto', padding: 24, fontFamily: T.font,
    }}>
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
        <div>
          <h1 style={{ margin: 0, fontSize: 18, fontWeight: 700, color: T.ink }}>
            Exploration ArchiMate
          </h1>
          <p style={{ margin: '4px 0 0', fontSize: 13, color: T.sub }}>
            CRUD du graphe ArchiMate 3.x (nœuds, relations, audit).
          </p>
        </div>
        <RoleSelector role={role} onChange={setRole} />
      </div>

      <HealthBanner apiFetch={apiFetch} role={role} />

      <div style={{ flex: 1, display: 'flex', gap: 20, overflow: 'hidden' }}>
        <div style={{ width: 180, display: 'flex', flexDirection: 'column', gap: 8 }}>
          {navBtn('nodes', '📋 Nœuds')}
          {navBtn('relations', '🔗 Relations')}
          {navBtn('orphans', '⚠ Orphelins')}
          {role === 'ADMIN' && navBtn('audit', '🕓 Audit')}
        </div>

        <div style={{ flex: 1, overflow: 'auto' }}>
          {view.mode === 'create' && (
            <NodeFormView apiFetch={apiFetch} role={role} mode="create"
              onSaved={handleSaved} onCancel={() => setView({ mode: 'list' })} />
          )}

          {view.mode === 'edit' && (
            <NodeFormView apiFetch={apiFetch} role={role} mode="edit" node={view.node}
              onSaved={handleSaved} onCancel={() => setView({ mode: 'detail', id: view.node.id })} />
          )}

          {view.mode === 'detail' && (
            <NodeDetailView apiFetch={apiFetch} role={role} canWrite={canWrite} nodeId={view.id}
              refreshKey={refreshKey}
              onEdit={goToEdit}
              onDelete={(node, relCount) => setDeleteTarget({ node, relCount })}
              onBack={goToList}
              onSelect={goToDetail}
              onAddRelation={(node) => goToCreateRelation(node, { mode: 'detail', id: view.id })}
              onEditRelation={(relId) => goToEditRelation(relId, { mode: 'detail', id: view.id })}
              onDeleteRelation={(rel) => setDeleteRelTarget(rel)}
            />
          )}

          {view.mode === 'rel-create' && (
            <RelFormView apiFetch={apiFetch} role={role} mode="create" initialSourceId={view.initialSourceId}
              onSaved={handleRelationSaved} onCancel={handleRelationCancel} />
          )}

          {view.mode === 'rel-edit' && (
            <RelFormView apiFetch={apiFetch} role={role} mode="edit" relId={view.relId}
              onSaved={handleRelationSaved} onCancel={handleRelationCancel} />
          )}

          {view.mode === 'list' && section === 'nodes' && (
            <NodeListView apiFetch={apiFetch} role={role} canWrite={canWrite} refreshKey={refreshKey}
              onView={goToDetail}
              onEdit={goToEdit}
              onDelete={(node, relCount) => setDeleteTarget({ node, relCount })}
              onCreate={goToCreate}
            />
          )}

          {view.mode === 'list' && section === 'relations' && (
            <RelListView apiFetch={apiFetch} role={role} canWrite={canWrite} refreshKey={refreshKey}
              onViewNode={goToDetail}
              onEdit={(relId) => goToEditRelation(relId, { mode: 'list' })}
              onDelete={(rel) => setDeleteRelTarget(rel)}
              onCreate={() => goToCreateRelation(null, { mode: 'list' })}
            />
          )}

          {view.mode === 'list' && section === 'orphans' && (
            <OrphanListView apiFetch={apiFetch} role={role} refreshKey={refreshKey} onView={goToDetail} />
          )}

          {view.mode === 'list' && section === 'audit' && role === 'ADMIN' && (
            <AuditListView apiFetch={apiFetch} role={role} refreshKey={refreshKey} onViewNode={goToDetail} />
          )}
        </div>
      </div>

      {deleteTarget && (
        <DeleteConfirmModal
          node={deleteTarget.node}
          relCount={deleteTarget.relCount || 0}
          role={role}
          onConfirm={handleDeleteConfirm}
          onCancel={() => setDeleteTarget(null)}
        />
      )}

      {deleteRelTarget && (
        <DeleteRelationConfirmModal
          rel={deleteRelTarget}
          onConfirm={handleDeleteRelationConfirm}
          onCancel={() => setDeleteRelTarget(null)}
        />
      )}

      <ToastStack toasts={toasts} onDismiss={dismissToast} />
    </div>
  );
};

Object.assign(window, { ExplorationPage });
