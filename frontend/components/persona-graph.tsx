"use client";

import React, { useRef, useState, useMemo } from "react";
import type { GraphData, GraphNode, GraphEdge } from "@/lib/api";

type PersonaGraphProps = {
  data: GraphData | null;
  selectedEntity: string | null;
  onSelectEntity: (entityName: string, entityType: string) => void;
  onSelectRelationship?: (source: string, relation: string, target: string) => void;
  loading?: boolean;
};

type SimNode = GraphNode & {
  x: number;
  y: number;
  vx: number;
  vy: number;
  radius: number;
};

type SimEdge = GraphEdge & {
  sourceNode: SimNode;
  targetNode: SimNode;
};

function computeForceLayout(
  data: GraphData | null,
  width: number,
  height: number
): { nodes: SimNode[]; edges: SimEdge[] } {
  if (!data || !data.nodes.length) {
    return { nodes: [], edges: [] };
  }

  const initialNodes: SimNode[] = data.nodes.map((n, idx) => {
    const angle = (idx / data.nodes.length) * 2 * Math.PI;
    const dist = 120 + ((idx * 37) % 80);
    const radius = n.type === "person" ? 24 : n.type === "organization" ? 22 : 18;
    return {
      ...n,
      x: width / 2 + Math.cos(angle) * dist,
      y: height / 2 + Math.sin(angle) * dist,
      vx: 0,
      vy: 0,
      radius,
    };
  });

  const nodeMap = new Map(initialNodes.map((n) => [n.id.toLowerCase(), n]));

  const validEdges: SimEdge[] = [];
  for (const e of data.edges) {
    const s = nodeMap.get(e.source.toLowerCase());
    const t = nodeMap.get(e.target.toLowerCase());
    if (s && t && s !== t) {
      validEdges.push({
        ...e,
        sourceNode: s,
        targetNode: t,
      });
    }
  }

  // Force simulation iterations
  const iterations = 80;
  for (let it = 0; it < iterations; it++) {
    for (let i = 0; i < initialNodes.length; i++) {
      for (let j = i + 1; j < initialNodes.length; j++) {
        const n1 = initialNodes[i];
        const n2 = initialNodes[j];
        const dx = n2.x - n1.x;
        const dy = n2.y - n1.y;
        const distSq = dx * dx + dy * dy || 1;
        const dist = Math.sqrt(distSq);
        if (dist < 220) {
          const force = (220 - dist) / (dist * 12);
          n1.vx -= dx * force;
          n1.vy -= dy * force;
          n2.vx += dx * force;
          n2.vy += dy * force;
        }
      }
    }

    const targetDist = 130;
    for (const edge of validEdges) {
      const dx = edge.targetNode.x - edge.sourceNode.x;
      const dy = edge.targetNode.y - edge.sourceNode.y;
      const dist = Math.sqrt(dx * dx + dy * dy) || 1;
      const force = (dist - targetDist) * 0.05;
      const fx = (dx / dist) * force;
      const fy = (dy / dist) * force;
      edge.sourceNode.vx += fx;
      edge.sourceNode.vy += fy;
      edge.targetNode.vx -= fx;
      edge.targetNode.vy -= fy;
    }

    for (const n of initialNodes) {
      n.vx += (width / 2 - n.x) * 0.01;
      n.vy += (height / 2 - n.y) * 0.01;
      n.x += n.vx * 0.6;
      n.y += n.vy * 0.6;
      n.vx *= 0.5;
      n.vy *= 0.5;
      n.x = Math.max(50, Math.min(width - 50, n.x));
      n.y = Math.max(50, Math.min(height - 50, n.y));
    }
  }

  return { nodes: initialNodes, edges: validEdges };
}

