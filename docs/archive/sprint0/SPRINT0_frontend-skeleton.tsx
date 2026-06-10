/**
 * React Frontend Skeleton — ADG-M Graph Visualization
 * Stack: React 18 + TypeScript + Vite + Cytoscape.js + MSAL
 *
 * Structure:
 *   src/
 *     components/
 *       GraphView.tsx (this file)
 *       Sidebar.tsx
 *     hooks/
 *       useGraph.ts (fetch from /api/graph/*)
 *       useAuth.ts (MSAL)
 *     services/
 *       graphService.ts (API client)
 *     App.tsx
 */

import React, { useEffect, useRef, useState } from 'react';
import CytoScape from 'cytoscape';
import './GraphView.css';

// ============================================================================
// Types
// ============================================================================

interface Component {
  id: string;
  name: string;
  type: string;
  criticality: string;
  businessValue: string;
}

interface Arc {
  source: string;
  target: string;
  type: string;
  confidence: number;
}

// ============================================================================
// Graph Service (API Client)
// ============================================================================

const graphService = {
  async getHealth() {
    const resp = await fetch('/api/graph/health');
    return resp.json();
  },

  async getNodes(filter?: { type?: string }) {
    const params = new URLSearchParams();
    if (filter?.type) params.append('type', filter.type);
    const resp = await fetch(`/api/graph/nodes?${params}`);
    return resp.json();
  },

  async getArcs() {
    const resp = await fetch('/api/graph/arcs');
    return resp.json();
  },

  async getSPOF(nodeId: string) {
    const resp = await fetch(`/api/graph/nodes/${nodeId}/spof`);
    return resp.json();
  },

  async patchQualification(nodeId: string, data: {
    sevenRChoice: string;
    validationSource: string;
    confidence: string;
  }) {
    const resp = await fetch(`/api/graph/nodes/${nodeId}/qualification`, {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(data),
    });
    return resp.json();
  },
};

// ============================================================================
// GraphView Component
// ============================================================================

