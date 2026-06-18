/**
 * Graph page — interactive force-directed knowledge graph.
 *
 * Features:
 *  - Weight-filtered edges (hide weak links to reduce clutter)
 *  - Community-aware initial layout
 *  - Drag, zoom, pan
 *  - Hover highlight with neighbor emphasis
 *  - High-DPI canvas rendering
 */
async function renderGraphPage(container) {
    container.innerHTML = `
        <div class="space-y-4">
            <div class="flex items-center justify-between flex-wrap gap-2">
                <h2 class="text-2xl font-bold text-white">🕸️ 知识图谱</h2>
                <div class="flex gap-2 items-center flex-wrap">
                    <label class="text-xs text-gray-400 flex items-center gap-1">
                        边权重 ≥
                        <input type="range" id="weight-slider" min="0" max="10" step="0.5" value="4"
                               class="w-20 accent-blue-500" oninput="updateWeightFilter(this.value)">
                        <span id="weight-value" class="w-6 text-gray-300">4.0</span>
                    </label>
                    <button onclick="loadGraph()"
                            class="px-3 py-1.5 bg-gray-700 hover:bg-gray-600 rounded-lg text-sm text-gray-300">
                        🔄 刷新
                    </button>
                    <button onclick="resetGraphView()"
                            class="px-3 py-1.5 bg-gray-700 hover:bg-gray-600 rounded-lg text-sm text-gray-300">
                        🎯 重置
                    </button>
                </div>
            </div>

            <div id="graph-container" class="bg-gray-800 rounded-xl cursor-grab active:cursor-grabbing"
                 style="height: 650px; position: relative; overflow: hidden;">
                <div id="graph-loading" class="flex items-center justify-center h-full absolute inset-0 z-10">
                    <div class="text-gray-400 animate-pulse">加载图谱数据...</div>
                </div>
                <canvas id="graph-canvas" style="display:block;"></canvas>
                <div id="graph-tooltip" class="hidden absolute z-20 pointer-events-none px-3 py-2 rounded-lg
                     bg-gray-900/95 border border-gray-600 text-sm text-white shadow-xl max-w-xs"></div>
            </div>

            <div class="grid grid-cols-1 md:grid-cols-3 gap-4">
                <div class="bg-gray-800 rounded-xl p-4">
                    <div class="text-gray-500 text-sm">节点</div>
                    <div id="graph-node-count" class="text-2xl font-bold text-blue-400">-</div>
                </div>
                <div class="bg-gray-800 rounded-xl p-4">
                    <div class="text-gray-500 text-sm">可见边 / 总边</div>
                    <div id="graph-edge-count" class="text-2xl font-bold text-green-400">-</div>
                </div>
                <div class="bg-gray-800 rounded-xl p-4">
                    <div class="text-gray-500 text-sm">社区</div>
                    <div id="graph-comm-count" class="text-2xl font-bold text-purple-400">-</div>
                </div>
            </div>

            <div id="graph-legend" class="bg-gray-800 rounded-xl p-4"></div>
            <div id="graph-node-detail" class="hidden bg-gray-800 rounded-xl p-4"></div>
        </div>
    `;

    loadGraph();
}

/* ── Globals ─────────────────────────────────────────── */

let graphData = null;
let simNodes = [];
let simEdges = [];     // all edges
let visEdges = [];     // filtered edges currently drawn
let weightThreshold = 4.0;
let nodeMap = {};

// View transform
let viewX = 0, viewY = 0, viewScale = 1;

// Interaction state
let dragNode = null;
let isPanning = false;
let panStart = { x: 0, y: 0, vx: 0, vy: 0 };
let hoverNode = null;
let animFrame = null;

const COMMUNITY_COLORS = [
    '#3b82f6', '#10b981', '#f59e0b', '#ef4444', '#8b5cf6',
    '#ec4899', '#06b6d4', '#84cc16', '#f97316', '#6366f1',
];

/* ── Data loading ────────────────────────────────────── */

