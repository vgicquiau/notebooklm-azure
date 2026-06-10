// src/GraphPage.jsx — Page de visualisation du graphe ADG-M (4 vues)
// Props: apiFetch(url, options) — wrapper _apiFetch (injecte X-API-Key), fourni par App
//
// Charge nœuds + arcs via le proxy /api/graph/* (api/routers/graph.py → fn-adgm-graph),
// puis les rend avec Cytoscape.js. Le switch de plan filtre les nœuds par subtype.

// ── Couleurs par sous-type de nœud ────────────────────────────────────────────
const STATUS_COLORS = {
  EXISTING:      '#9e9e9e',
  IN_TRANSITION: '#fb8c00',
  TARGET:        '#43a047',
};
const R7_COLORS = {
  RETIRE: '#e53935', RETAIN: '#9e9e9e', REHOST: '#4fc3f7',
  REPLATFORM: '#1e88e5', REPURCHASE: '#8e24aa', REFACTOR: '#fb8c00',
  REBUILD: '#43a047', UNQUALIFIED: '#ffffff',
};
// Couleurs fixes pour les sous-types non-7R
const SUBTYPE_COLORS = {
  domain:       '#1565c0',   // bleu foncé — domaine fonctionnel
  macrofunction:'#64b5f6',   // bleu clair — macro-fonction
  dataentity:   '#7b1fa2',   // violet — entité de données
  component:    '#ffffff',   // blanc — TechnicalNode générique (encode 7R)
  system:       '#2e7d32',   // vert foncé — système
  program:      '#ffffff',   // blanc — programme (encode 7R)
};
// Formes Cytoscape par sous-type — différenciation visuelle sans couleur
const SUBTYPE_SHAPES = {
  domain:       'ellipse',
  macrofunction:'roundrectangle',
  dataentity:   'hexagon',
  program:      'diamond',
  component:    'ellipse',
  system:       'triangle',
};
const SUBTYPE_LABELS = {
  domain:       'Domaine fonctionnel',
  macrofunction:'Macro-fonction',
  dataentity:   'Entité de données',
  program:      'Programme',
  component:    'Composant technique',
  system:       'Système',
};

// ── Layouts par vue ────────────────────────────────────────────────────────────
const TECH_LAYOUT       = { name: 'breadthfirst', directed: true, spacingFactor: 2.8, padding: 80, animate: true };
const FUNCTIONAL_LAYOUT = { name: 'cose', idealEdgeLength: 220, nodeRepulsion: 80000, gravity: 0.2, padding: 80, animate: true };
const DATA_LAYOUT       = { name: 'cose', idealEdgeLength: 180, nodeRepulsion: 60000, gravity: 0.2, padding: 80, animate: true };
const GLOBAL_LAYOUT     = { name: 'cose', idealEdgeLength: 250, nodeRepulsion: 90000, gravity: 0.15, padding: 80, animate: true };

const PLAN_LAYOUTS = {
  functional: FUNCTIONAL_LAYOUT,
  technical:  TECH_LAYOUT,
  data:       DATA_LAYOUT,
  global:     GLOBAL_LAYOUT,
};

// ── Filtrage par vue : quels subtypes sont visibles ───────────────────────────
const PLAN_SUBTYPES = {
  functional: new Set(['domain', 'macrofunction']),
  technical:  new Set(['program', 'component', 'system']),
  data:       new Set(['dataentity']),
  global:     null,  // null = tout afficher
};

const R7_LABELS = {
  RETIRE: 'Retire', RETAIN: 'Retain', REHOST: 'Rehost', REPLATFORM: 'Replatform',
  REPURCHASE: 'Repurchase', REFACTOR: 'Refactor', REBUILD: 'Rebuild', UNQUALIFIED: 'Non qualifié',
};
const STATUS_LABELS = { EXISTING: 'Existant', IN_TRANSITION: 'En transition', TARGET: 'Cible' };

// Feuille de style — la première section porte les styles dérivés (couleur de fond
// par statut/7R, bordure et halo de texte par défaut) ; la seconde est graphStylesheet
// telle que définie dans la SDD §6, VERBATIM (mêmes sélecteurs/couleurs/données). L'ordre
// est important : Cytoscape applique les règles dans l'ordre du tableau (la dernière
// règle qui définit une propriété donnée gagne, indépendamment de la spécificité du
// sélecteur) — les overrides spécifiques de la SDD (SPOF, fantôme, criticité, sélection)
// doivent donc rester APRÈS les styles génériques pour ne pas être écrasés par eux.
const GRAPH_STYLE = [
  { selector: 'node', style: {
      'background-color': 'data(color)',
      'shape': 'data(shape)',
      'border-color': '#e1ded7', 'border-width': 1,
      'color': '#1c1b18', 'text-outline-width': 2, 'text-outline-color': '#ffffff',
  } },
  { selector: 'edge', style: {
      'width': 1.5, 'line-color': '#e1ded7', 'target-arrow-color': '#e1ded7',
      'target-arrow-shape': 'triangle', 'curve-style': 'bezier', 'arrow-scale': 0.8,
  } },
  // ── graphStylesheet — SDD §6, verbatim ──
  { selector: 'node', style: { 'label': 'data(label)', 'font-size': 10, 'text-valign': 'center' } },
  { selector: 'node[?isSPOF]', style: { 'border-width': 3, 'border-color': '#e53935' } },
  { selector: 'node[?isGhost]', style: { 'border-style': 'dashed', 'background-opacity': 0.4 } },
  { selector: "edge[criticality = 'CRITICAL']", style: { 'line-color': '#e53935', 'width': 3 } },
  // ── Halo de cluster (ajout T15 UI, hors SDD — cf. ClusterToggle plus bas) :
  // overlay-* ne touche ni au remplissage (7R/statut) ni à la bordure (réservée
  // au badge isSPOF) — les encodages se superposent sans collision visuelle.
  // `clusterColor` n'existe dans data() que si l'utilisateur active le
  // surlignage des appartements candidats : sélecteur sans effet le reste du temps.
  { selector: 'node[clusterColor]', style: {
      'overlay-color': 'data(clusterColor)', 'overlay-opacity': 0.4, 'overlay-padding': 7,
  } },
  { selector: ':selected', style: { 'overlay-opacity': 0.2 } },
  // Nœuds hors-plan introduits par le mode exploration — dashed + opacité réduite
  { selector: 'node[?isOutOfPlan]', style: { 'border-style': 'dashed', 'border-color': '#94a3b8', 'opacity': 0.75 } },
  // Labels de relation — visibles en mode exploration uniquement sur hover
  { selector: 'edge[relLabel][?showLabel]', style: {
      'label': 'data(relLabel)',
      'font-size': 10, 'text-rotation': 'none',
      'text-background-color': '#1e293b', 'text-background-opacity': 0.9, 'text-background-padding': '3px',
      'text-border-width': 0, 'color': '#f1f5f9',
      'text-halign': 'center', 'text-valign': 'center',
  } },
];

// ── Switch de plan (4 vues) ────────────────────────────────────────────────────
const PLAN_OPTIONS = [
  { key: 'functional', label: 'Fonctionnel', title: 'Domaines fonctionnels et macro-fonctions' },
  { key: 'technical',  label: 'Technique',   title: 'Programmes, systèmes et composants techniques' },
  { key: 'data',       label: 'Données',     title: 'Entités de données et leurs dépendances' },
  { key: 'global',     label: 'Global',      title: 'Vue complète — tous les nœuds et arcs' },
];

const PlanSwitch = ({ plan, onChange }) => (
  <div style={{
    display: 'flex', gap: 2, padding: 3,
    background: T.panel, borderRadius: T.radiusPill, border: `1px solid ${T.border}`,
  }}>
    {PLAN_OPTIONS.map(({ key, label, title }) => {
      const active = plan === key;
      return (
        <button
          key={key}
          onClick={() => onChange(key)}
          title={title}
          style={{
            height: 30, padding: '0 14px',
            borderRadius: T.radiusPill, border: 'none',
            background: active ? T.white : 'transparent',
            color: active ? T.ink : T.muted,
            fontFamily: T.font, fontSize: 13, fontWeight: active ? 700 : 500,
            cursor: 'pointer', transition: 'all .12s', whiteSpace: 'nowrap',
            boxShadow: active ? '0 1px 3px rgba(28,27,24,.1)' : 'none',
          }}
          onMouseEnter={e => { if (!active) e.currentTarget.style.color = T.sub; }}
          onMouseLeave={e => { if (!active) e.currentTarget.style.color = T.muted; }}
        >
          {label}
        </button>
      );
    })}
  </div>
);