export const GraphView: React.FC = () => {
  const containerRef = useRef<HTMLDivElement>(null);
  const cyRef = useRef<CytoScape.Core | null>(null);
  const [nodes, setNodes] = useState<Component[]>([]);
  const [arcs, setArcs] = useState<Arc[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [selectedNode, setSelectedNode] = useState<string | null>(null);

  // Load graph data on mount
  useEffect(() => {
    const loadGraph = async () => {
      try {
        setLoading(true);

        // Fetch nodes and arcs
        const nodesResp = await graphService.getNodes();
        const arcsResp = await graphService.getArcs();

        setNodes(nodesResp.nodes || []);
        setArcs(arcsResp.arcs || []);
        setError(null);
      } catch (err) {
        setError(`Failed to load graph: ${err}`);
        console.error(err);
      } finally {
        setLoading(false);
      }
    };

    loadGraph();
  }, []);

  // Initialize Cytoscape on data load
  useEffect(() => {
    if (!containerRef.current || nodes.length === 0) return;

    // Build Cytoscape elements
    const elements: CytoScape.ElementDefinition[] = [];

    // Add nodes
    nodes.forEach((node) => {
      elements.push({
        data: {
          id: node.id,
          label: node.name,
          type: node.type,
          criticality: node.criticality,
          businessValue: node.businessValue,
        },
        classes: [
          node.type?.toLowerCase(),
          node.criticality?.toLowerCase(),
        ].filter(Boolean),
      });
    });

    // Add edges
    arcs.forEach((arc) => {
      elements.push({
        data: {
          id: `${arc.source}-${arc.target}`,
          source: arc.source,
          target: arc.target,
          type: arc.type,
          confidence: arc.confidence,
        },
        classes: [arc.type?.toLowerCase()].filter(Boolean),
      });
    });

    // Create Cytoscape instance
    const cy = CytoScape({
      container: containerRef.current,
      elements,
      style: [
        {
          selector: 'node',
          style: {
            'background-color': '#0066cc',
            'label': 'data(label)',
            'text-valign': 'center',
            'text-halign': 'center',
            'color': '#fff',
            'font-size': '12px',
            'width': '60px',
            'height': '60px',
          },
        },
        {
          selector: 'node.critical',
          style: {
            'background-color': '#cc0000',
            'border-width': '3px',
            'border-color': '#ff0000',
          },
        },
        {
          selector: 'node.high',
          style: {
            'background-color': '#ff6600',
          },
        },
        {
          selector: 'node.system',
          style: {
            'shape': 'rectangle',
          },
        },
        {
          selector: 'node.database',
          style: {
            'shape': 'ellipse',
            'background-color': '#0099ff',
          },
        },
        {
          selector: 'node:selected',
          style: {
            'border-width': '3px',
            'border-color': '#ffff00',
          },
        },
        {
          selector: 'edge',
          style: {
            'stroke': '#999',
            'target-arrow-color': '#999',
            'target-arrow-shape': 'triangle',
            'line-color': '#ccc',
            'opacity': 0.7,
          },
        },
        {
          selector: 'edge.database',
          style: {
            'line-style': 'dashed',
          },
        },
      ],
      layout: {
        name: 'cose',
        directed: true,
        animate: true,
        animationDuration: 500,
      },
    });

    // Event handlers
    cy.on('tap', 'node', (evt) => {
      setSelectedNode(evt.target.id());
    });

    cy.on('tap', (evt) => {
      if (evt.target === cy) {
        setSelectedNode(null);
      }
    });

    cyRef.current = cy;

    return () => {
      cy.destroy();
    };
  }, [nodes, arcs]);

  return (
    <div className="graph-view">
      <div className="graph-header">
        <h1>Architecture Dependency Graph — ADG-M</h1>
        {loading && <span className="status">Loading...</span>}
        {error && <span className="status error">{error}</span>}
      </div>

      <div className="graph-container" ref={containerRef} />

      {selectedNode && (
        <NodeDetail nodeId={selectedNode} onClose={() => setSelectedNode(null)} />
      )}
    </div>
  );
};

// ============================================================================
// NodeDetail Sidebar
// ============================================================================

interface NodeDetailProps {
  nodeId: string;
  onClose: () => void;
}

const NodeDetail: React.FC<NodeDetailProps> = ({ nodeId, onClose }) => {
  const [node, setNode] = useState<any>(null);
  const [spofData, setSpofData] = useState<any>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    const load = async () => {
      try {
        setLoading(true);
        const nodeResp = await fetch(`/api/graph/nodes/${nodeId}`);
        const nodeData = await nodeResp.json();
        setNode(nodeData);

        const spofResp = await fetch(`/api/graph/nodes/${nodeId}/spof`);
        const spofData = await spofResp.json();
        setSpofData(spofData);
      } catch (err) {
        console.error('Failed to load node detail:', err);
      } finally {
        setLoading(false);
      }
    };
    load();
  }, [nodeId]);

  return (
    <div className="node-detail">
      <button className="close-btn" onClick={onClose}>✕</button>

      {loading ? (
        <p>Loading...</p>
      ) : (
        <>
          <h2>{node?.name}</h2>
          <div className="detail-field">
            <label>Type:</label>
            <span>{node?.type}</span>
          </div>
          <div className="detail-field">
            <label>Criticality:</label>
            <span className={`criticality ${node?.criticality?.toLowerCase()}`}>
              {node?.criticality}
            </span>
          </div>
          <div className="detail-field">
            <label>Business Value:</label>
            <span>{node?.businessValue}</span>
          </div>
          {spofData?.isSPOF && (
            <div className="detail-field alert">
              <label>🚨 Single Point of Failure</label>
              <span>Betweenness: {spofData.betweenness.toFixed(2)}</span>
            </div>
          )}
          <div className="detail-field">
            <label>Cluster:</label>
            <span>{spofData?.cluster || 'N/A'}</span>
          </div>

          <div className="actions">
            <button className="btn-primary">Qualify</button>
            <button className="btn-secondary">View ADR</button>
          </div>
        </>
      )}
    </div>
  );
};

export default GraphView;