async function loadGraph() {
    const loading = document.getElementById('graph-loading');
    if (loading) { loading.style.display = 'flex'; }

    try {
        const resp = await fetch('/api/graph', { credentials: 'include' });
        graphData = await resp.json();

        document.getElementById('graph-node-count').textContent = graphData.nodes.length;
        document.getElementById('graph-edge-count').textContent = `0 / ${graphData.edges.length}`;
        document.getElementById('graph-comm-count').textContent = Object.keys(graphData.communities).length;

        if (loading) loading.style.display = 'none';

        initSimulation(graphData);
        renderLegend(graphData);

        // Auto-focus on a node if navigated from another page (e.g. home page insights)
        if (window.__graphPendingNode) {
            const pendingId = window.__graphPendingNode;
            window.__graphPendingNode = null;  // consume
            const pendingHighlight = window.__graphPendingHighlight || null;
            window.__graphPendingHighlight = null;

            // Wait for simulation to settle a bit, then show detail
            setTimeout(() => {
                // Try to find node by id first, then fall back to label
                let node = simNodes.find(n => n.id === pendingId);
                if (!node) node = simNodes.find(n => n.label === pendingId);
                if (node) {
                    showNodeDetail(node, pendingHighlight);

                    // Scroll the graph container into view
                    const container = document.getElementById('graph-container');
                    if (container) container.scrollIntoView({ behavior: 'smooth', block: 'center' });
                }
            }, 800);
        }
    } catch (e) {
        if (loading) loading.innerHTML = `<div class="text-red-400">加载失败: ${e.message}</div>`;
    }
}

/* ── Simulation setup ────────────────────────────────── */

function initSimulation(data) {
    const canvas = document.getElementById('graph-canvas');
    const container = document.getElementById('graph-container');
    const dpr = window.devicePixelRatio || 1;
    const W = container.offsetWidth;
    const H = container.offsetHeight;
    canvas.width = W * dpr;
    canvas.height = H * dpr;
    canvas.style.width = W + 'px';
    canvas.style.height = H + 'px';

    // Reset view
    viewX = 0; viewY = 0; viewScale = 1;

    if (data.nodes.length === 0) return;

    // Community-aware initial positions: place each community in a cluster
    const commIds = [...new Set(data.nodes.map(n => n.community))];
    const commCenters = {};
    const angleStep = (2 * Math.PI) / Math.max(commIds.length, 1);
    const clusterRadius = Math.min(W, H) * 0.28;
    commIds.forEach((cid, i) => {
        commCenters[cid] = {
            x: W / 2 + Math.cos(angleStep * i - Math.PI / 2) * clusterRadius,
            y: H / 2 + Math.sin(angleStep * i - Math.PI / 2) * clusterRadius,
        };
    });

    simNodes = data.nodes.map(n => {
        const center = commCenters[n.community] || { x: W / 2, y: H / 2 };
        return {
            ...n,
            x: center.x + (Math.random() - 0.5) * 120,
            y: center.y + (Math.random() - 0.5) * 120,
            vx: 0, vy: 0,
            fx: null, fy: null,   // fixed position when dragging
        };
    });

    nodeMap = {};
    simNodes.forEach(n => nodeMap[n.id] = n);

    simEdges = data.edges.filter(e => nodeMap[e.source] && nodeMap[e.target]);

    // Apply weight filter
    updateWeightFilter(weightThreshold, true);

    // Attach interaction listeners
    attachListeners(canvas, container);

    // Pre-compute layout: run 80 iterations synchronously before first render
    precomputeLayout(W, H, 80);

    // Start animated simulation (only for final settling)
    startSimulation(W, H);
}

function updateWeightFilter(val, skipRestart) {
    weightThreshold = parseFloat(val) || 0;
    const el = document.getElementById('weight-value');
    if (el) el.textContent = weightThreshold.toFixed(1);

    visEdges = simEdges.filter(e => e.weight >= weightThreshold);

    const countEl = document.getElementById('graph-edge-count');
    if (countEl && graphData) countEl.textContent = `${visEdges.length} / ${graphData.edges.length}`;

    if (!skipRestart && simNodes.length > 0) {
        const container = document.getElementById('graph-container');
        startSimulation(container.offsetWidth, container.offsetHeight);
    }
}