// ── Légende — explicite les indices visuels (couleurs, SPOF, fantôme) ───
const Swatch = ({ children, shape }) => (
  <span style={{ display: 'inline-flex', alignItems: 'center', gap: 5, fontSize: 11.5, color: T.sub, whiteSpace: 'nowrap' }}>
    {shape}{children}
  </span>
);
const dot = (bg, extra = {}) => (
  <span style={{ width: 11, height: 11, borderRadius: '50%', flexShrink: 0, background: bg, border: '1px solid #e1ded7', ...extra }} />
);

const Legend = ({ plan }) => {
  const sep = <span style={{ width: 1, height: 14, background: T.border, flexShrink: 0 }} />;
  return (
    <div style={{ display: 'flex', flexWrap: 'wrap', alignItems: 'center', gap: 12, fontFamily: T.font }}>
      {plan === 'functional' && (
        <>
          <Swatch shape={dot(SUBTYPE_COLORS.domain)}       >Domaine fonctionnel</Swatch>
          <Swatch shape={dot(SUBTYPE_COLORS.macrofunction)}>Macro-fonction</Swatch>
        </>
      )}
      {plan === 'technical' && (
        <>
          {Object.keys(R7_COLORS).map(k => (
            <Swatch key={k} shape={dot(R7_COLORS[k])}>{R7_LABELS[k]}</Swatch>
          ))}
          {sep}
          <Swatch shape={dot('transparent', { border: '2.5px solid #e53935' })}>⚠ SPOF</Swatch>
          <Swatch shape={dot(T.panel, { borderStyle: 'dashed', borderColor: T.muted, opacity: .7 })}>Fantôme</Swatch>
        </>
      )}
      {plan === 'data' && (
        <Swatch shape={dot(SUBTYPE_COLORS.dataentity)}>Entité de données</Swatch>
      )}
      {plan === 'global' && (
        <>
          <Swatch shape={dot(SUBTYPE_COLORS.domain)}       >Domaine</Swatch>
          <Swatch shape={dot(SUBTYPE_COLORS.macrofunction)}>Macro-fonction</Swatch>
          <Swatch shape={dot(SUBTYPE_COLORS.dataentity)}   >Donnée</Swatch>
          {sep}
          {Object.keys(R7_COLORS).filter(k => k !== 'UNQUALIFIED').map(k => (
            <Swatch key={k} shape={dot(R7_COLORS[k])}>{R7_LABELS[k]}</Swatch>
          ))}
        </>
      )}
    </div>
  );
};

// ── Appartements candidats — surlignage (T15 UI) ───────────────
// La SDD ne prescrit pas de composant dédié à la visualisation des clusters
// (seul GraphActions — « exporter clusters/CSV » — figure dans l'arbre §7) :
// choix de conception ci-dessous. On ne surligne QUE les appartements candidats
// (cohésion > 0.7 ET couplage externe < 0.3 — F1.5), pas les communautés Louvain
// brutes : sur le graphe live, 4 communautés sur 14 sont des candidats réels —
// surligner les 14 noierait le signal actionnable sous du bruit visuel.
const CLUSTER_PALETTE = ['#00bcd4', '#ffca28', '#26a69a', '#ec407a', '#5c6bc0', '#9ccc65', '#8d6e63', '#789262'];

const ClusterToggle = ({ active, count, disabled, title, onChange }) => (
  <button
    onClick={() => onChange(!active)}
    disabled={disabled}
    title={title}
    style={{
      display: 'flex', alignItems: 'center', gap: 7,
      height: 30, padding: '0 14px',
      borderRadius: T.radiusPill,
      border: `1px solid ${active ? T.azureBorder : T.border}`,
      background: active ? T.azureSoft : T.white,
      color: disabled ? T.muted : (active ? T.azureInk : T.sub),
      fontFamily: T.font, fontSize: 12.5, fontWeight: active ? 700 : 500,
      cursor: disabled ? 'default' : 'pointer', whiteSpace: 'nowrap',
      opacity: disabled ? 0.5 : 1, transition: 'all .12s',
    }}
  >
    <span style={{ width: 9, height: 9, borderRadius: '50%', flexShrink: 0, background: active ? T.azure : T.muted }} />
    Appartements candidats{count > 0 ? ` (${count})` : ''}
  </button>
);

const ClusterList = ({ clusters, onFocus, onClose }) => (
  <div style={{
    position: 'absolute', top: 14, left: 14, zIndex: 5,
    width: 272, maxHeight: 'calc(100% - 28px)', overflowY: 'auto',
    background: 'rgba(255,255,255,.97)', backdropFilter: 'blur(6px)',
    border: `1px solid ${T.border}`, borderRadius: T.radiusMd,
    boxShadow: '0 10px 30px rgba(28,27,24,.14)', fontFamily: T.font,
  }}>
    <div style={{
      display: 'flex', alignItems: 'center', justifyContent: 'space-between',
      padding: '12px 8px 12px 14px', borderBottom: `1px solid ${T.border}`,
    }}>
      <span style={{ fontSize: 12.5, fontWeight: 700, color: T.ink }}>
        Appartements candidats · {clusters.length}
      </span>
      <button
        onClick={onClose}
        title="Masquer le panneau des clusters"
        style={{ display: 'flex', border: 'none', background: 'none', cursor: 'pointer', color: T.muted, padding: 6, borderRadius: T.radiusSm }}
      >
        <Ic.Close s={12} />
      </button>
    </div>
    <div style={{ padding: 8, display: 'flex', flexDirection: 'column', gap: 3 }}>
      {clusters.map((c, i) => (
        <button
          key={c.clusterId}
          onClick={() => onFocus(c)}
          title={`Centrer la vue sur ${c.name ?? c.clusterId}`}
          style={{
            display: 'flex', flexDirection: 'column', gap: 3, textAlign: 'left',
            padding: '8px 10px', borderRadius: T.radiusSm, border: 'none',
            background: 'transparent', cursor: 'pointer', fontFamily: T.font,
            transition: 'background .12s',
          }}
          onMouseEnter={e => { e.currentTarget.style.background = T.panel; }}
          onMouseLeave={e => { e.currentTarget.style.background = 'transparent'; }}
        >
          <span style={{ display: 'flex', alignItems: 'center', gap: 8, fontSize: 12.5, fontWeight: 600, color: T.ink }}>
            <span style={{ width: 11, height: 11, borderRadius: '50%', flexShrink: 0, background: CLUSTER_PALETTE[i % CLUSTER_PALETTE.length] }} />
            {c.name ?? c.clusterId}
          </span>
          <span style={{ fontSize: 11, color: T.muted, paddingLeft: 19 }}>
            {c.size} nœud{c.size > 1 ? 's' : ''} · cohésion {c.cohesion.toFixed(2)} · couplage ext. {c.externalCoupling.toFixed(2)}
          </span>
        </button>
      ))}
    </div>
  </div>
);

// ── Exports — T18 (JSON clusters + CSV non qualifiés) ──────────
// Aucun contrat backend dédié n'existe pour ces exports (vérifié dans la SDD §3) :
// sérialisation purement client-side des données déjà chargées, via Blob + <a download>.
const _todayStamp = () => new Date().toISOString().slice(0, 10);

const _downloadFile = (filename, content, mime) => {
  const blob = new Blob([content], { type: mime });
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);
  URL.revokeObjectURL(url);
};

