'use client';

import React, { useEffect, useRef, useState, useCallback } from 'react';
import * as THREE from 'three';
import { OrbitControls } from 'three/examples/jsm/controls/OrbitControls.js';

import {
  DependencyGraphResponse,
  GraphFilterOptions,
  Node3D,
} from '../../types/graph';
import {
  transformDependencyGraph,
  filterGraph,
  CYCLE_HIGHLIGHT_COLOR,
} from '../../lib/graph-layout';

export interface ArchitectureCanvas3DProps {
  graphData?: DependencyGraphResponse | null;
  filters?: GraphFilterOptions;
  selectedNodeId?: string | null;
  onSelectNode?: (node: Node3D | null) => void;
  className?: string;
}

const DEFAULT_CAMERA_POS = new THREE.Vector3(0, 180, 420);
const DEFAULT_LOOK_TARGET = new THREE.Vector3(0, 0, 0);

export function ArchitectureCanvas3D({
  graphData,
  filters = {},
  selectedNodeId,
  onSelectNode,
  className = '',
}: ArchitectureCanvas3DProps) {
  const containerRef = useRef<HTMLDivElement>(null);
  const rendererRef = useRef<THREE.WebGLRenderer | null>(null);
  const sceneRef = useRef<THREE.Scene | null>(null);
  const cameraRef = useRef<THREE.PerspectiveCamera | null>(null);
  const controlsRef = useRef<OrbitControls | null>(null);
  const animFrameIdRef = useRef<number | null>(null);

  // Store interactive mesh references for raycasting
  const nodeMeshesMapRef = useRef<Map<string, THREE.Mesh>>(new Map());
  const meshToNodeDataRef = useRef<Map<THREE.Object3D, Node3D>>(new Map());
  const selectionRingRef = useRef<THREE.Mesh | null>(null);

  const [hoveredNode, setHoveredNode] = useState<Node3D | null>(null);

  // Camera Reset Handler
  const resetCamera = useCallback(() => {
    if (cameraRef.current && controlsRef.current) {
      cameraRef.current.position.copy(DEFAULT_CAMERA_POS);
      controlsRef.current.target.copy(DEFAULT_LOOK_TARGET);
      controlsRef.current.update();
    }
  }, []);

  // Initialize Three.js scene, camera, lights, controls, and renderer
  useEffect(() => {
    if (!containerRef.current) return;

    const container = containerRef.current;
    const width = container.clientWidth || 800;
    const height = container.clientHeight || 600;

    // 1. Scene setup
    const scene = new THREE.Scene();
    scene.background = new THREE.Color(0x09090b); // zinc-950 dark background
    sceneRef.current = scene;

    // Subtle coordinate grid helper for 3D orientation
    const gridHelper = new THREE.GridHelper(800, 40, 0x27272a, 0x18181b);
    gridHelper.position.y = -80;
    scene.add(gridHelper);

    // 2. Camera setup
    const camera = new THREE.PerspectiveCamera(45, width / height, 1, 4000);
    camera.position.copy(DEFAULT_CAMERA_POS);
    cameraRef.current = camera;

    // 3. Renderer setup
    const renderer = new THREE.WebGLRenderer({ antialias: true, alpha: false });
    renderer.setSize(width, height);
    renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
    renderer.toneMapping = THREE.ACESFilmicToneMapping;
    renderer.toneMappingExposure = 1.2;
    rendererRef.current = renderer;

    container.appendChild(renderer.domElement);

    // 4. OrbitControls setup
    const controls = new OrbitControls(camera, renderer.domElement);
    controls.enableDamping = true;
    controls.dampingFactor = 0.05;
    controls.minDistance = 20;
    controls.maxDistance = 2000;
    controls.target.copy(DEFAULT_LOOK_TARGET);
    controlsRef.current = controls;

    // 5. Lighting
    const ambientLight = new THREE.AmbientLight(0xffffff, 0.75);
    scene.add(ambientLight);

    const dirLight1 = new THREE.DirectionalLight(0xffffff, 1.2);
    dirLight1.position.set(200, 400, 300);
    scene.add(dirLight1);

    const dirLight2 = new THREE.DirectionalLight(0x38bdf8, 0.6);
    dirLight2.position.set(-300, -200, -200);
    scene.add(dirLight2);

    // Selection ring highlight mesh
    const ringGeo = new THREE.RingGeometry(14, 17, 32);
    const ringMat = new THREE.MeshBasicMaterial({
      color: 0x38bdf8,
      side: THREE.DoubleSide,
      transparent: true,
      opacity: 0.85,
    });
    const selectionRing = new THREE.Mesh(ringGeo, ringMat);
    selectionRing.visible = false;
    scene.add(selectionRing);
    selectionRingRef.current = selectionRing;

    // 6. Animation loop
    const animate = () => {
      animFrameIdRef.current = requestAnimationFrame(animate);
      controls.update();

      // Orient selection ring towards camera
      if (selectionRing.visible && camera) {
        selectionRing.quaternion.copy(camera.quaternion);
      }

      renderer.render(scene, camera);
    };
    animate();

    // 7. Resize listener
    const handleResize = () => {
      if (!container || !renderer || !camera) return;
      const w = container.clientWidth;
      const h = container.clientHeight;
      camera.aspect = w / h;
      camera.updateProjectionMatrix();
      renderer.setSize(w, h);
    };

    window.addEventListener('resize', handleResize);

    return () => {
      window.removeEventListener('resize', handleResize);
      if (animFrameIdRef.current) {
        cancelAnimationFrame(animFrameIdRef.current);
      }
      controls.dispose();
      renderer.dispose();
      if (renderer.domElement.parentElement === container) {
        container.removeChild(renderer.domElement);
      }
      scene.clear();
    };
  }, []);

  // Update 3D graph nodes and edges when graphData or filters change
  useEffect(() => {
    const scene = sceneRef.current;
    if (!scene) return;

    // Clean up existing graph object groups
    const existingGraphGroup = scene.getObjectByName('graphObjectsGroup');
    if (existingGraphGroup) {
      scene.remove(existingGraphGroup);
      existingGraphGroup.traverse((obj) => {
        if (obj instanceof THREE.Mesh) {
          obj.geometry?.dispose();
          if (Array.isArray(obj.material)) {
            obj.material.forEach((m) => m.dispose());
          } else {
            obj.material?.dispose();
          }
        }
      });
    }

    nodeMeshesMapRef.current.clear();
    meshToNodeDataRef.current.clear();

    if (!graphData || !graphData.nodes || graphData.nodes.length === 0) {
      return;
    }

    // 1. Transform raw data and apply active filters
    const transformed = transformDependencyGraph(graphData);
    const filtered = filterGraph(transformed, filters);

    const graphGroup = new THREE.Group();
    graphGroup.name = 'graphObjectsGroup';

    // 2. Build 3D Node Meshes
    for (const node of filtered.nodes) {
      let geometry: THREE.BufferGeometry;

      switch (node.node_type) {
        case 'class':
          geometry = new THREE.OctahedronGeometry(node.size * 0.9);
          break;
        case 'file':
          geometry = new THREE.BoxGeometry(node.size * 1.4, node.size * 1.4, node.size * 1.4);
          break;
        case 'external_package':
          geometry = new THREE.CylinderGeometry(node.size * 0.8, node.size * 0.8, node.size * 0.5, 16);
          break;
        case 'method':
          geometry = new THREE.DodecahedronGeometry(node.size * 0.8);
          break;
        case 'function':
        case 'async_function':
        default:
          geometry = new THREE.SphereGeometry(node.size * 0.8, 16, 16);
          break;
      }

      const colorHex = node.inCycle
        ? parseInt(CYCLE_HIGHLIGHT_COLOR.replace('#', '0x'), 16)
        : parseInt(node.color.replace('#', '0x'), 16);

      const material = new THREE.MeshStandardMaterial({
        color: colorHex,
        roughness: 0.35,
        metalness: node.inCycle ? 0.8 : 0.2,
        emissive: node.inCycle ? colorHex : 0x000000,
        emissiveIntensity: node.inCycle ? 0.45 : 0.0,
      });

      const mesh = new THREE.Mesh(geometry, material);
      mesh.position.set(node.position.x, node.position.y, node.position.z);
      mesh.userData = { nodeId: node.id };

      graphGroup.add(mesh);
      nodeMeshesMapRef.current.set(node.id, mesh);
      meshToNodeDataRef.current.set(mesh, node);
    }

    // 3. Build 3D Edge Lines & Directed Indicators
    const nodePosMap = new Map<string, THREE.Vector3>();
    for (const node of filtered.nodes) {
      nodePosMap.set(
        node.id,
        new THREE.Vector3(node.position.x, node.position.y, node.position.z)
      );
    }

    for (const edge of filtered.edges) {
      const srcPos = nodePosMap.get(edge.source_id);
      const tgtPos = nodePosMap.get(edge.target_id);
      if (!srcPos || !tgtPos) continue;

      const edgeColorHex = edge.inCycle
        ? parseInt(CYCLE_HIGHLIGHT_COLOR.replace('#', '0x'), 16)
        : parseInt(edge.color.replace('#', '0x'), 16);

      // Line geometry between source and target
      const points = [srcPos, tgtPos];
      const lineGeo = new THREE.BufferGeometry().setFromPoints(points);

      const lineMat = new THREE.LineBasicMaterial({
        color: edgeColorHex,
        transparent: true,
        opacity: edge.opacity,
        linewidth: edge.inCycle ? 2 : 1,
      });

      const line = new THREE.Line(lineGeo, lineMat);
      graphGroup.add(line);

      // Add directional arrow indicator near target node
      const dir = new THREE.Vector3().subVectors(tgtPos, srcPos).normalize();
      const dist = srcPos.distanceTo(tgtPos);

      if (dist > 15) {
        const arrowLength = Math.min(8, dist * 0.15);
        const arrowHeadPos = tgtPos.clone().sub(dir.clone().multiplyScalar(12));

        const arrowGeo = new THREE.ConeGeometry(2.5, arrowLength, 8);
        const arrowMat = new THREE.MeshBasicMaterial({
          color: edgeColorHex,
          transparent: true,
          opacity: Math.min(1.0, edge.opacity + 0.2),
        });

        const arrowMesh = new THREE.Mesh(arrowGeo, arrowMat);
        arrowMesh.position.copy(arrowHeadPos);
        arrowMesh.quaternion.setFromUnitVectors(new THREE.Vector3(0, 1, 0), dir);

        graphGroup.add(arrowMesh);
      }
    }

    scene.add(graphGroup);
  }, [graphData, filters]);

  // Update Selection Ring Position when selectedNodeId changes
  useEffect(() => {
    const ring = selectionRingRef.current;
    if (!ring) return;

    if (!selectedNodeId) {
      ring.visible = false;
      return;
    }

    const mesh = nodeMeshesMapRef.current.get(selectedNodeId);
    if (mesh) {
      ring.position.copy(mesh.position);
      ring.visible = true;
    } else {
      ring.visible = false;
    }
  }, [selectedNodeId]);

  // Raycasting & Pointer Interactions (Click selection and Hover tooltip)
  const handlePointerDown = useCallback(
    (e: React.PointerEvent<HTMLDivElement>) => {
      const container = containerRef.current;
      const camera = cameraRef.current;
      if (!container || !camera) return;

      const rect = container.getBoundingClientRect();
      const pointer = new THREE.Vector2(
        ((e.clientX - rect.left) / rect.width) * 2 - 1,
        -((e.clientY - rect.top) / rect.height) * 2 + 1
      );

      const raycaster = new THREE.Raycaster();
      raycaster.setFromCamera(pointer, camera);

      const meshes = Array.from(meshToNodeDataRef.current.keys()) as THREE.Mesh[];
      const intersects = raycaster.intersectObjects(meshes, false);

      if (intersects.length > 0) {
        const hitMesh = intersects[0].object;
        const nodeData = meshToNodeDataRef.current.get(hitMesh);
        if (nodeData && onSelectNode) {
          onSelectNode(nodeData);
        }
      } else {
        if (onSelectNode) {
          onSelectNode(null);
        }
      }
    },
    [onSelectNode]
  );

  const handlePointerMove = useCallback(
    (e: React.PointerEvent<HTMLDivElement>) => {
      const container = containerRef.current;
      const camera = cameraRef.current;
      if (!container || !camera) return;

      const rect = container.getBoundingClientRect();
      const pointer = new THREE.Vector2(
        ((e.clientX - rect.left) / rect.width) * 2 - 1,
        -((e.clientY - rect.top) / rect.height) * 2 + 1
      );

      const raycaster = new THREE.Raycaster();
      raycaster.setFromCamera(pointer, camera);

      const meshes = Array.from(meshToNodeDataRef.current.keys()) as THREE.Mesh[];
      const intersects = raycaster.intersectObjects(meshes, false);

      if (intersects.length > 0) {
        container.style.cursor = 'pointer';
        const hitMesh = intersects[0].object;
        const nodeData = meshToNodeDataRef.current.get(hitMesh);
        setHoveredNode(nodeData || null);
      } else {
        container.style.cursor = 'default';
        setHoveredNode(null);
      }
    },
    []
  );

  return (
    <div
      className={`relative w-full h-full min-h-[500px] overflow-hidden select-none bg-zinc-950 ${className}`}
      onPointerDown={handlePointerDown}
      onPointerMove={handlePointerMove}
    >
      <div ref={containerRef} className="w-full h-full" />

      {/* Floating View Controls (Camera Reset) */}
      <div className="absolute bottom-4 left-4 flex gap-2 z-10 pointer-events-auto">
        <button
          type="button"
          onClick={resetCamera}
          className="px-3 py-1.5 text-xs font-medium rounded bg-zinc-800/90 text-zinc-200 hover:bg-zinc-700 transition border border-zinc-700 shadow-md backdrop-blur-sm"
          title="Reset camera to default view"
        >
          Reset Camera
        </button>
      </div>

      {/* Lightweight Hover Node Tooltip */}
      {hoveredNode && (
        <div className="absolute top-4 left-4 z-10 pointer-events-none px-3 py-2 rounded bg-zinc-900/90 border border-zinc-700 text-xs text-zinc-100 shadow-lg backdrop-blur-sm max-w-sm">
          <div className="font-semibold text-zinc-50 flex items-center gap-1.5">
            <span
              className="inline-block w-2.5 h-2.5 rounded-full"
              style={{ backgroundColor: hoveredNode.color }}
            />
            <span>{hoveredNode.name}</span>
            <span className="text-[10px] px-1.5 py-0.5 rounded bg-zinc-800 text-zinc-400">
              {hoveredNode.node_type}
            </span>
          </div>
          {hoveredNode.file_path && (
            <p className="text-zinc-400 text-[11px] truncate mt-0.5">
              {hoveredNode.file_path}
            </p>
          )}
          {hoveredNode.inCycle && (
            <p className="text-red-400 text-[11px] font-medium mt-1">
              Part of circular dependency
            </p>
          )}
        </div>
      )}
    </div>
  );
}

export default ArchitectureCanvas3D;