/* ── Spatial hash for O(n) repulsion ────────────────── */
class SpatialHash {
    constructor(cellSize) { this.cellSize = cellSize; this.cells = new Map(); }
    clear() { this.cells.clear(); }
    hash(x, y) {
        return `${Math.floor(x / this.cellSize)},${Math.floor(y / this.cellSize)}`;
    }
    insert(node) {
        const key = this.hash(node.x, node.y);
        if (!this.cells.has(key)) this.cells.set(key, []);
        this.cells.get(key).push(node);
    }
    query(x, y, radius) {
        const r = Math.max(radius, this.cellSize);
        const cx = Math.floor(x / this.cellSize), cy = Math.floor(y / this.cellSize);
        const range = Math.ceil(r / this.cellSize);
        const nearby = [];
        for (let dx = -range; dx <= range; dx++) {
            for (let dy = -range; dy <= range; dy++) {
                const key = `${cx + dx},${cy + dy}`;
                if (this.cells.has(key)) nearby.push(...this.cells.get(key));
            }
        }
        return nearby;
    }
}

let spatialHash = null;

/* ── Force simulation (animated) ─────────────────────── */

let simAlpha = 1.0;
let simRunning = false;
let lastDrawTime = 0;
let frameSkip = 0;

function precomputeLayout(W, H, iterations) {
    const repStr = 6000, attStr = 0.0008, idealLen = 120, gravity = 0.02, damping = 0.85;
    let alpha = 1.0;
    spatialHash = spatialHash || new SpatialHash(100);
    for (let iter = 0; iter < iterations; iter++) {
        spatialHash.clear();
        for (const n of simNodes) spatialHash.insert(n);
        for (let i = 0; i < simNodes.length; i++) {
            const a = simNodes[i];
            const nearby = spatialHash.query(a.x, a.y, 200);
            for (const b of nearby) {
                if (a === b) continue;
                let dx = b.x - a.x, dy = b.y - a.y;
                let dist2 = dx * dx + dy * dy;
                if (dist2 < 1) dist2 = 1;
                if (dist2 > 40000) continue;
                let dist = Math.sqrt(dist2);
                let force = repStr * alpha / dist2;
                let fx = (dx / dist) * force, fy = (dy / dist) * force;
                a.vx -= fx; a.vy -= fy;
                b.vx += fx; b.vy += fy;
            }
        }
        for (const e of visEdges) {
            const s = nodeMap[e.source], t = nodeMap[e.target];
            if (!s || !t) continue;
            let dx = t.x - s.x, dy = t.y - s.y;
            let dist = Math.sqrt(dx * dx + dy * dy) || 1;
            let force = (dist - idealLen) * attStr * alpha * Math.sqrt(e.weight);
            let fx = (dx / dist) * force, fy = (dy / dist) * force;
            s.vx += fx; s.vy += fy;
            t.vx -= fx; t.vy -= fy;
        }
        const cx = W / 2, cy = H / 2;
        for (const n of simNodes) {
            n.vx += (cx - n.x) * gravity * alpha;
            n.vy += (cy - n.y) * gravity * alpha;
            n.vx *= damping; n.vy *= damping;
            n.x += n.vx; n.y += n.vy;
            const pad = 30;
            if (n.x < pad) { n.x = pad; n.vx *= -0.5; }
            if (n.x > W - pad) { n.x = W - pad; n.vx *= -0.5; }
            if (n.y < pad) { n.y = pad; n.vy *= -0.5; }
            if (n.y > H - pad) { n.y = H - pad; n.vy *= -0.5; }
        }
        alpha *= 0.96;
    }
    simAlpha = alpha;
}

function startSimulation(W, H) {
    simAlpha = 1.0;
    if (!simRunning) {
        simRunning = true;
        tick(W, H);
    }
}

