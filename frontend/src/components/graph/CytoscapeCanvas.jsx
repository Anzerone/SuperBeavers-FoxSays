'use client';

import cytoscape from 'cytoscape';
import fcose from 'cytoscape-fcose';
import { useEffect, useRef } from 'react';

let _fcoseAvailable = false;
if (typeof window !== 'undefined') {
  try { cytoscape.use(fcose); _fcoseAvailable = true; }
  catch (e) { console.warn('[graph] fcose unavailable, falling back to cose:', e); }
}

function _runLayout(cy) {
  // Небольшие графы «сваливаются в кучу», если nodeRepulsion слишком мал.
  // Даём геометрии больше воздуха: repulsion зависит от плотности связей.
  const n = Math.max(1, cy.nodes().length);
  const e = Math.max(1, cy.edges().length);
  const density = e / n;
  const opts = _fcoseAvailable
    ? {
        name: 'fcose', quality: 'proof',
        animate: true, animationDuration: 500,
        nodeRepulsion: 20000 + Math.round(density * 8000),
        idealEdgeLength: 140,
        nodeSeparation: 160,
        edgeElasticity: 0.35,
        gravity: 0.25,
        gravityRange: 3.8,
        randomize: true,
        packComponents: true,
        uniformNodeDimensions: false,
        tile: true, tilingPaddingHorizontal: 40, tilingPaddingVertical: 40,
      }
    : {
        name: 'cose', animate: true,
        nodeRepulsion: 30000, idealEdgeLength: 140,
        gravity: 60, initialTemp: 500,
      };
  try {
    const l = cy.layout(opts);
    l.one('layoutstop', () => {
      try {
        cy.resize();
        cy.fit(cy.elements(), 50);
      } catch (_) {}
    });
    l.run();
  } catch (err) {
    console.warn('[graph] layout failed, using grid:', err);
    cy.layout({ name: 'grid', padding: 40 }).run();
    try { cy.fit(cy.elements(), 50); } catch (_) {}
  }
}

const NODE_STYLES = {
  experiment: { color: '#1D57A6', shape: 'ellipse',        size: 26 },
  material:   { color: '#E30613', shape: 'round-rectangle', size: 24 },
  property:   { color: '#2E7D32', shape: 'diamond',        size: 22 },
  mode:       { color: '#7B1FA2', shape: 'hexagon',        size: 22 },
  equipment:  { color: '#607D8B', shape: 'triangle',       size: 22 },
  author:     { color: '#F9A825', shape: 'round-rectangle', size: 20 },
  team:       { color: '#F57C00', shape: 'pentagon',       size: 22 },
  document:   { color: '#5E35B2', shape: 'round-rectangle', size: 22 },
  conclusion: { color: '#C62828', shape: 'ellipse',        size: 20 },
  tag:        { color: '#546E7A', shape: 'round-rectangle', size: 18 },
};

const EDGE_COLORS = {
  USED_MATERIAL: '#E30613', USED_MODE: '#7B1FA2', USED_EQUIPMENT: '#607D8B',
  MEASURED: '#2E7D32', CONDUCTED_BY: '#F9A825', DOCUMENTED_IN: '#5E35B2',
  RESULTED_IN: '#C62828', SIMILAR_TO: '#1D57A6', MENTIONS: '#546E7A',
  CONFIRMS: '#2E7D32', CONTRADICTS: '#E30613', TAGGED_WITH: '#546E7A',
  MEMBER_OF: '#F57C00', HAS_PARAM: '#7B1FA2',
};

function _cleanLabel(n) {
  let s = n.short_title || n.title || '';
  // «[слайд 7] Проблема гидрометаллургической переработки…» → «Проблема гидро…»
  s = s.replace(/^\[(слайд|стр\.?|page)[^\]]*\]\s*/i, '');
  // Ведущие маркеры типа «1)», «5.30», «3] », «4] ЭВОЛЮЦИЯ»
  s = s.replace(/^\d+[.)\]]\s+/, '');
  s = s.trim();
  if (!s) return '(без названия)';
  return s.length > 40 ? s.slice(0, 38) + '…' : s;
}