const _csvCell = (value) => {
  if (value === null || value === undefined) return '';
  const s = Array.isArray(value) ? value.join('|') : String(value);
  return /[",\r\n]/.test(s) ? `"${s.replace(/"/g, '""')}"` : s;
};

// Colonnes du CSV — sous-ensemble de TechnicalNode utile au triage (taille,
// criticité, SPOF, propriétaire, conformité), pas le DTO brut complet.
const UNQUALIFIED_CSV_COLUMNS = [
  ['id',                 n => n.id],
  ['componentName',      n => n.componentName],
  ['technology',         n => n.technology],
  ['linesOfCode',        n => n.linesOfCode],
  ['callFrequency',      n => n.callFrequency],
  ['criticalityScore',   n => n.criticalityScore],
  ['betweenness',        n => (typeof n.betweenness === 'number' ? n.betweenness.toFixed(3) : n.betweenness)],
  ['isSPOF',             n => n.isSPOF],
  ['docCoveragePercent', n => n.docCoveragePercent],
  ['knowledgeOwner',     n => n.knowledgeOwner],
  ['regulatoryTags',     n => n.regulatoryTags],
];

const exportUnqualifiedCsv = (nodes) => {
  const rows = nodes.filter(n => n.type === 'technical' && n.candidate7R === 'UNQUALIFIED');
  const lines = [
    UNQUALIFIED_CSV_COLUMNS.map(([key]) => key).join(','),
    ...rows.map(n => UNQUALIFIED_CSV_COLUMNS.map(([, get]) => _csvCell(get(n))).join(',')),
  ];
  // BOM UTF-8 — sans lui, Excel (FR) lit le fichier en ANSI et déforme les accents
  _downloadFile(`adgm-non-qualifies-${_todayStamp()}.csv`, '﻿' + lines.join('\r\n'), 'text/csv;charset=utf-8');
};

const exportClustersJson = (clusters) => {
  const payload = { exportedAt: new Date().toISOString(), total: clusters.length, items: clusters };
  _downloadFile(`adgm-clusters-${_todayStamp()}.json`, JSON.stringify(payload, null, 2), 'application/json');
};

const ActionButton = ({ onClick, disabled, title, children }) => (
  <button
    onClick={onClick}
    disabled={disabled}
    title={title}
    style={{
      display: 'flex', alignItems: 'center', gap: 6,
      height: 30, padding: '0 13px',
      borderRadius: T.radiusPill, border: `1px solid ${T.border}`,
      background: T.white, color: disabled ? T.muted : T.sub,
      fontFamily: T.font, fontSize: 12.5, fontWeight: 500,
      cursor: disabled ? 'default' : 'pointer', whiteSpace: 'nowrap',
      opacity: disabled ? 0.5 : 1, transition: 'background .12s, border-color .12s, color .12s',
    }}
    onMouseEnter={e => { if (!disabled) { e.currentTarget.style.background = T.panel; e.currentTarget.style.borderColor = T.borderStrong; e.currentTarget.style.color = T.ink; } }}
    onMouseLeave={e => { if (!disabled) { e.currentTarget.style.background = T.white; e.currentTarget.style.borderColor = T.border; e.currentTarget.style.color = T.sub; } }}
  >
    {children}
  </button>
);

// ── Reset graphe ───────────────────────────────────────────────
// Deux clics requis pour confirmer — premier clic passe en état "confirmer",
// second clic exécute. Auto-annulation après 4 s d'inaction.
const ResetButton = ({ onReset, disabled }) => {
  const [confirming, setConfirming] = React.useState(false);
  const timerRef = React.useRef(null);

  const handleClick = () => {
    if (disabled) return;
    if (!confirming) {
      setConfirming(true);
      clearTimeout(timerRef.current);
      timerRef.current = setTimeout(() => setConfirming(false), 4000);
    } else {
      clearTimeout(timerRef.current);
      setConfirming(false);
      onReset();
    }
  };

  React.useEffect(() => () => clearTimeout(timerRef.current), []);

  return (
    <button
      onClick={handleClick}
      disabled={disabled}
      title={
        confirming
          ? 'Cliquer encore pour confirmer — TOUTES les données seront supprimées, irréversible'
          : 'Supprimer toutes les données du graphe ADG-M (irréversible)'
      }
      style={{
        display: 'flex', alignItems: 'center', gap: 6,
        height: 30, padding: '0 13px',
        borderRadius: T.radiusPill, border: 'none',
        background: confirming
          ? 'linear-gradient(135deg, #ea580c 0%, #b91c1c 100%)'
          : 'linear-gradient(135deg, #fb923c 0%, #dc2626 100%)',
        color: '#ffffff',
        fontFamily: T.font, fontSize: 12.5, fontWeight: 600,
        cursor: disabled ? 'default' : 'pointer',
        opacity: disabled ? 0.5 : 1,
        boxShadow: confirming ? '0 2px 8px rgba(220,38,38,.35)' : '0 2px 6px rgba(251,146,60,.3)',
        transition: 'all .15s', whiteSpace: 'nowrap',
      }}
      onMouseEnter={e => { if (!disabled) e.currentTarget.style.filter = 'brightness(1.08)'; }}
      onMouseLeave={e => { if (!disabled) e.currentTarget.style.filter = 'none'; }}
    >
      <Ic.Close s={10} />
      {confirming ? '⚠ Confirmer le reset' : 'Reset graphe'}
    </button>
  );
};

// ── LED d'état du pipeline Neo4j ──────────────────────────────
// Vert : données chargées · Jaune : en cours / réessai · Rouge : erreur
const GraphLed = ({ graphStatus, error, extractJob }) => {
  const isExtracting = extractJob?.status === 'pending' || extractJob?.status === 'running';

  let color, label, pulse;
  if (graphStatus === 'error') {
    color = '#ef4444'; pulse = false;
    label = error ? error.replace(/^(Nœuds|Arcs)\s*:\s*/i, '').slice(0, 60) : 'Service ADG-M inaccessible';
  } else if (graphStatus === 'loading' || graphStatus === 'retrying' || isExtracting) {
    color = '#f59e0b'; pulse = true;
    label = graphStatus === 'retrying' ? 'Reconnexion au service ADG-M…'
          : isExtracting               ? 'Extraction en cours…'
          :                              'Connexion à Neo4j…';
  } else if (graphStatus === 'empty') {
    color = '#9ca3af'; pulse = false;
    label = 'Base Neo4j vide — lancez une extraction';
  } else {
    color = '#22c55e'; pulse = false;
    label = 'Neo4j disponible';
  }

  return (
    <div style={{ display: 'flex', alignItems: 'center', gap: 5, fontFamily: T.font }} title={label}>
      <span style={{
        width: 9, height: 9, borderRadius: '50%', flexShrink: 0,
        background: color,
        boxShadow: `0 0 0 2.5px ${color}30`,
        animation: pulse ? 'nlGraphPulse 1.3s ease-in-out infinite' : 'none',
      }} />
      {graphStatus === 'error' && (
        <span style={{ fontSize: 12, color: '#ef4444', whiteSpace: 'nowrap', maxWidth: 220, overflow: 'hidden', textOverflow: 'ellipsis' }}>
          {label}
        </span>
      )}
    </div>
  );
};

// ── Extraction Chat → Graph (Track C) ─────────────────────────
// Déclenche POST /api/extract/graph (api/routers/extract.py) et poll le statut.
// Le composant reçoit le job courant et un callback onStart ; la logique de
// polling et de refresh du graphe vit dans GraphPage (état et effets).
const ExtractButton = ({ job, onStart, disabled }) => {
  const isRunning = job && (job.status === 'pending' || job.status === 'running');
  const isDone    = job?.status === 'done';
  const isError   = job?.status === 'error';

  if (isRunning) {
    const progress = job.docs_total > 0
      ? Math.round((job.docs_processed / job.docs_total) * 100)
      : null;
    return (
      <div style={{
        display: 'flex', alignItems: 'center', gap: 8,
        height: 30, padding: '0 12px',
        borderRadius: T.radiusPill, border: `1px solid ${T.border}`,
        background: T.panel, fontFamily: T.font, fontSize: 12.5, color: T.sub,
        whiteSpace: 'nowrap', maxWidth: 320,
      }}>
        <div style={{
          width: 12, height: 12, borderRadius: '50%', flexShrink: 0,
          border: '2px solid #d2e0fc', borderTopColor: T.azure,
          animation: 'nlGraphSpin .7s linear infinite',
        }} />
        <span style={{ overflow: 'hidden', textOverflow: 'ellipsis' }}>
          {progress !== null ? `${progress}% — ` : ''}{job.message}
        </span>
      </div>
    );
  }

  const totalImported = isDone && job.entities_imported
    ? Object.values(job.entities_imported).reduce((s, v) => s + v, 0)
    : 0;

  const label = isError   ? 'Réessayer'
              : isDone    ? `Mettre à jour · ${totalImported} ent.`
              :             'Construire le graphe ADG-M';
  const title = isError
    ? `Erreur : ${job.message} — Cliquer pour réessayer`
    : isDone
      ? 'Relancer l\'extraction depuis les documents indexés'
      : 'Extraire les entités des documents indexés dans le Chat pour alimenter le graphe ADG-M';

  return (
    <button
      onClick={disabled ? undefined : onStart}
      disabled={disabled}
      title={disabled ? 'Chargement en cours…' : title}
      style={{
        display: 'flex', alignItems: 'center', gap: 7,
        height: 30, padding: '0 14px',
        borderRadius: T.radiusPill, border: 'none',
        background: disabled
          ? T.panel2
          : isError
            ? 'linear-gradient(135deg, #f87171 0%, #dc2626 100%)'
            : 'linear-gradient(135deg, #60a5fa 0%, #1e40af 100%)',
        color: disabled ? T.muted : '#ffffff',
        fontFamily: T.font, fontSize: 12.5, fontWeight: 600,
        cursor: disabled ? 'default' : 'pointer', whiteSpace: 'nowrap', transition: 'filter .12s',
        opacity: disabled ? 0.5 : 1,
        boxShadow: disabled ? 'none' : isError
          ? '0 2px 6px rgba(220,38,38,.3)'
          : '0 2px 6px rgba(96,165,250,.35)',
      }}
      onMouseEnter={e => { if (!disabled) e.currentTarget.style.filter = 'brightness(1.1)'; }}
      onMouseLeave={e => { if (!disabled) e.currentTarget.style.filter = 'none'; }}
    >
      <Ic.Lightning s={12} />
      {label}
    </button>
  );
};

// SDD §7 : « GraphActions — relancer analyse, exporter clusters/CSV ». Le proxy
// /api/graph (Increment 2) ne relaie volontairement que GET/PATCH — pas
// POST /admin/analyze, opération d'administration hors surface utilisateur —
// donc seuls les exports (100% client, sans dépendance backend) sont proposés ici.
const GraphActions = ({ clusters, nodes }) => {
  const unqualifiedCount = React.useMemo(
    () => nodes.filter(n => n.type === 'technical' && n.candidate7R === 'UNQUALIFIED').length,
    [nodes]
  );
  return (
    <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
      <ActionButton
        onClick={() => exportClustersJson(clusters)}
        disabled={clusters.length === 0}
        title="Télécharger les appartements candidats au format JSON"
      >
        <Ic.Doc s={13} /> Clusters · JSON
      </ActionButton>
      <ActionButton
        onClick={() => exportUnqualifiedCsv(nodes)}
        disabled={unqualifiedCount === 0}
        title="Télécharger les composants non qualifiés au format CSV"
      >
        <Ic.Doc s={13} /> Non qualifiés · CSV{unqualifiedCount > 0 ? ` (${unqualifiedCount})` : ''}
      </ActionButton>
    </div>
  );
};

// ── Détail du nœud sélectionné (F1.4 — RightPanel) ─────────────
// UNQUALIFIED exclu : l'API rejette ce candidat en 400 (ce n'est pas une trajectoire,
// c'est l'absence de qualification — on ne peut pas "qualifier vers" cet état).
const QUALIFIABLE_7R = Object.keys(R7_LABELS).filter(k => k !== 'UNQUALIFIED');
const AUTHOR_STORAGE_KEY = 'nlaz-adgm-author';

const SectionTitle = ({ children }) => (
  <div style={{ fontSize: 10.5, fontWeight: 700, letterSpacing: 0.6, textTransform: 'uppercase', color: T.muted, marginBottom: 8 }}>
    {children}
  </div>
);

const Pill = ({ children, color = T.sub, bg = T.panel, border = T.border }) => (
  <span style={{ display: 'inline-flex', alignItems: 'center', gap: 5, fontSize: 11, fontWeight: 600, lineHeight: 1, padding: '4px 9px', borderRadius: T.radiusPill, color, background: bg, border: `1px solid ${border}`, whiteSpace: 'nowrap' }}>
    {children}
  </span>
);

const DetailRow = ({ label, value }) => {
  if (value === undefined || value === null || value === '') return null;
  return (
    <div style={{ display: 'flex', alignItems: 'flex-start', justifyContent: 'space-between', gap: 14, padding: '6px 0', fontSize: 12.5, lineHeight: 1.5, borderBottom: `1px solid ${T.border}` }}>
      <span style={{ color: T.muted, flexShrink: 0 }}>{label}</span>
      <span style={{ color: T.ink, fontWeight: 600, textAlign: 'right' }}>{value}</span>
    </div>
  );
};

const critStyle = (level) => level === 'CRITICAL' ? { color: T.danger, fontWeight: 700 } : { color: T.muted, fontWeight: 500 };

const ArcSection = ({ title, arcs, nodesById, endField }) => {
  if (!arcs?.length) return null;
  return (
    <div style={{ marginTop: 16 }}>
      <SectionTitle>{title} ({arcs.length})</SectionTitle>
      <div style={{ display: 'flex', flexDirection: 'column', gap: 5 }}>
        {arcs.map(a => {
          const other = nodesById.get(a[endField]);
          const label = other ? (other.type === 'technical' ? other.componentName : other.domain) : a[endField];
          return (
            <div key={a.id} title={a.arcType} style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 10, fontSize: 12, padding: '7px 10px', background: T.panel, borderRadius: T.radiusSm }}>
              <span style={{ color: T.ink, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap', minWidth: 0 }}>{label}</span>
              <span style={{ flexShrink: 0, fontSize: 10.5, ...critStyle(a.criticality) }}>{a.criticality}</span>
            </div>
          );
        })}
      </div>
    </div>
  );
};

const ImpactSection = ({ impact }) => {
  if (!impact?.downstreamImpacted?.length) return null;
  return (
    <div style={{ marginTop: 16, padding: '12px 13px', background: '#fef2f2', border: '1px solid #fecaca', borderRadius: T.radiusMd }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 6, marginBottom: 9 }}>
        <span style={{ color: T.danger, fontWeight: 700, fontSize: 13 }}>⚠</span>
        <span style={{ fontSize: 12.5, fontWeight: 700, color: '#b91c1c' }}>
          SPOF — {impact.impactedCount} composant{impact.impactedCount > 1 ? 's' : ''} impacté{impact.impactedCount > 1 ? 's' : ''} en cascade
        </span>
      </div>
      <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
        {impact.downstreamImpacted.map(c => (
          <div key={c.id} style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 10, fontSize: 12 }}>
            <span style={{ color: T.ink, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap', minWidth: 0 }}>
              <span style={{ color: '#b91c1c', fontWeight: 700 }}>+{c.distance}</span> {c.componentName}
            </span>
            <span style={{ flexShrink: 0, fontSize: 10.5, ...critStyle(c.criticality) }}>{c.criticality}</span>
          </div>
        ))}
      </div>
    </div>
  );
};

const fieldStyle = {
  width: '100%', boxSizing: 'border-box',
  border: `1px solid ${T.border}`, borderRadius: T.radiusSm,
  background: T.white, color: T.ink,
  fontFamily: T.font, fontSize: 12.5,
  padding: '8px 10px', outline: 'none',
};

const AnnotationForm = ({ node, apiFetch, onSuccess }) => {
  const [target,        setTarget]        = React.useState('');
  const [justification, setJustification] = React.useState('');
  const [author,        setAuthor]        = React.useState(() => localStorage.getItem(AUTHOR_STORAGE_KEY) ?? '');
  const [submitting,    setSubmitting]    = React.useState(false);
  const [feedback,      setFeedback]      = React.useState(null);

  const canSubmit = !!target && !!justification.trim() && !!author.trim() && !submitting;

  const submit = async () => {
    if (!canSubmit) return;
    setSubmitting(true);
    setFeedback(null);
    try {
      const res = await apiFetch(`${API_BASE}/graph/nodes/${node.id}/qualification`, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ candidate7R: target, justification: justification.trim(), source: 'MANUAL', author: author.trim() }),
      });
      const data = await res.json().catch(() => ({}));
      if (!res.ok) throw new Error(data.error || `HTTP ${res.status}`);
      localStorage.setItem(AUTHOR_STORAGE_KEY, author.trim());
      setFeedback({ ok: true, message: `Qualifié : ${R7_LABELS[data.previous7R] ?? data.previous7R} → ${R7_LABELS[data.candidate7R] ?? data.candidate7R}` });
      setTarget('');
      setJustification('');
      onSuccess(data);
    } catch (err) {
      setFeedback({ ok: false, message: err.message || 'Échec de la qualification.' });
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div style={{ marginTop: 18, paddingTop: 16, borderTop: `1px solid ${T.border}` }}>
      <SectionTitle>Qualifier (7R)</SectionTitle>
      <label style={{ display: 'block', fontSize: 11.5, color: T.sub, marginBottom: 4 }}>Trajectoire cible</label>
      <select value={target} onChange={e => setTarget(e.target.value)} style={{ ...fieldStyle, marginBottom: 10, cursor: 'pointer' }}>
        <option value="">— Choisir une trajectoire —</option>
        {QUALIFIABLE_7R.map(k => <option key={k} value={k}>{R7_LABELS[k]}</option>)}
      </select>
      <label style={{ display: 'block', fontSize: 11.5, color: T.sub, marginBottom: 4 }}>Justification</label>
      <textarea value={justification} onChange={e => setJustification(e.target.value)} placeholder="Motif de la décision…" rows={3} style={{ ...fieldStyle, marginBottom: 10, resize: 'vertical', lineHeight: 1.5, fontFamily: T.font }} />
      <label style={{ display: 'block', fontSize: 11.5, color: T.sub, marginBottom: 4 }}>Auteur (UPN)</label>
      <input type="text" value={author} onChange={e => setAuthor(e.target.value)} placeholder="prenom.nom@domaine.fr" style={{ ...fieldStyle, marginBottom: 12 }} />
      <button onClick={submit} disabled={!canSubmit} style={{ width: '100%', height: 36, display: 'flex', alignItems: 'center', justifyContent: 'center', gap: 7, borderRadius: T.radiusPill, border: 'none', background: canSubmit ? T.azure : T.panel2, color: canSubmit ? T.white : T.muted, fontFamily: T.font, fontSize: 13, fontWeight: 600, cursor: canSubmit ? 'pointer' : 'default', transition: 'background .12s' }}
        onMouseEnter={e => { if (canSubmit) e.currentTarget.style.background = T.azureHover; }}
        onMouseLeave={e => { if (canSubmit) e.currentTarget.style.background = T.azure; }}>
        {submitting ? 'Envoi…' : <><Ic.Check s={14} /> Valider la qualification</>}
      </button>
      {feedback && <p style={{ margin: '10px 0 0', fontSize: 12, lineHeight: 1.5, color: feedback.ok ? T.success : T.danger }}>{feedback.message}</p>}
    </div>
  );
};

const NodeDetailPanel = ({ nodeId, apiFetch, nodesById, onClose, onQualified }) => {
  const [detail,  setDetail]  = React.useState(null);
  const [impact,  setImpact]  = React.useState(null);
  const [loading, setLoading] = React.useState(true);
  const [error,   setError]   = React.useState(null);

  React.useEffect(() => {
    let cancelled = false;
    setLoading(true); setError(null); setDetail(null); setImpact(null);
    (async () => {
      try {
        const res = await apiFetch(`${API_BASE}/graph/nodes/${nodeId}`);
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        const data = await res.json();
        if (cancelled) return;
        setDetail(data);
        // SDD : "pour un nœud SPOF, retourne la liste des composants impactés en cascade"
        // — on ne sollicite cet endpoint que pour les nœuds réellement concernés.
        if (data?.node?.isSPOF) {
          const impRes = await apiFetch(`${API_BASE}/graph/nodes/${nodeId}/impact`);
          if (impRes.ok) { const impData = await impRes.json(); if (!cancelled) setImpact(impData); }
        }
      } catch (err) {
        if (!cancelled) setError(err.message || 'Erreur de chargement du nœud.');
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => { cancelled = true; };
  }, [nodeId, apiFetch]);

  const node = detail?.node;
  const isTechnical = node?.type === 'technical';

  const handleAnnotationSuccess = React.useCallback((result) => {
    setDetail(prev => prev ? { ...prev, node: { ...prev.node, candidate7R: result.candidate7R, updatedAt: result.updatedAt } } : prev);
    onQualified(result.nodeId, result.candidate7R);
  }, [onQualified]);

  return (
    <aside style={{ width: 360, flexShrink: 0, borderLeft: `1px solid ${T.border}`, background: T.white, display: 'flex', flexDirection: 'column', overflow: 'hidden' }}>
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', padding: '14px 16px', borderBottom: `1px solid ${T.border}`, flexShrink: 0 }}>
        <span style={{ fontSize: 10.5, fontWeight: 700, letterSpacing: 0.8, textTransform: 'uppercase', color: T.muted }}>Détail du nœud</span>
        <button onClick={onClose} title="Fermer" style={{ display: 'grid', placeItems: 'center', width: 28, height: 28, borderRadius: 8, border: 'none', background: 'transparent', color: T.muted, cursor: 'pointer', transition: 'background .12s, color .12s' }}
          onMouseEnter={e => { e.currentTarget.style.background = T.panel; e.currentTarget.style.color = T.ink; }}
          onMouseLeave={e => { e.currentTarget.style.background = 'transparent'; e.currentTarget.style.color = T.muted; }}>
          <Ic.Close s={14} />
        </button>
      </div>
      <div style={{ flex: 1, overflowY: 'auto', padding: '16px' }}>
        {loading && (
          <div style={{ display: 'flex', alignItems: 'center', gap: 10, color: T.sub, fontSize: 13 }}>
            <div style={{ width: 16, height: 16, borderRadius: '50%', border: '2px solid #d2e0fc', borderTopColor: T.azure, animation: 'nlGraphSpin .7s linear infinite', flexShrink: 0 }} />
            Chargement…
          </div>
        )}
        {!loading && error && <p style={{ fontSize: 12.5, color: T.danger, lineHeight: 1.6 }}>{error}</p>}
        {!loading && !error && node && (
          <>
            <div style={{ display: 'flex', alignItems: 'flex-start', gap: 7, marginBottom: 9 }}>
              {node.isSPOF && <span title="Single Point of Failure" style={{ color: T.danger, fontWeight: 700, fontSize: 14, lineHeight: '22px' }}>⚠</span>}
              <h3 style={{ margin: 0, fontSize: 15.5, fontWeight: 700, color: T.ink, lineHeight: 1.35, wordBreak: 'break-word' }}>{isTechnical ? node.componentName : node.domain}</h3>
            </div>
            <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6, marginBottom: 14 }}>
              <Pill>{isTechnical ? 'Nœud technique' : 'Nœud fonctionnel'}</Pill>
              {node.isSPOF && <Pill color={T.danger} bg="#fef2f2" border="#fecaca">⚠ SPOF</Pill>}
              {node.isGhost && <Pill border={T.borderStrong}>Fantôme</Pill>}
              {isTechnical && <Pill color={T.ink} bg={T.white} border={T.borderStrong}>{dot(R7_COLORS[node.candidate7R])} {R7_LABELS[node.candidate7R]}</Pill>}
              {!isTechnical && <Pill color={T.ink} bg={T.white} border={T.borderStrong}>{dot(STATUS_COLORS[node.modernizationStatus])} {STATUS_LABELS[node.modernizationStatus]}</Pill>}
            </div>
            <SectionTitle>Propriétés</SectionTitle>
            {isTechnical ? (
              <>
                <DetailRow label="Technologie" value={node.technology} />
                <DetailRow label="Lignes de code" value={node.linesOfCode?.toLocaleString('fr-FR')} />
                <DetailRow label="Fréquence d'appel" value={node.callFrequency} />
                <DetailRow label="Propriétaire connaissance" value={node.knowledgeOwner} />
                <DetailRow label="Réglementaire" value={node.regulatoryTags?.length ? <span style={{ display: 'inline-flex', flexWrap: 'wrap', gap: 4, justifyContent: 'flex-end' }}>{node.regulatoryTags.map(t => <Pill key={t} color={T.azureInk} bg={T.azureSoft} border={T.azureBorder}>{t}</Pill>)}</span> : null} />
                <DetailRow label="Cluster" value={node.clusterId} />
              </>
            ) : (
              <>
                <DetailRow label="Sous-domaine" value={node.subdomain} />
                <DetailRow label="Processus" value={node.processes?.join(' · ')} />
                <DetailRow label="Objets métier partagés" value={node.sharedBusinessObjects?.join(' · ')} />
              </>
            )}
            <DetailRow label="Couverture documentaire" value={node.docCoveragePercent != null ? `${node.docCoveragePercent}%` : null} />
            <div style={{ marginTop: 16 }}>
              <SectionTitle>Métriques</SectionTitle>
              <DetailRow label="Degré entrant" value={detail.metrics?.inDegree} />
              <DetailRow label="Degré sortant" value={detail.metrics?.outDegree} />
              <DetailRow label="Arcs critiques entrants" value={detail.metrics?.criticalArcsIn} />
              {isTechnical && <DetailRow label="Score de criticité" value={node.criticalityScore} />}
              {isTechnical && <DetailRow label="Centralité (betweenness)" value={node.betweenness?.toFixed(3)} />}
            </div>
            <ImpactSection impact={impact} />
            <ArcSection title="Arcs entrants" arcs={detail.incomingArcs} nodesById={nodesById} endField="sourceNodeId" />
            <ArcSection title="Arcs sortants" arcs={detail.outgoingArcs} nodesById={nodesById} endField="targetNodeId" />
            {isTechnical && <AnnotationForm node={node} apiFetch={apiFetch} onSuccess={handleAnnotationSuccess} />}
          </>
        )}
      </div>
    </aside>
  );
};

// ── Page principale ────────────────────────────────────────────
const GraphPage = ({ apiFetch }) => {
  const [plan,         setPlan]         = React.useState('functional');
  const [nodes,        setNodes]        = React.useState([]);
  const [arcs,         setArcs]         = React.useState([]);
  const [loading,      setLoading]      = React.useState(true);
  const [error,        setError]        = React.useState(null);
  const [retryAttempt, setRetryAttempt] = React.useState(0);
  const [selectedId,   setSelectedId]   = React.useState(null);
  const [showClusters, setShowClusters] = React.useState(false);
  const [clusters,     setClusters]     = React.useState([]);
  const [extractJob,   setExtractJob]   = React.useState(null);
  const [refreshKey,   setRefreshKey]   = React.useState(0);
  const [resetting,    setResetting]    = React.useState(false);
  const [graphStatus,  setGraphStatus]  = React.useState('loading');
  // Mode exploration (double-clic) : null = vue plan normale, Set<id> = ids visibles
  const [exploredIds,      setExploredIds]      = React.useState(null);
  // Données chargées par l'API neighbors pour le mode exploration
  // { nodeMap: Map<id, nodeDTO>, edgeList: Array<edge> }
  const [explorationBundle, setExplorationBundle] = React.useState(null);
  // Tooltip hover
  const [tooltip,      setTooltip]      = React.useState(null);

  const containerRef = React.useRef(null);
  const cyRef        = React.useRef(null);
  // Refs pour accéder aux données fraîches depuis les handlers Cytoscape (closures statiques)
  const nodesRef      = React.useRef([]);
  const arcsRef       = React.useRef([]);
  const planRef       = React.useRef('functional');
  const apiFetchRef   = React.useRef(apiFetch);
  React.useEffect(() => { nodesRef.current    = nodes;     }, [nodes]);
  React.useEffect(() => { arcsRef.current     = arcs;      }, [arcs]);
  React.useEffect(() => { planRef.current     = plan;      }, [plan]);
  React.useEffect(() => { apiFetchRef.current = apiFetch;  }, [apiFetch]);

  // ── Reset graphe ───────────────────────────────────────────────
  const resetGraph = React.useCallback(async () => {
    setResetting(true);
    try {
      const res = await apiFetch(`${API_BASE}/graph/admin/reset`, { method: 'DELETE' });
      if (!res.ok) { const d = await res.json().catch(() => ({})); throw new Error(d.error || `HTTP ${res.status}`); }
    } catch (err) {
      // L'erreur est silencieuse — le graphe se recharge de toute façon (refreshKey++)
      // et l'utilisateur verra un graphe vide ou l'ancien état si le reset a échoué.
    } finally {
      setResetting(false);
      setRefreshKey(k => k + 1);
    }
  }, [apiFetch]);

  // ── Extraction Chat → Graph ────────────────────────────────────
  const startExtract = React.useCallback(async () => {
    try {
      const res = await apiFetch(`${API_BASE}/extract/graph`, { method: 'POST' });
      if (!res.ok) { setExtractJob({ status: 'error', message: `HTTP ${res.status}` }); return; }
      const data = await res.json();
      setExtractJob(data);
    } catch (err) {
      setExtractJob({ status: 'error', message: err.message || 'Erreur de connexion.' });
    }
  }, [apiFetch]);

  // Poll le statut toutes les 3 s tant que le job est en cours, puis rafraîchit
  // les nœuds/arcs/clusters en incrémentant refreshKey (déclenche les useEffect).
  React.useEffect(() => {
    if (!extractJob?.job_id) return;
    if (extractJob.status !== 'pending' && extractJob.status !== 'running') return;
    const id = setInterval(async () => {
      try {
        const res = await apiFetch(`${API_BASE}/extract/graph/${extractJob.job_id}`);
        if (!res.ok) return;
        const data = await res.json();
        setExtractJob(data);
        if (data.status === 'done') setRefreshKey(k => k + 1);
      } catch { /* on ignore les erreurs réseau transitoires pendant le poll */ }
    }, 3000);
    return () => clearInterval(id);
  }, [apiFetch, extractJob?.job_id, extractJob?.status]);

  // ── Chargement des nœuds + arcs via le proxy /api/graph/* ─────
  // Retry sur 500 : l'Azure Function peut être transitoirement surchargée
  // juste après un bulk import (écritures Neo4j), les lectures échouent
  // quelques secondes avant que le service récupère.
  React.useEffect(() => {
    let cancelled = false;
    const MAX_ATTEMPTS = 4;
    setLoading(true);
    setError(null);
    setRetryAttempt(0);
    setGraphStatus('loading');

    const sleep = ms => new Promise(r => setTimeout(r, ms));

    const fetchGraph = async (attemptsLeft, delay) => {
      if (cancelled) return;
      try {
        const [nodesRes, arcsRes] = await Promise.all([
          apiFetch(`${API_BASE}/graph/nodes?limit=500`),
          apiFetch(`${API_BASE}/graph/arcs?limit=1000`),
        ]);
        if ((nodesRes.status === 500 || arcsRes.status === 500) && attemptsLeft > 0) {
          if (!cancelled) {
            setGraphStatus('retrying');
            setRetryAttempt(MAX_ATTEMPTS - attemptsLeft + 1);
          }
          await sleep(delay);
          return fetchGraph(attemptsLeft - 1, Math.min(delay * 1.5, 10000));
        }
        if (!nodesRes.ok) throw new Error(`Nœuds : HTTP ${nodesRes.status}`);
        if (!arcsRes.ok)  throw new Error(`Arcs : HTTP ${arcsRes.status}`);

        const [nodesData, arcsData] = await Promise.all([nodesRes.json(), arcsRes.json()]);
        if (cancelled) return;
        const n = nodesData.items ?? [];
        const a = arcsData.items ?? [];
        setNodes(n);
        setArcs(a);
        setGraphStatus(n.length > 0 ? 'ok' : 'empty');
      } catch (err) {
        if (!cancelled) {
          setError(err.message || 'Erreur de chargement du graphe.');
          setGraphStatus('error');
        }
      } finally {
        if (!cancelled) setLoading(false);
      }
    };

    fetchGraph(4, 3000);

    return () => { cancelled = true; };
  }, [apiFetch, refreshKey]);

  // ── Chargement séparé des clusters (T15 UI — peut échouer en 409 si
  // l'analyse Louvain n'a jamais été lancée : état normal, pas une erreur de page) ─
  React.useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const res = await apiFetch(`${API_BASE}/graph/clusters?candidateOnly=true`);
        if (cancelled) return;
        if (res.ok) {
          const data = await res.json();
          setClusters(data.items ?? []);
        } else {
          setClusters([]);
        }
      } catch {
        if (!cancelled) setClusters([]);
      }
    })();
    return () => { cancelled = true; };
  }, [apiFetch, refreshKey]);

  // ── Index nœud → cluster (T15 UI) ─────────────────────────────
  // `clusterId` est documenté sur TechnicalNode (SDD) mais jamais peuplé par le
  // backend (Louvain écrit `communityId`, pas `clusterId` — vérifié sur les 24
  // nœuds techniques live, tous `clusterId: null`). On dérive donc l'appartenance
  // côté client en inversant les `nodeIds[]` de /graph/clusters.
  const nodeClusterIndex = React.useMemo(() => {
    const map = new Map();
    clusters.forEach((c, i) => {
      const color = CLUSTER_PALETTE[i % CLUSTER_PALETTE.length];
      c.nodeIds.forEach(id => map.set(id, { cluster: c, color }));
    });
    return map;
  }, [clusters]);

  // ── Filtrage par plan actif (ou mode exploration) → éléments Cytoscape + layout ─
  const { elements, layout, nodeCount, arcCount } = React.useMemo(() => {
    const subtypeFilter = PLAN_SUBTYPES[plan];
    const planSubtypes  = subtypeFilter;  // null = global
    const EXPLORATION_LAYOUT = { name: 'cose', idealEdgeLength: 200, nodeRepulsion: 70000, gravity: 0.2, padding: 80, animate: true };

    // ── Mode exploration : données venant du bundle /neighbors ──────────────
    if (explorationBundle !== null && exploredIds !== null) {
      const visibleNodes = [...explorationBundle.nodeMap.values()].filter(n => exploredIds.has(n.id));
      const visibleIds   = new Set(visibleNodes.map(n => n.id));

      const nodeElements = visibleNodes.map(n => {
        const isTechnical  = n.type === 'technical';
        const color        = isTechnical
          ? (R7_COLORS[n.candidate7R] ?? R7_COLORS.UNQUALIFIED)
          : (SUBTYPE_COLORS[n.subtype] ?? SUBTYPE_COLORS.domain);
        const baseLabel    = isTechnical ? (n.componentName ?? n.id) : (n.domain ?? n.id);
        const isOutOfPlan  = planSubtypes !== null && !planSubtypes.has(n.subtype);
        return {
          data: {
            id: n.id,
            label: n.isSPOF ? `⚠ ${baseLabel}` : baseLabel,
            color, shape: SUBTYPE_SHAPES[n.subtype] ?? 'ellipse',
            isSPOF: !!n.isSPOF, isGhost: !!n.isGhost,
            isOutOfPlan: isOutOfPlan || undefined,
            nodeType: n.type, subtype: n.subtype,
          },
        };
      });

      // Multi-arêtes possibles (ex. DEPENDS_ON + HAS_MACROFUNCTION sur même paire)
      // → id unique par (source, target, relType)
      const edgeElements = explorationBundle.edgeList
        .filter(e => visibleIds.has(e.sourceNodeId) && visibleIds.has(e.targetNodeId))
        .map(e => ({
          data: {
            id:         `${e.sourceNodeId}|${e.targetNodeId}|${e.relType}`,
            source:     e.sourceNodeId,
            target:     e.targetNodeId,
            criticality: e.criticality,
            arcType:    e.arcType,
            relLabel:   e.relType,  // affiché sur l'arête en mode exploration
          },
        }));

      return {
        elements:  [...nodeElements, ...edgeElements],
        layout:    EXPLORATION_LAYOUT,
        nodeCount: visibleNodes.length,
        arcCount:  edgeElements.length,
      };
    }

    // ── Vue plan normale ────────────────────────────────────────────────────
    const visibleNodes = planSubtypes === null
      ? nodes
      : nodes.filter(n => planSubtypes.has(n.subtype));
    const visibleIds   = new Set(visibleNodes.map(n => n.id));
    const visibleArcs  = arcs.filter(a => visibleIds.has(a.sourceNodeId) && visibleIds.has(a.targetNodeId));

    const nodeElements = visibleNodes.map(n => {
      const isTechnical = n.type === 'technical';
      const color       = isTechnical
        ? (R7_COLORS[n.candidate7R] ?? R7_COLORS.UNQUALIFIED)
        : (SUBTYPE_COLORS[n.subtype] ?? SUBTYPE_COLORS.domain);
      const baseLabel   = isTechnical ? (n.componentName ?? n.id) : (n.domain ?? n.id);
      const clusterEntry = showClusters ? nodeClusterIndex.get(n.id) : undefined;
      return {
        data: {
          id: n.id,
          label: n.isSPOF ? `⚠ ${baseLabel}` : baseLabel,
          color, shape: SUBTYPE_SHAPES[n.subtype] ?? 'ellipse',
          isSPOF: !!n.isSPOF, isGhost: !!n.isGhost,
          nodeType: n.type, subtype: n.subtype,
          ...(clusterEntry ? { clusterColor: clusterEntry.color } : {}),
        },
      };
    });

    const edgeElements = visibleArcs.map(a => ({
      data: {
        id: a.id, source: a.sourceNodeId, target: a.targetNodeId,
        criticality: a.criticality, arcType: a.arcType,
        // pas de relLabel en vue plan → labels absents du style
      },
    }));

    return {
      elements:  [...nodeElements, ...edgeElements],
      layout:    PLAN_LAYOUTS[plan],
      nodeCount: visibleNodes.length,
      arcCount:  visibleArcs.length,
    };
  }, [nodes, arcs, plan, showClusters, nodeClusterIndex, exploredIds, explorationBundle]);

  // ── Initialisation Cytoscape — une seule fois au mount ────────
  // On ne détruit jamais cy pendant que l'utilisateur interagit : cela laisse
  // les listeners DOM internes de Cytoscape attachés à une instance dont
  // _private est null, ce qui provoque un TypeError sur findNearestElement.
  React.useEffect(() => {
    if (!containerRef.current) return;
    const cy = window.cytoscape({
      container: containerRef.current,
      elements: [],
      style: GRAPH_STYLE,
      wheelSensitivity: 0.25,
    });

    cy.on('tap', 'node', evt => setSelectedId(evt.target.id()));
    cy.on('tap', evt => {
      if (evt.target === cy) {
        setSelectedId(null);
        setExploredIds(null);       // clic fond → quitter exploration
        setExplorationBundle(null);
      }
    });

    // Double-clic → mode exploration : charge TOUTES les relations Neo4j du nœud via /neighbors
    cy.on('dblclick', 'node', async evt => {
      const nodeId = evt.target.id();
      try {
        const res = await apiFetchRef.current(
          `${API_BASE}/graph/nodes/${encodeURIComponent(nodeId)}/neighbors`
        );
        if (!res.ok) return;
        const data = await res.json(); // { center, neighbors, edges }

        // Merge dans le bundle existant (expansion progressive)
        setExplorationBundle(prev => {
          const nodeMap = prev ? new Map(prev.nodeMap) : new Map();
          const edgeList = prev ? [...prev.edgeList] : [];
          const seenKeys = new Set(edgeList.map(e => `${e.sourceNodeId}|${e.targetNodeId}|${e.relType}`));

          nodeMap.set(data.center.id, data.center);
          data.neighbors.forEach(n => nodeMap.set(n.id, n));
          data.edges.forEach(e => {
            const k = `${e.sourceNodeId}|${e.targetNodeId}|${e.relType}`;
            if (!seenKeys.has(k)) { seenKeys.add(k); edgeList.push(e); }
          });
          return { nodeMap, edgeList };
        });

        setExploredIds(prev => {
          const next = prev ? new Set(prev) : new Set();
          next.add(data.center.id);
          data.neighbors.forEach(n => next.add(n.id));
          return next;
        });
      } catch (_) { /* exploration silencieuse si l'API est injoignable */ }
    });

    // Hover arête → affiche le label de relation (mode exploration)
    cy.on('mouseover', 'edge', evt => { if (evt.target.data('relLabel')) evt.target.data('showLabel', true); });
    cy.on('mouseout',  'edge', evt => { evt.target.data('showLabel', null); });

    // Hover → tooltip avec infos clés
    cy.on('mouseover', 'node', evt => {
      const rp = evt.renderedPosition;
      const rect = containerRef.current?.getBoundingClientRect();
      if (!rect) return;
      setTooltip({ nodeId: evt.target.id(), x: rect.left + rp.x, y: rect.top + rp.y });
    });
    cy.on('mouseout', 'node', () => setTooltip(null));
    cy.on('viewport', () => setTooltip(null)); // pan/zoom → masquer tooltip

    cyRef.current = cy;
    return () => { cy.destroy(); cyRef.current = null; };
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  // ── Mise à jour du contenu — patche les éléments sans détruire cy ─
  React.useEffect(() => {
    const cy = cyRef.current;
    if (!cy) return;
    cy.elements().remove();
    cy.add(elements);
    const ly = cy.layout(layout);
    ly.one('layoutstop', () => {
      cy.fit(undefined, 80);
      // Plafonner le zoom : évite que quelques nœuds ne remplissent tout l'écran
      if (cy.zoom() > 1.0) { cy.zoom(1.0); cy.center(); }
    });
    ly.run();
  }, [elements, layout]);

  // ── Redimensionnement (Cytoscape ne suit pas son conteneur) ───
  React.useEffect(() => {
    const onResize = () => cyRef.current?.resize();
    window.addEventListener('resize', onResize);
    return () => window.removeEventListener('resize', onResize);
  }, []);

  // ── Panneau de détail (F1.4) ──────────────────────────────────
  const nodesById = React.useMemo(() => new Map(nodes.map(n => [n.id, n])), [nodes]);

  // Un nœud sélectionné peut disparaître du plan actif au changement de plan
  // (ex. un nœud technique sélectionné en vue "Technique" n'existe pas en "Fonctionnel")
  // — fermer le panneau évite d'afficher le détail d'un nœud qui n'est plus visible.
  React.useEffect(() => { setSelectedId(null); }, [plan]);

  const closeDetail = React.useCallback(() => {
    cyRef.current?.elements(':selected').unselect();
    setSelectedId(null);
  }, []);

  const handleQualified = React.useCallback((nodeId, newCandidate7R) => {
    setNodes(prev => prev.map(n => n.id === nodeId ? { ...n, candidate7R: newCandidate7R } : n));
  }, []);

  // ── Clusters (T15 UI) — focus caméra + désactivation contextuelle ─
  const focusCluster = React.useCallback((cluster) => {
    const cy = cyRef.current;
    if (!cy) return;
    const memberIds = new Set(cluster.nodeIds);
    const members = cy.nodes().filter(n => memberIds.has(n.id()));
    if (members.length > 0) cy.fit(members, 80);
  }, []);

  // Les clusters Louvain ne concernent que les TechnicalNode — désactiver hors vue Technique/Global.
  React.useEffect(() => {
    if (plan !== 'technical' && plan !== 'global') setShowClusters(false);
    setExploredIds(null);        // Changement de plan → sortir du mode exploration
    setExplorationBundle(null);
  }, [plan]);

  const clusterToggleDisabled = (plan !== 'technical' && plan !== 'global') || clusters.length === 0;
  const clusterToggleTitle = (plan !== 'technical' && plan !== 'global')
    ? 'Disponible sur les vues Technique et Global — les clusters ne regroupent que des composants techniques'
    : clusters.length === 0
      ? "Aucun appartement candidat détecté (cohésion > 0,7 et couplage externe < 0,3) sur ce graphe"
      : 'Surligner les appartements candidats détectés par le clustering Louvain';

  return (
    <div style={{ flex: 1, display: 'flex', flexDirection: 'column', overflow: 'hidden', minWidth: 0 }}>
      {/* TopBar — switch de plan + légende + compteur */}
      <div style={{
        display: 'flex', alignItems: 'center', justifyContent: 'space-between',
        flexWrap: 'wrap', gap: 14, padding: '14px 22px',
        borderBottom: `1px solid ${T.border}`, background: T.white, fontFamily: T.font,
      }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 16, flexWrap: 'wrap' }}>
          <PlanSwitch plan={plan} onChange={setPlan} />
          <ClusterToggle
            active={showClusters}
            count={clusters.length}
            disabled={clusterToggleDisabled}
            title={clusterToggleTitle}
            onChange={setShowClusters}
          />
          <GraphLed graphStatus={graphStatus} error={error} extractJob={extractJob} />
          <span style={{ fontSize: 12.5, color: T.muted, whiteSpace: 'nowrap' }}>
            {nodeCount} nœud{nodeCount > 1 ? 's' : ''} · {arcCount} arc{arcCount > 1 ? 's' : ''}
          </span>
        </div>
        <div style={{ display: 'flex', alignItems: 'center', flexWrap: 'wrap', gap: 8 }}>
          <ExtractButton job={extractJob} onStart={startExtract} disabled={loading} />
          <ActionButton
            onClick={() => setRefreshKey(k => k + 1)}
            disabled={loading}
            title="Recharger les données depuis Neo4j (sans réextraction)"
          >
            <span style={{ fontSize: 14, lineHeight: 1 }}>↻</span> Actualiser
          </ActionButton>
          <ResetButton onReset={resetGraph} disabled={resetting} />
          <span style={{ width: 1, height: 18, background: T.border, flexShrink: 0 }} />
          <GraphActions clusters={clusters} nodes={nodes} />
          <Legend plan={plan} />
        </div>
      </div>

      {/* Canvas + panneau de détail (F1.4) */}
      <div style={{ flex: 1, display: 'flex', overflow: 'hidden', minHeight: 0 }}>
        <div style={{ flex: 1, position: 'relative', background: T.panel, minHeight: 0 }}>
          <div ref={containerRef} style={{ position: 'absolute', inset: 0 }} />

          {/* Bannière mode exploration */}
          {exploredIds !== null && (
            <div style={{
              position: 'absolute', top: 12, left: '50%', transform: 'translateX(-50%)',
              display: 'flex', alignItems: 'center', gap: 10,
              padding: '6px 14px 6px 12px',
              background: 'rgba(21,101,192,.92)', backdropFilter: 'blur(4px)',
              borderRadius: T.radiusPill, fontFamily: T.font, fontSize: 12.5,
              color: '#fff', boxShadow: '0 4px 16px rgba(21,101,192,.3)', zIndex: 10,
              whiteSpace: 'nowrap',
            }}>
              <span style={{ opacity: .8 }}>Mode exploration</span>
              <span style={{ fontWeight: 700 }}>{exploredIds.size} nœud{exploredIds.size > 1 ? 's' : ''}</span>
              <span style={{ opacity: .6 }}>·</span>
              <span style={{ opacity: .8, fontSize: 11 }}>Double-clic pour étendre · Clic fond pour quitter</span>
              <button
                onClick={() => { setExploredIds(null); setExplorationBundle(null); }}
                style={{
                  marginLeft: 4, padding: '2px 10px', borderRadius: T.radiusPill,
                  border: 'none', background: 'rgba(255,255,255,.2)', color: '#fff',
                  fontFamily: T.font, fontSize: 12, cursor: 'pointer',
                }}
              >Quitter</button>
            </div>
          )}

          {showClusters && clusters.length > 0 && (
            <ClusterList clusters={clusters} onFocus={focusCluster} onClose={() => setShowClusters(false)} />
          )}

          {loading && (() => {
            const isRetrying  = graphStatus === 'retrying';
            const isRefreshing = extractJob?.status === 'done';
            const spinColor   = isRetrying ? '#f59e0b' : T.azure;
            const trackColor  = isRetrying ? '#fef3c7' : '#d2e0fc';
            const mainMsg     = isRetrying
              ? `Service temporairement indisponible · Tentative ${retryAttempt}/4…`
              : isRefreshing
                ? 'Actualisation du graphe après extraction…'
                : 'Connexion au service graphe ADG-M…';
            const subMsg      = isRetrying
              ? 'Le service reprend généralement en quelques secondes.'
              : isRefreshing
                ? 'Les nouveaux nœuds et arcs vont apparaître.'
                : null;
            return (
              <div style={{
                position: 'absolute', inset: 0, display: 'flex', flexDirection: 'column',
                alignItems: 'center', justifyContent: 'center', gap: 10,
                background: T.panel, fontFamily: T.font,
              }}>
                <div style={{
                  width: 26, height: 26, borderRadius: '50%',
                  border: `2.5px solid ${trackColor}`, borderTopColor: spinColor,
                  animation: 'nlGraphSpin .7s linear infinite',
                }} />
                <span style={{ fontSize: 13, color: isRetrying ? '#92400e' : T.sub, fontWeight: isRetrying ? 500 : 400 }}>
                  {mainMsg}
                </span>
                {subMsg && (
                  <span style={{ fontSize: 11.5, color: T.muted, maxWidth: 340, textAlign: 'center' }}>
                    {subMsg}
                  </span>
                )}
              </div>
            );
          })()}

          {!loading && error && (
            <div style={{ position: 'absolute', inset: 0, display: 'flex', alignItems: 'center', justifyContent: 'center', padding: 24 }}>
              <div style={{
                maxWidth: 440, padding: '16px 20px', borderRadius: T.radiusMd,
                background: '#fef2f2', border: '1px solid #fecaca', fontFamily: T.font,
              }}>
                <div style={{ fontWeight: 700, fontSize: 14, color: T.danger, marginBottom: 4 }}>
                  Impossible de charger le graphe ADG-M
                </div>
                <div style={{ fontSize: 12.5, color: '#b91c1c', lineHeight: 1.6 }}>{error}</div>
              </div>
            </div>
          )}

          {!loading && !error && elements.length === 0 && (
            <div style={{
              position: 'absolute', inset: 0, display: 'flex', flexDirection: 'column',
              alignItems: 'center', justifyContent: 'center', gap: 8,
              fontFamily: T.font,
            }}>
              {nodes.length === 0 ? (
                <>
                  <span style={{ fontSize: 13, color: T.ink, fontWeight: 500 }}>
                    Le graphe ADG-M est vide
                  </span>
                  <span style={{ fontSize: 12, color: T.muted, maxWidth: 320, textAlign: 'center', lineHeight: 1.6 }}>
                    Indexez des documents dans l'onglet Chat, puis cliquez sur
                    {' '}<strong>Construire le graphe ADG-M</strong> pour extraire les entités.
                  </span>
                </>
              ) : (
                <span style={{ fontSize: 13, color: T.muted }}>
                  Aucun nœud à afficher pour ce plan.
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
            nodesById={nodesById}
            onClose={closeDetail}
            onQualified={handleQualified}
          />
        )}
      </div>

      {/* Tooltip hover — position: fixed pour sortir du clip du canvas */}
      {tooltip && (() => {
        const n = nodesById.get(tooltip.nodeId);
        if (!n) return null;
        const isTechnical = n.type === 'technical';
        const lines = [
          { label: 'Type',   value: SUBTYPE_LABELS[n.subtype] ?? n.subtype },
          isTechnical && n.technology  && { label: 'Techno',  value: n.technology },
          isTechnical && n.linesOfCode && { label: 'LoC',     value: n.linesOfCode.toLocaleString() },
          isTechnical && n.candidate7R && { label: '7R',      value: n.candidate7R },
          !isTechnical && n.modernizationStatus && { label: 'Statut', value: STATUS_LABELS[n.modernizationStatus] ?? n.modernizationStatus },
        ].filter(Boolean);
        const TIP_W = 200;
        return (
          <div style={{
            position: 'fixed',
            left: tooltip.x + 14, top: tooltip.y - 10,
            width: TIP_W, padding: '8px 12px',
            background: 'rgba(28,27,24,.93)', backdropFilter: 'blur(6px)',
            borderRadius: T.radiusMd, fontFamily: T.font,
            boxShadow: '0 6px 20px rgba(0,0,0,.25)', zIndex: 9999,
            pointerEvents: 'none',
          }}>
            <div style={{ fontSize: 12.5, fontWeight: 700, color: '#fff', marginBottom: 5,
                          overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
              {n.domain ?? n.componentName ?? n.id}
            </div>
            {lines.map(({ label, value }) => (
              <div key={label} style={{ display: 'flex', justifyContent: 'space-between', fontSize: 11.5, marginTop: 2 }}>
                <span style={{ color: '#94a3b8' }}>{label}</span>
                <span style={{ color: '#e2e8f0', fontWeight: 500, marginLeft: 8,
                               overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap',
                               maxWidth: 110 }}>{value}</span>
              </div>
            ))}
            {n.docCoveragePercent != null && (
              <div style={{ marginTop: 5, fontSize: 11, color: '#64748b' }}>
                Couverture doc. : {Math.round(n.docCoveragePercent)}%
              </div>
            )}
            <div style={{ marginTop: 5, borderTop: '1px solid rgba(255,255,255,.1)', paddingTop: 5,
                          fontSize: 10.5, color: '#475569' }}>
              Double-clic → développer les voisins
            </div>
          </div>
        );
      })()}

      <style>{`
        @keyframes nlGraphSpin { to { transform: rotate(360deg); } }
        @keyframes nlGraphPulse { 0%,100% { opacity: 1; } 50% { opacity: .35; } }
      `}</style>
    </div>
  );
};

Object.assign(window, { GraphPage });