// Pause simulation when tab is hidden to save battery
document.addEventListener('visibilitychange', () => {
    if (document.hidden) {
        if (animFrame) { cancelAnimationFrame(animFrame); animFrame = null; }
        simRunning = false;
    } else if (simAlpha >= 0.001) {
        simRunning = true;
        const container = document.getElementById('graph-container');
        if (container) tick(container.offsetWidth, container.offsetHeight);
    }
});

function tick(W, H) {
    if (simAlpha < 0.001 && !dragNode) {
        simRunning = false;
        // Only redraw if there was a change (hover, drag, etc.)
        if (hoverNode || dragNode) {
            draw();
        }
        return;
    }

    // --- Forces ---
    const repStr = 6000;
    const attStr = 0.0008;
    const idealLen = 120;
    const gravity = 0.02;
    const damping = 0.85;

    // Build spatial hash for O(n) repulsion
    spatialHash = spatialHash || new SpatialHash(100);
    spatialHash.clear();
    for (const n of simNodes) spatialHash.insert(n);

    // Repulsion (spatial-hash-optimized: only nearby nodes)
    for (let i = 0; i < simNodes.length; i++) {
        const a = simNodes[i];
        const nearby = spatialHash.query(a.x, a.y, 200);
        for (const b of nearby) {
            if (a === b) continue;
            let dx = b.x - a.x, dy = b.y - a.y;
            let dist2 = dx * dx + dy * dy;
            if (dist2 < 1) dist2 = 1;
            if (dist2 > 40000) continue; // Skip far nodes (>200px)
            let dist = Math.sqrt(dist2);
            let force = repStr * simAlpha / dist2;
            let fx = (dx / dist) * force;
            let fy = (dy / dist) * force;
            a.vx -= fx; a.vy -= fy;
            b.vx += fx; b.vy += fy;
        }
    }

    // Attraction (visible edges only)
    for (const e of visEdges) {
        const s = nodeMap[e.source], t = nodeMap[e.target];
        if (!s || !t) continue;
        let dx = t.x - s.x, dy = t.y - s.y;
        let dist = Math.sqrt(dx * dx + dy * dy) || 1;
        let force = (dist - idealLen) * attStr * simAlpha * Math.sqrt(e.weight);
        let fx = (dx / dist) * force;
        let fy = (dy / dist) * force;
        s.vx += fx; s.vy += fy;
        t.vx -= fx; t.vy -= fy;
    }

    // Center gravity
    const cx = W / 2, cy = H / 2;
    for (const n of simNodes) {
        n.vx += (cx - n.x) * gravity * simAlpha;
        n.vy += (cy - n.y) * gravity * simAlpha;
    }

    // Integrate
    for (const n of simNodes) {
        if (n.fx !== null) { n.x = n.fx; n.y = n.fy; n.vx = 0; n.vy = 0; continue; }
        n.vx *= damping;
        n.vy *= damping;
        n.x += n.vx;
        n.y += n.vy;
        // Soft bounds
        const pad = 30;
        if (n.x < pad) { n.x = pad; n.vx *= -0.5; }
        if (n.x > W - pad) { n.x = W - pad; n.vx *= -0.5; }
        if (n.y < pad) { n.y = pad; n.vy *= -0.5; }
        if (n.y > H - pad) { n.y = H - pad; n.vy *= -0.5; }
    }

    simAlpha *= 0.96;  // faster cooling for quick layout

    draw();
    animFrame = requestAnimationFrame(() => tick(W, H));
}

/* ── Drawing ─────────────────────────────────────────── */

