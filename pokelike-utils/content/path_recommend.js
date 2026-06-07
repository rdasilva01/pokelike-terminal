// Highlights the best-scoring route from the last cleared node to the boss,
// directly on the map screen's SVG — porting the path-scoring algorithm from
// the Python interactor's `_compute_best_level_path` / `_NODE_SCORE` (see
// CLAUDE.md "Type-effectiveness scoring" / interactor.py `_compute_best_level_path`).
//
// Reads `localStorage['poke_current_run']` for the map graph (nodes/edges/
// layers + visited/accessible flags) — same source MapParser.py uses — rather
// than the page's `state` global, since localStorage is reliably readable from
// any script context regardless of lexical-scope sharing quirks.
(() => {
  // Matches catch_hotkeys.js's flag — both scripts run as separate MAIN-world
  // closures and tag synthetic keydowns with this so they ignore each other's
  // (and their own) re-dispatched events.
  const SYNTHETIC_FLAG = '__pokelikeUtilsSynthetic';

  const OVERLAY_ID = 'pokelike-path-overlay';
  const INDICATOR_ID = 'pokelike-path-next-indicator';
  const COLOR_NORMAL = '#00aaff';
  const COLOR_CATCH_PRIORITY = '#ff3333';
  const DRAW_INTERVAL_MS = 400;

  // Mirrors interactor.py's _NODE_SCORE — higher score = more valuable to route
  // through. map.js's raw type strings (battle/question) differ from the
  // python parser's translated ones (wild_encounter/mystery); same weights apply.
  const NODE_SCORE = {
    trainer: 2.0,
    battle: 1.0,
    question: 0.5,
    move_tutor: 0.25,
    item: 0.1,
  };

  // Alternate weighting used when "Prioritize Catches" mode is on — routes
  // through Catch and Mystery (question) nodes ahead of trainers/battles.
  const NODE_SCORE_CATCH_PRIORITY = {
    catch: 2.0,
    question: 2.0,
    trainer: 1.0,
    battle: 0.5,
    move_tutor: 0.25,
    item: 0.1,
  };

  let running = false;
  let drawTimer = null;
  let catchPriority = false;

  // Auto-follow state (toggled by E): clicks each accessible node along the
  // recommended path as it becomes reachable, and turns itself off (without
  // clicking) as soon as the boss node is the next one up — leaving the boss
  // fight for the player to start manually.
  const FOLLOW_BADGE_ID = 'pokelike-path-follow-badge';
  let following = false;
  let lastAccessibleKey = null;

  function pathColor() {
    return catchPriority ? COLOR_CATCH_PRIORITY : COLOR_NORMAL;
  }

  function nodeScoreTable() {
    return catchPriority ? NODE_SCORE_CATCH_PRIORITY : NODE_SCORE;
  }

  function readMap() {
    try {
      const run = JSON.parse(localStorage.getItem('poke_current_run') || '{}');
      return run?.map || null;
    } catch (_) {
      return null;
    }
  }

  function nodeVal(nodes, id) {
    return nodeScoreTable()[nodes[id]?.type] || 0;
  }

  // DFS from the last-cleared node to the boss, maximising summed node value —
  // same shape as interactor.py's _compute_best_level_path.
  function computeBestPath(map) {
    const { nodes, edges } = map;
    const ids = Object.keys(nodes);
    if (!ids.length) return null;
    const bossId = ids.find((id) => nodes[id].type === 'boss');
    if (!bossId) return null;

    const children = {};
    for (const e of edges) {
      (children[e.from] = children[e.from] || []).push(e.to);
    }

    const visited = ids.filter((id) => nodes[id].visited);
    const startId = visited.length
      ? visited.reduce((a, b) => (nodes[b].layer > nodes[a].layer ? b : a))
      : (ids.find((id) => nodes[id].type === 'start') || ids[0]);

    let best = [startId];
    let bestScore = -Infinity;

    (function dfs(path, score) {
      const cur = path[path.length - 1];
      if (cur === bossId) {
        if (score > bestScore) {
          bestScore = score;
          best = path.slice();
        }
        return;
      }
      for (const child of (children[cur] || [])) {
        dfs([...path, child], score + nodeVal(nodes, child));
      }
    })([startId], nodeVal(nodes, startId));

    return best;
  }

  // Mirrors map.js's renderMap() top-to-bottom layout math exactly, so the
  // overlay lines up with the game's own node positions.
  function computePositions(map, container) {
    const W = container.clientWidth || 600;
    const H = container.clientHeight || 500;
    const layerCount = map.layers.length;
    const padY = 28;
    const positions = {};
    for (let l = 0; l < map.layers.length; l++) {
      const layer = map.layers[l];
      const y = layerCount > 1 ? padY + (l / (layerCount - 1)) * (H - 2 * padY) : H / 2;
      const nodeGap = W / (layer.length + 0.2);
      for (let c = 0; c < layer.length; c++) {
        const x = layer.length === 1 ? W / 2 : W / 2 + (c - (layer.length - 1) / 2) * nodeGap;
        positions[layer[c].id] = { x, y };
      }
    }
    return positions;
  }

  function clearOverlay() {
    document.getElementById(OVERLAY_ID)?.remove();
  }

  function ensureIndicator() {
    let el = document.getElementById(INDICATOR_ID);
    if (!el) {
      el = document.createElement('div');
      el.id = INDICATOR_ID;
      el.style.cssText = `
        position: fixed;
        z-index: 9999;
        pointer-events: none;
        display: none;
        flex-direction: column;
        align-items: center;
        gap: 3px;
        font-family: 'Segoe UI', sans-serif;
        text-shadow: 0 0 4px rgba(0,0,0,0.7);
      `;
      el.innerHTML = `
        <span style="font-size:10px; letter-spacing:1px; opacity:0.85;">NEXT</span>
        <span class="pokelike-path-next-key" style="
          display:flex; align-items:center; justify-content:center;
          width:28px; height:28px; border-radius:6px;
          background: rgba(0,20,40,0.7);
          font-size:16px; font-weight:bold;
        "></span>
      `;
      document.body.appendChild(el);
    }
    const color = pathColor();
    el.style.color = color;
    const key = el.querySelector('.pokelike-path-next-key');
    key.style.border = `2px solid ${color}`;
    return el;
  }

  function removeIndicator() {
    document.getElementById(INDICATOR_ID)?.remove();
  }

  // Shows which numbered map shortcut (1 = leftmost accessible node, 2 =
  // rightmost — matching game.js's own `Digit1`/`Digit2` map handler, which
  // sorts accessible nodes by layer then column) leads onto the recommended
  // path, positioned just to the right of the map.
  function updateNextNodeIndicator(map, path, container) {
    const nextId = path[1];
    if (!nextId) { removeIndicator(); return; }

    const accessible = Object.values(map.nodes)
      .filter((n) => n.accessible && !n.visited)
      .sort((a, b) => (a.layer !== b.layer ? a.layer - b.layer : a.col - b.col));
    const idx = accessible.findIndex((n) => n.id === nextId);
    if (idx !== 0 && idx !== 1) { removeIndicator(); return; }

    const el = ensureIndicator();
    const rect = container.getBoundingClientRect();
    el.style.left = `${rect.right + 14}px`;
    el.style.top = `${rect.top + rect.height / 2 - 24}px`;
    el.style.display = 'flex';
    el.querySelector('.pokelike-path-next-key').textContent = String(idx + 1);
  }

  function findMapSvg() {
    // Always scope to .screen.active — inactive screens remain in the DOM.
    const container = document.querySelector('.screen.active #map-container')
      || document.getElementById('map-container');
    const svg = container?.querySelector('svg');
    return svg ? { container, svg } : null;
  }

  function ensureFollowBadge(container) {
    let el = document.getElementById(FOLLOW_BADGE_ID);
    if (!el) {
      el = document.createElement('div');
      el.id = FOLLOW_BADGE_ID;
      el.textContent = 'AUTO-FOLLOW';
      el.style.cssText = `
        position: fixed;
        z-index: 9999;
        pointer-events: none;
        font-family: 'Segoe UI', sans-serif;
        font-size: 10px;
        font-weight: bold;
        letter-spacing: 1px;
        padding: 4px 8px;
        border-radius: 4px;
        background: rgba(0,20,40,0.7);
        text-shadow: 0 0 4px rgba(0,0,0,0.7);
      `;
      document.body.appendChild(el);
    }
    el.style.color = pathColor();
    el.style.border = `2px solid ${pathColor()}`;
    const rect = container.getBoundingClientRect();
    el.style.left = `${rect.left + 8}px`;
    el.style.top = `${rect.top + 8}px`;
    return el;
  }

  function removeFollowBadge() {
    document.getElementById(FOLLOW_BADGE_ID)?.remove();
  }

  // Clicks the actual SVG <g> rendered at a node's computed position — the
  // game wires its onNodeClick handler to that element's 'click' event
  // (see CLAUDE.md / map.js renderMap), so dispatching one there drives the
  // exact same behaviour as a real click.
  function clickMapNode(svg, pos) {
    if (!pos) return false;
    const pt = svg.createSVGPoint();
    pt.x = pos.x;
    pt.y = pos.y;
    const screenPt = pt.matrixTransform(svg.getScreenCTM());
    const el = document.elementFromPoint(screenPt.x, screenPt.y);
    const g = el?.closest('g');
    if (!g) return false;
    g.dispatchEvent(new MouseEvent('click', { bubbles: true, cancelable: true, view: window }));
    return true;
  }

  // Auto-clicks the next reachable node along the recommended path. Stops
  // itself (without clicking) as soon as the next node along the path is the
  // boss — leaving the boss fight for the player to start manually.
  function tryAutoFollow(map, path, svg, container) {
    ensureFollowBadge(container);

    const accessible = Object.values(map.nodes).filter((n) => n.accessible && !n.visited);
    const key = accessible.map((n) => n.id).sort().join(',');
    if (!accessible.length || key === lastAccessibleKey) return;

    const nextId = path.find((id) => accessible.some((n) => n.id === id));
    if (!nextId) return;

    if (map.nodes[nextId]?.type === 'boss') {
      following = false;
      lastAccessibleKey = null;
      removeFollowBadge();
      postStatus();
      return;
    }

    const positions = computePositions(map, container);
    if (!clickMapNode(svg, positions[nextId])) return;

    lastAccessibleKey = key;
  }

  function draw() {
    const found = findMapSvg();
    const map = found ? readMap() : null;
    if (!found || !map || !map.nodes || !map.edges || !map.layers) {
      clearOverlay();
      removeIndicator();
      return;
    }
    const { container, svg } = found;

    const path = computeBestPath(map);
    if (!path || path.length < 2) {
      clearOverlay();
      removeIndicator();
      return;
    }

    updateNextNodeIndicator(map, path, container);
    if (following) tryAutoFollow(map, path, svg, container);

    // renderMap() does `container.innerHTML = ''` on every (re)render, wiping
    // any overlay we previously appended — so re-create it fresh each tick
    // rather than trying to keep a persistent node alive across re-renders.
    clearOverlay();
    const positions = computePositions(map, container);

    const overlay = document.createElementNS('http://www.w3.org/2000/svg', 'g');
    overlay.id = OVERLAY_ID;
    overlay.style.pointerEvents = 'none';
    const color = pathColor();

    for (let i = 0; i < path.length - 1; i++) {
      const a = positions[path[i]];
      const b = positions[path[i + 1]];
      if (!a || !b) continue;
      const line = document.createElementNS('http://www.w3.org/2000/svg', 'line');
      line.setAttribute('x1', a.x);
      line.setAttribute('y1', a.y);
      line.setAttribute('x2', b.x);
      line.setAttribute('y2', b.y);
      line.setAttribute('stroke', color);
      line.setAttribute('stroke-width', '3');
      line.setAttribute('stroke-linecap', 'round');
      overlay.appendChild(line);
    }

    for (const id of path) {
      const pos = positions[id];
      if (!pos) continue;
      const circle = document.createElementNS('http://www.w3.org/2000/svg', 'circle');
      circle.setAttribute('cx', pos.x);
      circle.setAttribute('cy', pos.y);
      circle.setAttribute('r', '30');
      circle.setAttribute('fill', 'none');
      circle.setAttribute('stroke', color);
      circle.setAttribute('stroke-width', '2.5');
      circle.setAttribute('stroke-dasharray', '6,4');
      overlay.appendChild(circle);
    }

    svg.appendChild(overlay);
  }

  // W toggles between the normal (blue) and catch-priority (red) routing modes
  // while the util is active — same effect as the popup's "Prioritize Catches"
  // switch, just without opening the popup.
  function onKeyDown(e) {
    if (!running || e[SYNTHETIC_FLAG]) return;
    if (e.target.tagName === 'INPUT' || e.target.tagName === 'TEXTAREA' || e.target.isContentEditable) return;
    if (e.shiftKey || e.ctrlKey || e.altKey || e.metaKey) return;

    if (e.code === 'KeyW') {
      e.preventDefault();
      catchPriority = !catchPriority;
      clearOverlay();
      removeIndicator();
      draw();
      postStatus();
      return;
    }

    if (e.code === 'KeyE') {
      e.preventDefault();
      following = !following;
      lastAccessibleKey = null;
      if (!following) removeFollowBadge();
      postStatus();
      return;
    }
  }
  document.addEventListener('keydown', onKeyDown);

  function postStatus() {
    window.postMessage({
      source: 'pokelike-path-main',
      payload: { status: running ? 'running' : 'stopped', catchPriority, following },
    }, '*');
  }

  function start(opts) {
    if (opts && typeof opts.catchPriority === 'boolean') catchPriority = opts.catchPriority;
    if (running) { postStatus(); return; }
    running = true;
    draw();
    drawTimer = setInterval(draw, DRAW_INTERVAL_MS);
    postStatus();
  }

  function stop() {
    if (!running) return;
    running = false;
    if (drawTimer) { clearInterval(drawTimer); drawTimer = null; }
    clearOverlay();
    removeIndicator();
    removeFollowBadge();
    following = false;
    lastAccessibleKey = null;
    postStatus();
  }

  window.addEventListener('message', (e) => {
    if (e.source !== window || e.data?.source !== 'pokelike-utils-bridge') return;
    const msg = e.data.payload;
    if (msg.util !== 'path') return;
    if (msg.type === 'START') start({ catchPriority: msg.catchPriority });
    else if (msg.type === 'STOP') stop();
    else if (msg.type === 'SET_CATCH_PRIORITY') {
      catchPriority = !!msg.catchPriority;
      if (running) { clearOverlay(); removeIndicator(); draw(); }
      postStatus();
    }
  });

  postStatus();
})();
