// src/LegacyKbPage.jsx — Vue "Legacy KB" : exploration du graphe GraphRAG brut (neo4j-legacykb)
// Props: apiFetch(url, options) — wrapper _apiFetch (injecte X-API-Key), fourni par App
//
// Lecture seule, via api/routers/legacykb.py (connexion directe à l'instance Neo4j
// neo4j-legacykb, distincte du graphe ADG-M, retiré). Recherche par nom/titre, puis
// exploration progressive du voisinage par double-clic. Rendu avec React Flow (xyflow,
// window.ReactFlow) + dagre (window.dagre) pour le layout.

const API_BASE = window.location.origin + '/api';

const {
  ReactFlow: ReactFlowCanvas,
  ReactFlowProvider,
  Background,
  Controls,
  Handle,
  Position,
  MarkerType,
  useReactFlow,
} = window.ReactFlow;

// ── Couleurs/formes par type d'entité et niveau de communauté ─────────────────
const ENTITY_COLORS = {
  Program:        '#1565c0',
  BatchJob:       '#8d6e63',
  Copybook:       '#7b1fa2',
  GenericFile:    '#26a69a',
  'External/Doc': '#9e9e9e',
};
const COMMUNITY_COLORS = { 1: '#ffb74d', 2: '#fb8c00' };

const ENTITY_TYPE_LABELS = {
  Program:        'Programme',
  BatchJob:       'Job batch',
  Copybook:       'Copybook',
  GenericFile:    'Fichier',
  'External/Doc': 'Référence externe',
};

const NODE_W = 220;
const NODE_H = 44;