function draw() {
    const canvas = document.getElementById('graph-canvas');
    if (!canvas) return;
    const ctx = canvas.getContext('2d');
    const dpr = window.devicePixelRatio || 1;
    const W = canvas.width / dpr;
    const H = canvas.height / dpr;

    ctx.save();
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    ctx.clearRect(0, 0, W, H);

    // Apply view transform
    ctx.translate(viewX, viewY);
    ctx.scale(viewScale, viewScale);

    const isHovering = hoverNode !== null;
    const hoverNeighborIds = new Set();
    if (isHovering) {
        for (const e of visEdges) {
            if (e.source === hoverNode.id) hoverNeighborIds.add(e.target);
            if (e.target === hoverNode.id) hoverNeighborIds.add(e.source);
        }
        hoverNeighborIds.add(hoverNode.id);
    }

    // --- Edges ---
    for (const e of visEdges) {
        const s = nodeMap[e.source], t = nodeMap[e.target];
        if (!s || !t) continue;

        let alpha, width;
        if (isHovering) {
            const connected = (e.source === hoverNode.id || e.target === hoverNode.id);
            alpha = connected ? 0.7 : 0.05;
            width = connected ? Math.max(1, Math.min(4, e.weight / 2)) : 0.5;
        } else {
            alpha = 0.25;
            width = Math.max(0.5, Math.min(3, e.weight / 3));
        }

        ctx.globalAlpha = alpha;
        ctx.strokeStyle = isHovering && (e.source === hoverNode.id || e.target === hoverNode.id)
            ? COMMUNITY_COLORS[hoverNode.community % COMMUNITY_COLORS.length]
            : '#6b7280';
        ctx.lineWidth = width;
        ctx.beginPath();
        ctx.moveTo(s.x, s.y);
        ctx.lineTo(t.x, t.y);
        ctx.stroke();
    }

    // --- Nodes ---
    for (const n of simNodes) {
        const color = COMMUNITY_COLORS[n.community % COMMUNITY_COLORS.length];
        const r = Math.max(3, n.size * 1.8);

        let nodeAlpha = 1.0;
        let labelAlpha = 1.0;
        let glowRadius = 0;

        if (isHovering) {
            if (n.id === hoverNode.id) {
                glowRadius = r + 8;
                labelAlpha = 1.0;
            } else if (hoverNeighborIds.has(n.id)) {
                nodeAlpha = 0.9;
                labelAlpha = 0.9;
            } else {
                nodeAlpha = 0.15;
                labelAlpha = 0.1;
            }
        }

        ctx.globalAlpha = nodeAlpha;

        // Glow for hovered node
        if (glowRadius > 0) {
            ctx.shadowColor = color;
            ctx.shadowBlur = 15;
        }

        // Node circle
        ctx.fillStyle = color;
        ctx.beginPath();
        ctx.arc(n.x, n.y, r, 0, Math.PI * 2);
        ctx.fill();

        // Border
        ctx.shadowBlur = 0;
        ctx.strokeStyle = n.id === hoverNode?.id ? (getTheme() === 'dark' ? '#fff' : '#1e293b') : (getTheme() === 'dark' ? 'rgba(255,255,255,0.15)' : 'rgba(0,0,0,0.08)');
        ctx.lineWidth = n.id === hoverNode?.id ? 2 : 1;
        ctx.stroke();

        // Label
        ctx.globalAlpha = labelAlpha;
        const showLabel = n.size > 3.5 || simNodes.length < 15 || (isHovering && hoverNeighborIds.has(n.id));
        if (showLabel) {
            const fontSize = Math.max(9, Math.min(12, n.size * 1.6));
            ctx.font = `500 ${fontSize}px Inter, -apple-system, BlinkMacSystemFont, sans-serif`;
            ctx.textAlign = 'center';
            ctx.textBaseline = 'top';

            const label = n.label.length > 16 ? n.label.slice(0, 15) + '…' : n.label;
            const lx = n.x, ly = n.y + r + 4;

            // Outline stroke for readability (cleaner than shadow offset)
            ctx.strokeStyle = getTheme() === 'dark' ? 'rgba(15,23,42,0.85)' : 'rgba(255,255,255,0.85)';
            ctx.lineWidth = 3;
            ctx.lineJoin = 'round';
            ctx.strokeText(label, lx, ly);

            // Main text
            ctx.fillStyle = getTheme() === 'dark' ? '#e2e8f0' : '#1e293b';
            ctx.fillText(label, lx, ly);
        }
    }

    ctx.globalAlpha = 1.0;
    ctx.restore();
}