function buildElements(nodes, edges) {
  const cyNodes = nodes.map((n) => ({
    data: {
      id: n.id,
      label: _cleanLabel(n),
      type: n.type, isAnchor: !!n.is_anchor, raw: n,
    },
  }));
  const cyEdges = edges
    .map((e, i) => ({
      data: {
        id: `e_${i}_${e.source}_${e.target}_${e.type}`,
        source: e.source, target: e.target,
        edgeType: e.type, weight: e.weight || 1,
      },
    }))
    .filter((e) =>
      cyNodes.find((n) => n.data.id === e.data.source) &&
      cyNodes.find((n) => n.data.id === e.data.target)
    );
  return [...cyNodes, ...cyEdges];
}

function buildStyle() {
  const s = [
    { selector: 'node', style: {
      label: 'data(label)',
      'font-size': 10, 'font-family': 'Inter, system-ui, sans-serif',
      color: '#E1E5EB',
      'text-outline-color': '#050F22', 'text-outline-width': 2.5,
      'text-valign': 'bottom', 'text-margin-y': 4,
      'text-max-width': '100px', 'text-wrap': 'ellipsis',
      'border-width': 2, 'border-color': 'rgba(255,255,255,0.15)',
      'transition-property': 'border-width, border-color', 'transition-duration': '0.15s',
    }},
    { selector: 'node:selected', style: { 'border-color': '#fff', 'border-width': 3 }},
    { selector: 'node[?isAnchor]', style: {
      'border-width': 3, 'border-color': '#E30613',
      'font-weight': 700,
    }},
    { selector: 'edge', style: {
      width: 1.4, 'curve-style': 'bezier', opacity: 0.6,
      'line-color': '#4A5A6B', 'target-arrow-color': '#4A5A6B',
      'target-arrow-shape': 'triangle', 'arrow-scale': 0.7,
    }},
    // Подсветка связных при клике: неучаствующие узлы/рёбра тускнеют, связанные — ярче.
    { selector: '.dim',       style: { opacity: 0.15 } },
    { selector: 'edge.dim',   style: { opacity: 0.05 } },
    { selector: 'node.hl',    style: { 'border-color': '#fbbf24', 'border-width': 3 } },
    { selector: 'edge.hl',    style: { opacity: 1, width: 2.2 } },
  ];
  for (const [type, cfg] of Object.entries(NODE_STYLES)) {
    s.push({
      selector: `node[type = "${type}"]`,
      style: { 'background-color': cfg.color, shape: cfg.shape, width: cfg.size, height: cfg.size },
    });
  }
  for (const [t, c] of Object.entries(EDGE_COLORS)) {
    s.push({
      selector: `edge[edgeType = "${t}"]`,
      style: { 'line-color': c, 'target-arrow-color': c, opacity: 0.75 },
    });
  }
  s.push({
    selector: 'edge[edgeType = "CONTRADICTS"]',
    style: { 'line-style': 'dashed', width: 2 },
  });
  return s;
}

export default function CytoscapeCanvas({ nodes = [], edges = [], onSelectNode }) {
  const containerRef = useRef(null);
  const cyRef = useRef(null);

  useEffect(() => {
    if (!containerRef.current) return;
    if (!cyRef.current) {
      cyRef.current = cytoscape({
        container: containerRef.current,
        style: buildStyle(),
        elements: buildElements(nodes, edges),
        wheelSensitivity: 0.25, minZoom: 0.1, maxZoom: 3,
      });
      cyRef.current.on('tap', 'node', (e) => {
        const cy = cyRef.current;
        const node = e.target;
        cy.elements().addClass('dim').removeClass('hl');
        const nb = node.closedNeighborhood();
        nb.removeClass('dim').addClass('hl');
        onSelectNode?.(node.data().raw);
      });
      cyRef.current.on('tap', (e) => {
        if (e.target === cyRef.current) {
          cyRef.current.elements().removeClass('dim').removeClass('hl');
          onSelectNode?.(null);
        }
      });
      _runLayout(cyRef.current);
    } else {
      cyRef.current.elements().remove();
      cyRef.current.add(buildElements(nodes, edges));
      _runLayout(cyRef.current);
    }
  }, [nodes, edges, onSelectNode]);

  useEffect(() => {
    if (!containerRef.current || typeof ResizeObserver === 'undefined') return;
    const ro = new ResizeObserver(() => {
      if (cyRef.current) {
        cyRef.current.resize();
        try { cyRef.current.fit(cyRef.current.elements(), 40); } catch (_) {}
      }
    });
    ro.observe(containerRef.current);
    return () => ro.disconnect();
  }, []);

  useEffect(() => () => { if (cyRef.current) { cyRef.current.destroy(); cyRef.current = null; } }, []);

  return <div ref={containerRef} className="h-full w-full bg-surface-darker" />;
}