// ── Nœud custom — entité (pastille ronde) ou communauté (pastille carrée) ─────
const LegacyNode = ({ data }) => {
  const isEntity = data.kind === 'entity';
  const color = isEntity
    ? (ENTITY_COLORS[data.type] ?? '#9e9e9e')
    : (COMMUNITY_COLORS[data.level] ?? '#bdbdbd');

  return (
    <div style={{
      display: 'flex', alignItems: 'center', gap: 8,
      width: NODE_W, height: NODE_H, padding: '0 12px', boxSizing: 'border-box',
      borderRadius: isEntity ? 999 : 8,
      border: data.isCenter ? `2px solid ${T.azure}` : `1px solid ${T.border}`,
      background: T.white,
      fontFamily: T.font, fontSize: 12, fontWeight: 600, color: T.ink,
      boxShadow: '0 1px 2px rgba(0,0,0,0.06)',
    }}>
      <Handle type="target" position={Position.Left} style={{ background: color, border: 'none', width: 8, height: 8 }} />
      <span style={{
        width: 10, height: 10, borderRadius: isEntity ? '50%' : 2,
        background: color, flexShrink: 0,
      }} />
      <span style={{ overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
        {data.nom}
      </span>
      <Handle type="source" position={Position.Right} style={{ background: color, border: 'none', width: 8, height: 8 }} />
    </div>
  );
};

const NODE_TYPES = { legacyNode: LegacyNode };

// ── Panneau de détail ───────────────────────────────────────────────────────
const NodeDetailPanel = ({ nodeId, apiFetch, onClose }) => {
  const [detail, setDetail] = React.useState(null);
  const [loading, setLoading] = React.useState(true);
  const [error, setError] = React.useState(null);

  React.useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError(null);
    apiFetch(`${API_BASE}/legacykb/nodes/${encodeURIComponent(nodeId)}`)
      .then(r => { if (!r.ok) throw new Error(`HTTP ${r.status}`); return r.json(); })
      .then(data => { if (!cancelled) { setDetail(data); setLoading(false); } })
      .catch(err => { if (!cancelled) { setError(err.message); setLoading(false); } });
    return () => { cancelled = true; };
  }, [nodeId, apiFetch]);

  const Section = ({ title, children }) => (
    <div style={{ marginTop: 14 }}>
      <div style={{ fontSize: 11.5, fontWeight: 700, color: T.muted, textTransform: 'uppercase', letterSpacing: 0.4, marginBottom: 4 }}>
        {title}
      </div>
      <div style={{ fontSize: 12.5, color: T.sub, lineHeight: 1.6, whiteSpace: 'pre-wrap' }}>
        {children}
      </div>
    </div>
  );

  return (
    <div style={{
      width: 360, flexShrink: 0, borderLeft: `1px solid ${T.border}`,
      background: T.white, overflowY: 'auto', padding: 18, fontFamily: T.font,
    }}>
      <div style={{ display: 'flex', alignItems: 'flex-start', justifyContent: 'space-between', gap: 8 }}>
        <div style={{ fontSize: 15, fontWeight: 700, color: T.ink, wordBreak: 'break-word' }}>
          {detail?.nom ?? '…'}
        </div>
        <button
          onClick={onClose}
          style={{ display: 'flex', border: 'none', background: 'transparent', color: T.muted, cursor: 'pointer', padding: 4, borderRadius: T.radiusSm, flexShrink: 0 }}
          title="Fermer"
        >
          <Ic.Close s={14} />
        </button>
      </div>

      {loading && <div style={{ fontSize: 12.5, color: T.muted, marginTop: 10 }}>Chargement…</div>}
      {error && <div style={{ fontSize: 12.5, color: T.danger, marginTop: 10 }}>Erreur : {error}</div>}

      {detail && !loading && (
        <>
          {detail.kind === 'entity' ? (
            <>
              <div style={{ marginTop: 6, display: 'flex', alignItems: 'center', gap: 6 }}>
                <span style={{ width: 10, height: 10, borderRadius: '50%', background: ENTITY_COLORS[detail.type] ?? '#9e9e9e', flexShrink: 0 }} />
                <span style={{ fontSize: 12, color: T.sub }}>{ENTITY_TYPE_LABELS[detail.type] ?? detail.type}</span>
              </div>
              {detail.source && <Section title="Fichier source">{detail.source}</Section>}
              {detail.functional_description && <Section title="Description fonctionnelle">{detail.functional_description}</Section>}
              {detail.technical_description && <Section title="Description technique">{detail.technical_description}</Section>}
            </>
          ) : (
            <>
              <div style={{ marginTop: 6, display: 'flex', alignItems: 'center', gap: 6 }}>
                <span style={{ width: 10, height: 10, borderRadius: '50%', background: COMMUNITY_COLORS[detail.level] ?? '#bdbdbd', flexShrink: 0 }} />
                <span style={{ fontSize: 12, color: T.sub }}>Communauté niveau {detail.level}</span>
              </div>
              {detail.functional_summary && <Section title="Résumé fonctionnel">{detail.functional_summary}</Section>}
              {detail.technical_summary && <Section title="Résumé technique">{detail.technical_summary}</Section>}
            </>
          )}
        </>
      )}
    </div>
  );
};

// ── Calcule un layout dagre (gauche → droite) pour le bundle courant ──────────
const _layout = (bundle, centerId) => {
  if (!bundle) return { nodes: [], edges: [] };

  const visibleIds = new Set(bundle.nodeMap.keys());
  const edgeList = bundle.edgeList.filter(e => visibleIds.has(e.from) && visibleIds.has(e.to));

  const g = new dagre.graphlib.Graph();
  g.setGraph({ rankdir: 'LR', nodesep: 30, ranksep: 90 });
  g.setDefaultEdgeLabel(() => ({}));

  bundle.nodeMap.forEach(n => g.setNode(n.id, { width: NODE_W, height: NODE_H }));
  edgeList.forEach(e => g.setEdge(e.from, e.to));

  dagre.layout(g);

  const nodes = [...bundle.nodeMap.values()].map(n => {
    const pos = g.node(n.id);
    return {
      id: n.id,
      type: 'legacyNode',
      position: { x: pos.x - NODE_W / 2, y: pos.y - NODE_H / 2 },
      data: { ...n, isCenter: n.id === centerId },
    };
  });

  const edges = edgeList.map(e => ({
    id: `${e.from}|${e.to}|${e.type}`,
    source: e.from,
    target: e.to,
    label: e.type,
    type: 'smoothstep',
    markerEnd: { type: MarkerType.ArrowClosed, color: '#cbd5e1' },
    style: { stroke: '#cbd5e1' },
    labelStyle: { fontSize: 10, fill: T.muted },
    labelBgStyle: { fill: T.white, fillOpacity: 0.9 },
  }));

  return { nodes, edges };
};