/* ── Interaction (drag, pan, zoom, hover, click) ─────── */

function attachListeners(canvas, container) {
    // Remove old listeners by cloning
    const newCanvas = canvas.cloneNode(true);
    canvas.parentNode.replaceChild(newCanvas, canvas);
    const c = newCanvas;

    c.addEventListener('mousedown', onMouseDown);
    c.addEventListener('mousemove', onMouseMove);
    c.addEventListener('mouseup', onMouseUp);
    c.addEventListener('mouseleave', onMouseUp);
    c.addEventListener('wheel', onWheel, { passive: false });
    c.addEventListener('dblclick', onDblClick);

    // Touch support
    c.addEventListener('touchstart', onTouchStart, { passive: false });
    c.addEventListener('touchmove', onTouchMove, { passive: false });
    c.addEventListener('touchend', onTouchEnd);

    function screenToWorld(sx, sy) {
        return { x: (sx - viewX) / viewScale, y: (sy - viewY) / viewScale };
    }

    function findNodeAt(wx, wy) {
        for (let i = simNodes.length - 1; i >= 0; i--) {
            const n = simNodes[i];
            const r = Math.max(3, n.size * 1.8) + 6;
            if (Math.abs(wx - n.x) < r && Math.abs(wy - n.y) < r) return n;
        }
        return null;
    }

    function getCanvasPos(e) {
        const rect = c.getBoundingClientRect();
        return { x: e.clientX - rect.left, y: e.clientY - rect.top };
    }

    function onMouseDown(e) {
        const pos = getCanvasPos(e);
        const wp = screenToWorld(pos.x, pos.y);
        const node = findNodeAt(wp.x, wp.y);

        if (node) {
            dragNode = node;
            dragNode.fx = dragNode.x;
            dragNode.fy = dragNode.y;
            c.style.cursor = 'grabbing';
            // Reheat simulation
            simAlpha = Math.max(simAlpha, 0.3);
            if (!simRunning) {
                simRunning = true;
                tick(container.offsetWidth, container.offsetHeight);
            }
        } else {
            isPanning = true;
            panStart = { x: pos.x, y: pos.y, vx: viewX, vy: viewY };
            c.style.cursor = 'grabbing';
        }
    }

    function onMouseMove(e) {
        const pos = getCanvasPos(e);
        const wp = screenToWorld(pos.x, pos.y);

        if (dragNode) {
            dragNode.fx = wp.x;
            dragNode.fy = wp.y;
            dragNode.x = wp.x;
            dragNode.y = wp.y;
            if (!simRunning) draw();
        } else if (isPanning) {
            viewX = panStart.vx + (pos.x - panStart.x);
            viewY = panStart.vy + (pos.y - panStart.y);
            if (!simRunning) draw();
        } else {
            // Hover
            const node = findNodeAt(wp.x, wp.y);
            if (node !== hoverNode) {
                hoverNode = node;
                updateTooltip(node, e);
                if (!simRunning) draw();
            }
            c.style.cursor = node ? 'pointer' : 'grab';
        }
    }

    function onMouseUp(e) {
        if (dragNode) {
            dragNode.fx = null;
            dragNode.fy = null;
            dragNode = null;
        }
        isPanning = false;
        c.style.cursor = 'grab';
    }

    function onWheel(e) {
        e.preventDefault();
        const pos = getCanvasPos(e);
        const zoomFactor = e.deltaY < 0 ? 1.1 : 0.9;
        const newScale = Math.max(0.2, Math.min(5, viewScale * zoomFactor));

        // Zoom towards mouse position
        viewX = pos.x - (pos.x - viewX) * (newScale / viewScale);
        viewY = pos.y - (pos.y - viewY) * (newScale / viewScale);
        viewScale = newScale;

        if (!simRunning) draw();
    }

    function onDblClick(e) {
        const pos = getCanvasPos(e);
        const wp = screenToWorld(pos.x, pos.y);
        const node = findNodeAt(wp.x, wp.y);
        if (node) {
            showNodeDetail(node);
        }
    }

    // Touch handlers
    let lastTouchDist = 0;
    function onTouchStart(e) {
        e.preventDefault();
        if (e.touches.length === 1) {
            const t = e.touches[0];
            const pos = { x: t.clientX - c.getBoundingClientRect().left, y: t.clientY - c.getBoundingClientRect().top };
            const wp = screenToWorld(pos.x, pos.y);
            const node = findNodeAt(wp.x, wp.y);
            if (node) {
                dragNode = node;
                dragNode.fx = dragNode.x;
                dragNode.fy = dragNode.y;
                simAlpha = Math.max(simAlpha, 0.3);
                if (!simRunning) { simRunning = true; tick(container.offsetWidth, container.offsetHeight); }
            } else {
                isPanning = true;
                panStart = { x: pos.x, y: pos.y, vx: viewX, vy: viewY };
            }
        } else if (e.touches.length === 2) {
            const dx = e.touches[0].clientX - e.touches[1].clientX;
            const dy = e.touches[0].clientY - e.touches[1].clientY;
            lastTouchDist = Math.sqrt(dx * dx + dy * dy);
        }
    }
    function onTouchMove(e) {
        e.preventDefault();
        if (e.touches.length === 1) {
            const t = e.touches[0];
            const pos = { x: t.clientX - c.getBoundingClientRect().left, y: t.clientY - c.getBoundingClientRect().top };
            const wp = screenToWorld(pos.x, pos.y);
            if (dragNode) {
                dragNode.fx = wp.x; dragNode.fy = wp.y;
                dragNode.x = wp.x; dragNode.y = wp.y;
                if (!simRunning) draw();
            } else if (isPanning) {
                viewX = panStart.vx + (pos.x - panStart.x);
                viewY = panStart.vy + (pos.y - panStart.y);
                if (!simRunning) draw();
            }
        } else if (e.touches.length === 2) {
            const dx = e.touches[0].clientX - e.touches[1].clientX;
            const dy = e.touches[0].clientY - e.touches[1].clientY;
            const dist = Math.sqrt(dx * dx + dy * dy);
            if (lastTouchDist > 0) {
                const scale = dist / lastTouchDist;
                viewScale = Math.max(0.2, Math.min(5, viewScale * scale));
                if (!simRunning) draw();
            }
            lastTouchDist = dist;
        }
    }
    function onTouchEnd(e) {
        if (dragNode) { dragNode.fx = null; dragNode.fy = null; dragNode = null; }
        isPanning = false;
        lastTouchDist = 0;
    }
}