export function PersonaGraph({
  data,
  selectedEntity,
  onSelectEntity,
  onSelectRelationship,
  loading = false,
}: PersonaGraphProps) {
  const svgRef = useRef<SVGSVGElement | null>(null);
  const [filterType, setFilterType] = useState<string>("all");
  const [zoom, setZoom] = useState<number>(1);
  const [pan, setPan] = useState<{ x: number; y: number }>({ x: 0, y: 0 });
  const [isPanning, setIsPanning] = useState(false);
  const [dragStart, setDragStart] = useState<{ x: number; y: number }>({ x: 0, y: 0 });
  const [draggedNode, setDraggedNode] = useState<string | null>(null);
  const [draggedPositions, setDraggedPositions] = useState<Record<string, { x: number; y: number }>>({});
  const [hoveredNode, setHoveredNode] = useState<string | null>(null);
  const [hoveredEdge, setHoveredEdge] = useState<string | null>(null);

  const width = 800;
  const height = 500;

  const { nodes: simNodes, edges: simEdges } = useMemo(
    () => computeForceLayout(data, width, height),
    [data]
  );

  const handleMouseDownNode = (e: React.MouseEvent, nodeId: string) => {
    e.stopPropagation();
    setDraggedNode(nodeId);
  };

  const handleMouseMove = (e: React.MouseEvent) => {
    if (draggedNode) {
      const rect = svgRef.current?.getBoundingClientRect();
      if (!rect) return;
      const mouseX = (e.clientX - rect.left - pan.x) / zoom;
      const mouseY = (e.clientY - rect.top - pan.y) / zoom;

      setDraggedPositions((prev) => ({
        ...prev,
        [draggedNode]: { x: mouseX, y: mouseY },
      }));
    } else if (isPanning) {
      setPan({
        x: e.clientX - dragStart.x,
        y: e.clientY - dragStart.y,
      });
    }
  };

  const handleMouseUp = () => {
    setDraggedNode(null);
    setIsPanning(false);
  };

  const handleStartPan = (e: React.MouseEvent) => {
    if (e.button === 0 && !draggedNode) {
      setIsPanning(true);
      setDragStart({ x: e.clientX - pan.x, y: e.clientY - pan.y });
    }
  };

  const handleZoomIn = () => setZoom((z) => Math.min(2.5, z + 0.2));
  const handleZoomOut = () => setZoom((z) => Math.max(0.4, z - 0.2));
  const handleReset = () => {
    setZoom(1);
    setPan({ x: 0, y: 0 });
    setDraggedPositions({});
  };

  const filteredNodes = useMemo(() => {
    if (filterType === "all") return simNodes;
    return simNodes.filter((n) => n.type === filterType);
  }, [simNodes, filterType]);

  const visibleNodeIds = useMemo(
    () => new Set(filteredNodes.map((n) => n.id.toLowerCase())),
    [filteredNodes]
  );

  const filteredEdges = useMemo(() => {
    return simEdges.filter(
      (e) =>
        visibleNodeIds.has(e.sourceNode.id.toLowerCase()) &&
        visibleNodeIds.has(e.targetNode.id.toLowerCase())
    );
  }, [simEdges, visibleNodeIds]);

  const getNodeColor = (type: string, isSelected: boolean) => {
    if (isSelected) return "#0f766e";
    switch (type) {
      case "person":
        return "#234e38";
      case "organization":
        return "#1e3a8a";
      case "role":
        return "#9a3412";
      case "project":
        return "#581c87";
      default:
        return "#374151";
    }
  };

  if (loading) {
    return (
      <div className="persona-graph-container is-loading" role="status">
        <span className="state-spinner" aria-hidden="true" />
        <p>Analyzing entity relationships and rendering graph…</p>
      </div>
    );
  }

  if (!data || !data.nodes.length) {
    return (
      <div className="persona-graph-container is-empty">
        <p className="graph-empty-title">No entity relationships detected yet</p>
        <p className="graph-empty-sub">
          Upload documents mentioning people, organizations, roles, and teams to explore the interactive Persona Graph.
        </p>
      </div>
    );
  }

  return (
    <div className="persona-graph-container">
      <div className="graph-toolbar">
        <div className="graph-filters" role="group" aria-label="Filter entity types">
          <button
            type="button"
            className={`graph-filter-chip ${filterType === "all" ? "is-active" : ""}`}
            onClick={() => setFilterType("all")}
          >
            All ({simNodes.length})
          </button>
          <button
            type="button"
            className={`graph-filter-chip ${filterType === "person" ? "is-active" : ""}`}
            onClick={() => setFilterType("person")}
          >
            People
          </button>
          <button
            type="button"
            className={`graph-filter-chip ${filterType === "organization" ? "is-active" : ""}`}
            onClick={() => setFilterType("organization")}
          >
            Orgs
          </button>
          <button
            type="button"
            className={`graph-filter-chip ${filterType === "project" ? "is-active" : ""}`}
            onClick={() => setFilterType("project")}
          >
            Projects
          </button>
        </div>
        <div className="graph-controls">
          <button type="button" onClick={handleZoomIn} title="Zoom in" aria-label="Zoom in">
            +
          </button>
          <button type="button" onClick={handleZoomOut} title="Zoom out" aria-label="Zoom out">
            −
          </button>
          <button type="button" onClick={handleReset} title="Reset view" aria-label="Reset view">
            ⟲
          </button>
        </div>
      </div>

      <svg
        ref={svgRef}
        className="graph-canvas"
        viewBox={`0 0 ${width} ${height}`}
        onMouseDown={handleStartPan}
        onMouseMove={handleMouseMove}
        onMouseUp={handleMouseUp}
      >
        <defs>
          <marker
            id="arrowhead"
            viewBox="0 0 10 10"
            refX="26"
            refY="5"
            markerWidth="6"
            markerHeight="6"
            orient="auto-start-reverse"
          >
            <path d="M 0 1 L 10 5 L 0 9 z" fill="#8898aa" />
          </marker>
          <marker
            id="arrowhead-highlight"
            viewBox="0 0 10 10"
            refX="26"
            refY="5"
            markerWidth="6"
            markerHeight="6"
            orient="auto-start-reverse"
          >
            <path d="M 0 1 L 10 5 L 0 9 z" fill="#0f766e" />
          </marker>
        </defs>

        <g transform={`translate(${pan.x}, ${pan.y}) scale(${zoom})`}>
          {/* Edges */}
          {filteredEdges.map((edge) => {
            const isEdgeHovered = hoveredEdge === edge.id;
            const isConnectedToSelected =
              Boolean(selectedEntity) &&
              (edge.sourceNode.label.toLowerCase() === selectedEntity?.toLowerCase() ||
                edge.targetNode.label.toLowerCase() === selectedEntity?.toLowerCase());
            const strokeColor = isEdgeHovered || isConnectedToSelected ? "#0f766e" : "#b0bec5";
            const strokeWidth = isEdgeHovered || isConnectedToSelected ? 2.5 : 1.5;

            const sX = draggedPositions[edge.sourceNode.id]?.x ?? edge.sourceNode.x;
            const sY = draggedPositions[edge.sourceNode.id]?.y ?? edge.sourceNode.y;
            const tX = draggedPositions[edge.targetNode.id]?.x ?? edge.targetNode.x;
            const tY = draggedPositions[edge.targetNode.id]?.y ?? edge.targetNode.y;

            const midX = (sX + tX) / 2;
            const midY = (sY + tY) / 2;

            return (
              <g
                key={edge.id}
                className="graph-edge-group"
                onMouseEnter={() => setHoveredEdge(edge.id)}
                onMouseLeave={() => setHoveredEdge(null)}
                onClick={() =>
                  onSelectRelationship?.(
                    edge.sourceNode.label,
                    edge.relation,
                    edge.targetNode.label
                  )
                }
              >
                <line
                  x1={sX}
                  y1={sY}
                  x2={tX}
                  y2={tY}
                  stroke={strokeColor}
                  strokeWidth={strokeWidth}
                  markerEnd={
                    isEdgeHovered || isConnectedToSelected
                      ? "url(#arrowhead-highlight)"
                      : "url(#arrowhead)"
                  }
                />
                <rect
                  x={midX - edge.relation.length * 3.5}
                  y={midY - 8}
                  width={edge.relation.length * 7}
                  height={16}
                  rx={4}
                  fill="#f4f6f8"
                  stroke={strokeColor}
                  strokeWidth={0.8}
                  className="edge-label-bg"
                />
                <text
                  x={midX}
                  y={midY + 3.5}
                  textAnchor="middle"
                  className="edge-label-text"
                  fontSize="8.5"
                  fill="#475569"
                >
                  {edge.relation}
                </text>
              </g>
            );
          })}

          {/* Nodes */}
          {filteredNodes.map((node) => {
            const isSelected =
              selectedEntity?.toLowerCase() === node.label.toLowerCase() ||
              (node.aliases && node.aliases.some((a) => a.toLowerCase() === selectedEntity?.toLowerCase()));
            const isHovered = hoveredNode === node.id;
            const fillColor = getNodeColor(node.type, Boolean(isSelected));
            const nodeRadius = node.radius + (isHovered || isSelected ? 4 : 0);

            const nX = draggedPositions[node.id]?.x ?? node.x;
            const nY = draggedPositions[node.id]?.y ?? node.y;

            return (
              <g
                key={node.id}
                className={`graph-node-group ${isSelected ? "is-selected" : ""}`}
                transform={`translate(${nX}, ${nY})`}
                onMouseDown={(e) => handleMouseDownNode(e, node.id)}
                onMouseEnter={() => setHoveredNode(node.id)}
                onMouseLeave={() => setHoveredNode(null)}
                onClick={(e) => {
                  e.stopPropagation();
                  onSelectEntity(node.label, node.type);
                }}
              >
                <circle
                  r={nodeRadius}
                  fill={fillColor}
                  stroke={isSelected ? "#14b8a6" : isHovered ? "#64748b" : "#ffffff"}
                  strokeWidth={isSelected ? 3 : 2}
                  className="node-circle"
                />
                <text
                  textAnchor="middle"
                  dy=".3em"
                  fill="#ffffff"
                  fontSize={node.type === "person" ? "10" : "9"}
                  fontWeight="600"
                  pointerEvents="none"
                >
                  {node.label.slice(0, 3).toUpperCase()}
                </text>
                <text
                  y={nodeRadius + 12}
                  textAnchor="middle"
                  className="node-label-caption"
                  fontSize="9.5"
                  fontWeight="600"
                  fill="#1e293b"
                >
                  {node.label}
                </text>
                {node.type !== "person" && (
                  <text
                    y={nodeRadius + 22}
                    textAnchor="middle"
                    className="node-type-caption"
                    fontSize="7.5"
                    fill="#64748b"
                    style={{ textTransform: "capitalize" }}
                  >
                    {node.type}
                  </text>
                )}
              </g>
            );
          })}
        </g>
      </svg>
      <div className="graph-footer-hint">
        Click any persona or entity node to scope chat questions. Drag nodes to explore the network.
      </div>
    </div>
  );
}