// ── Canvas React Flow — recadre la vue à chaque mise à jour du graphe ─────────
const LegacyKbCanvas = ({ nodes, edges, onNodeClick, onNodeDoubleClick, onPaneClick }) => {
  const { fitView } = useReactFlow();

  React.useEffect(() => {
    if (!nodes.length) return;
    const id = requestAnimationFrame(() => fitView({ padding: 0.15, duration: 300 }));
    return () => cancelAnimationFrame(id);
  }, [nodes, fitView]);

  return (
    <ReactFlowCanvas
      nodes={nodes}
      edges={edges}
      nodeTypes={NODE_TYPES}
      onNodeClick={onNodeClick}
      onNodeDoubleClick={onNodeDoubleClick}
      onPaneClick={onPaneClick}
      nodesDraggable={false}
      nodesConnectable={false}
      fitView
    >
      <Background color={T.border} gap={20} />
      <Controls showInteractive={false} />
    </ReactFlowCanvas>
  );
};

// ── Page principale ─────────────────────────────────────────────────────────
const LegacyKbPage = ({ apiFetch }) => {
  const apiFetchRef  = React.useRef(apiFetch);
  apiFetchRef.current = apiFetch;

  const [query,        setQuery]        = React.useState('');
  const [searchResults, setSearchResults] = React.useState([]);
  const [searching,    setSearching]    = React.useState(false);
  const [searchError,  setSearchError]  = React.useState(null);

  const [stats,        setStats]        = React.useState(null);
  const [statsError,   setStatsError]   = React.useState(null);

  const [bundle,       setBundle]       = React.useState(null); // { nodeMap: Map, edgeList: [] }
  const [centerId,     setCenterId]     = React.useState(null);
  const [selectedId,   setSelectedId]   = React.useState(null);

  // ── Stats (chargées une fois au montage) ─────────────────────────────────
  React.useEffect(() => {
    apiFetch(`${API_BASE}/legacykb/stats`)
      .then(r => { if (!r.ok) throw new Error(`HTTP ${r.status}`); return r.json(); })
      .then(setStats)
      .catch(err => setStatsError(err.message));
  }, [apiFetch]);

  // ── Recherche ─────────────────────────────────────────────────────────────
  const runSearch = React.useCallback(async () => {
    const q = query.trim();
    if (!q) { setSearchResults([]); return; }
    setSearching(true);
    setSearchError(null);
    try {
      const res = await apiFetch(`${API_BASE}/legacykb/search?q=${encodeURIComponent(q)}&limit=30`);
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const data = await res.json();
      setSearchResults(data.items ?? []);
    } catch (err) {
      setSearchError(err.message);
      setSearchResults([]);
    } finally {
      setSearching(false);
    }
  }, [query, apiFetch]);

  // ── Charge le voisinage d'un nœud et fusionne dans le bundle ──────────────
  const exploreNode = React.useCallback(async (nodeId) => {
    try {
      const res = await apiFetchRef.current(
        `${API_BASE}/legacykb/nodes/${encodeURIComponent(nodeId)}/neighbors`
      );
      if (!res.ok) return;
      const data = await res.json(); // { center, neighbors, edges }

      setBundle(prev => {
        const nodeMap = prev ? new Map(prev.nodeMap) : new Map();
        const edgeList = prev ? [...prev.edgeList] : [];
        const seenKeys = new Set(edgeList.map(e => `${e.from}|${e.to}|${e.type}`));

        nodeMap.set(data.center.id, data.center);
        data.neighbors.forEach(n => nodeMap.set(n.id, n));
        data.edges.forEach(e => {
          const k = `${e.from}|${e.to}|${e.type}`;
          if (!seenKeys.has(k)) { seenKeys.add(k); edgeList.push(e); }
        });
        return { nodeMap, edgeList };
      });
      setCenterId(data.center.id);
      setSelectedId(data.center.id);
    } catch (_) { /* exploration silencieuse si l'API est injoignable */ }
  }, []);

  // ── Sélection d'un résultat de recherche → démarre/étend l'exploration ────
  const handleResultClick = React.useCallback((item) => {
    exploreNode(item.id);
  }, [exploreNode]);

  // ── Réinitialise la vue ────────────────────────────────────────────────
  const clearGraph = React.useCallback(() => {
    setBundle(null);
    setCenterId(null);
    setSelectedId(null);
  }, []);

  // ── Nœuds/arêtes React Flow dérivés du bundle (layout dagre) ──────────────
  const { nodes, edges } = React.useMemo(() => _layout(bundle, centerId), [bundle, centerId]);
  const nodeCount = nodes.length;
  const arcCount = edges.length;

  const handleNodeClick = React.useCallback((_evt, node) => setSelectedId(node.id), []);
  const handleNodeDoubleClick = React.useCallback((_evt, node) => exploreNode(node.id), [exploreNode]);
  const handlePaneClick = React.useCallback(() => setSelectedId(null), []);

  return (
    <div style={{ flex: 1, display: 'flex', flexDirection: 'column', overflow: 'hidden', minWidth: 0 }}>
      {/* TopBar — recherche + stats */}
      <div style={{
        display: 'flex', alignItems: 'center', justifyContent: 'space-between',
        flexWrap: 'wrap', gap: 14, padding: '14px 22px',
        borderBottom: `1px solid ${T.border}`, background: T.white, fontFamily: T.font,
      }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 8, flex: 1, minWidth: 260, maxWidth: 480 }}>
          <div style={{
            flex: 1, display: 'flex', alignItems: 'center', gap: 8,
            height: 36, padding: '0 12px',
            borderRadius: T.radiusPill, border: `1px solid ${T.border}`, background: T.panel,
          }}>
            <Ic.Search s={14} />
            <input
              value={query}
              onChange={e => setQuery(e.target.value)}
              onKeyDown={e => { if (e.key === 'Enter') runSearch(); }}
              placeholder="Rechercher un programme, fichier, communauté…"
              style={{
                flex: 1, border: 'none', outline: 'none', background: 'transparent',
                fontFamily: T.font, fontSize: 13, color: T.ink,
              }}
            />
          </div>
          <button
            onClick={runSearch}
            disabled={searching}
            style={{
              height: 36, padding: '0 16px', borderRadius: T.radiusPill,
              border: 'none', background: T.azure, color: T.white,
              fontFamily: T.font, fontSize: 13, fontWeight: 600,
              cursor: searching ? 'default' : 'pointer', opacity: searching ? 0.6 : 1,
              whiteSpace: 'nowrap',
            }}
          >
            {searching ? 'Recherche…' : 'Rechercher'}
          </button>
        </div>

        <div style={{ display: 'flex', alignItems: 'center', gap: 14, flexWrap: 'wrap' }}>
          {stats && !statsError && (
            <span style={{ fontSize: 12.5, color: T.muted, whiteSpace: 'nowrap' }}>
              {Object.values(stats.entities ?? {}).reduce((a, b) => a + b, 0)} entités ·{' '}
              {Object.values(stats.communities ?? {}).reduce((a, b) => a + b, 0)} communautés
            </span>
          )}
          {bundle && (
            <>
              <span style={{ fontSize: 12.5, color: T.muted, whiteSpace: 'nowrap' }}>
                {nodeCount} nœud{nodeCount > 1 ? 's' : ''} · {arcCount} arc{arcCount > 1 ? 's' : ''}
              </span>
              <button
                onClick={clearGraph}
                style={{
                  height: 32, padding: '0 14px', borderRadius: T.radiusPill,
                  border: `1px solid ${T.border}`, background: T.white, color: T.sub,
                  fontFamily: T.font, fontSize: 12.5, fontWeight: 500, cursor: 'pointer',
                  whiteSpace: 'nowrap',
                }}
              >
                Réinitialiser
              </button>
            </>
          )}
        </div>
      </div>

      {/* Corps : résultats de recherche / canvas / panneau de détail */}
      <div style={{ flex: 1, display: 'flex', overflow: 'hidden', minHeight: 0 }}>
        {/* Résultats de recherche */}
        {searchResults.length > 0 && (
          <div style={{
            width: 280, flexShrink: 0, borderRight: `1px solid ${T.border}`,
            background: T.railBg, overflowY: 'auto', fontFamily: T.font,
          }}>
            {searchResults.map(item => (
              <button
                key={item.id}
                onClick={() => handleResultClick(item)}
                style={{
                  display: 'flex', flexDirection: 'column', gap: 2,
                  width: '100%', textAlign: 'left', padding: '10px 14px',
                  border: 'none', borderBottom: `1px solid ${T.border}`,
                  background: selectedId === item.id ? T.azureSoft : 'transparent',
                  cursor: 'pointer',
                }}
                onMouseEnter={e => { if (selectedId !== item.id) e.currentTarget.style.background = T.panel; }}
                onMouseLeave={e => { if (selectedId !== item.id) e.currentTarget.style.background = 'transparent'; }}
              >
                <span style={{ display: 'flex', alignItems: 'center', gap: 6, fontSize: 12.5, fontWeight: 600, color: T.ink }}>
                  <span style={{
                    width: 9, height: 9, borderRadius: item.kind === 'community' ? 2 : '50%', flexShrink: 0,
                    background: item.kind === 'entity' ? (ENTITY_COLORS[item.type] ?? '#9e9e9e') : (COMMUNITY_COLORS[item.level] ?? '#bdbdbd'),
                  }} />
                  <span style={{ overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{item.nom}</span>
                </span>
                <span style={{ fontSize: 11, color: T.muted }}>
                  {item.kind === 'entity' ? (ENTITY_TYPE_LABELS[item.type] ?? item.type) : `Communauté niveau ${item.level}`}
                </span>
              </button>
            ))}
          </div>
        )}

        {/* Canvas */}
        <div style={{ flex: 1, position: 'relative', background: T.panel, minHeight: 0 }}>
          {bundle ? (
            <ReactFlowProvider>
              <LegacyKbCanvas
                nodes={nodes}
                edges={edges}
                onNodeClick={handleNodeClick}
                onNodeDoubleClick={handleNodeDoubleClick}
                onPaneClick={handlePaneClick}
              />
            </ReactFlowProvider>
          ) : (
            <div style={{
              position: 'absolute', inset: 0, display: 'flex', flexDirection: 'column',
              alignItems: 'center', justifyContent: 'center', gap: 8, padding: 24,
              fontFamily: T.font,
            }}>
              <span style={{ fontSize: 13, color: T.ink, fontWeight: 500 }}>
                Legacy KB — graphe brut GraphRAG
              </span>
              <span style={{ fontSize: 12, color: T.muted, maxWidth: 380, textAlign: 'center', lineHeight: 1.6 }}>
                Recherchez un programme, un fichier ou une communauté, puis cliquez sur un
                résultat pour afficher son voisinage. Double-clic sur un nœud pour étendre
                l'exploration.
              </span>
              {statsError && (
                <span style={{ fontSize: 12, color: T.danger, marginTop: 6 }}>
                  Impossible de charger les statistiques : {statsError}
                </span>
              )}
              {searchError && (
                <span style={{ fontSize: 12, color: T.danger, marginTop: 6 }}>
                  Erreur de recherche : {searchError}
                </span>
              )}
            </div>
          )}
        </div>

        {selectedId && (
          <NodeDetailPanel
            key={selectedId}
            nodeId={selectedId}
            apiFetch={apiFetch}
            onClose={() => setSelectedId(null)}
          />
        )}
      </div>
    </div>
  );
};

Object.assign(window, { LegacyKbPage });