function updateTooltip(node, e) {
    const tip = document.getElementById('graph-tooltip');
    if (!tip) return;
    if (!node) {
        tip.classList.add('hidden');
        return;
    }
    const container = document.getElementById('graph-container');
    const rect = container.getBoundingClientRect();
    tip.classList.remove('hidden');
    tip.innerHTML = `
        <div class="font-semibold">${escHtml(node.label)}</div>
        <div class="text-xs text-gray-400 mt-1">${escHtml(node.type)} · 度 ${node.degree} · 社区 ${node.community}</div>
    `;
    tip.style.left = Math.min(e.clientX - rect.left + 15, rect.width - 180) + 'px';
    tip.style.top = (e.clientY - rect.top - 10) + 'px';
}

/* ── Legend ───────────────────────────────────────────── */

function renderLegend(data) {
    const el = document.getElementById('graph-legend');
    if (!el) return;
    const comms = data.communities;
    if (!comms || Object.keys(comms).length === 0) {
        el.innerHTML = '<div class="text-gray-500 text-sm">无社区数据</div>';
        return;
    }
    el.innerHTML = `
        <div class="text-gray-400 text-sm mb-2">社区</div>
        <div class="flex flex-wrap gap-4">
            ${Object.entries(comms).map(([id, info]) => `
                <div class="flex items-center gap-2">
                    <span class="w-3 h-3 rounded-full shrink-0"
                          style="background:${COMMUNITY_COLORS[parseInt(id) % COMMUNITY_COLORS.length]}"></span>
                    <span class="text-gray-300 text-sm">
                        ${escHtml(info.label)}
                        <span class="text-gray-500">(${info.members} 页, 内聚 ${info.cohesion})</span>
                    </span>
                </div>
            `).join('')}
        </div>
        <div class="text-gray-600 text-xs mt-3">
            💡 拖拽节点移动 · 滚轮缩放 · 空白处拖拽平移 · 悬停高亮关联 · 双击查看详情 · 拖动滑块过滤弱连接
        </div>
    `;
}

/* ── Neighbor row renderer (avoids nested template literals) ── */

function renderNeighborRow(n, highlightNeighbor) {
    const isHighlight = highlightNeighbor && (n.id === highlightNeighbor || n.label === highlightNeighbor);
    const rowClass = isHighlight
        ? 'bg-blue-600/20 ring-1 ring-blue-500/50'
        : 'bg-gray-750';
    const nameClass = isHighlight ? 'text-yellow-300 font-semibold' : 'text-blue-300';
    const prefix = isHighlight ? '\u{1F517} ' : '';
    const barW = Math.min(60, n.weight * 8);
    return `<div class="flex items-center justify-between px-3 py-2 rounded text-sm ${rowClass}">
        <span class="${nameClass} truncate">${prefix}${escHtml(n.label)}</span>
        <div class="flex items-center gap-2 shrink-0 ml-2">
            <div class="h-1 rounded bg-gray-600" style="width:${barW}px"></div>
            <span class="text-gray-600 text-xs w-8 text-right">${n.weight}</span>
        </div>
    </div>`;
}

/* ── Node detail panel ───────────────────────────────── */

async function showNodeDetail(node, highlightNeighbor) {
    const el = document.getElementById('graph-node-detail');
    if (!el) return;
    el.classList.remove('hidden');
    el.innerHTML = '<div class="text-gray-400 animate-pulse">加载中...</div>';

    try {
        const resp = await fetch(`/api/graph/node/${node.id}`, { credentials: 'include' });
        const data = await resp.json();
        const color = COMMUNITY_COLORS[(data.node.community || 0) % COMMUNITY_COLORS.length];

        el.innerHTML = `
            <div class="flex items-center justify-between mb-3">
                <div class="flex items-center gap-3">
                    <span class="w-4 h-4 rounded-full" style="background:${color}"></span>
                    <h3 class="text-lg font-bold text-white">${escHtml(data.node.title || node.id)}</h3>
                    <span class="text-xs px-2 py-0.5 rounded-full bg-gray-700 text-gray-400">${escHtml(data.node.type)}</span>
                </div>
                <button onclick="document.getElementById('graph-node-detail').classList.add('hidden')"
                        class="text-gray-500 hover:text-gray-300 text-lg">✕</button>
            </div>
            <div class="text-sm text-gray-500 mb-3">
                度: ${data.neighbors.length} · 社区: ${data.node.community ?? '-'}
            </div>
            ${data.neighbors.length ? `
                <div class="text-sm text-gray-400 mb-2">关联节点 (${data.neighbors.length})</div>
                <div class="grid grid-cols-1 md:grid-cols-2 gap-1">
                    ${data.neighbors.map(n => renderNeighborRow(n, highlightNeighbor)).join('')}
                </div>
            ` : '<div class="text-gray-500 text-sm">无关联</div>'}
        `;
    } catch (e) {
        el.innerHTML = `<div class="text-red-400">${e.message}</div>`;
    }
}

function resetGraphView() {
    viewX = 0; viewY = 0; viewScale = 1;
    hoverNode = null;
    if (graphData) initSimulation(graphData);
}
