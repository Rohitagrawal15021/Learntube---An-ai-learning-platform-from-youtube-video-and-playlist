/* LearnTube — Course map: an interactive 3D knowledge graph.
   Reads window.__GRAPH__ (nodes + prerequisite edges), renders it with
   3d-force-graph, and lets a click jump to the exact second of the video that
   teaches a concept. The video jump (openVideoAt) is reused by the quiz. */

(function () {
  "use strict";

  var DATA = window.__GRAPH__ || { nodes: [], edges: [] };

  // Categorical palette — inks & pens that stay legible on cream paper.
  var PALETTE = ["#1B2A4A","#D24039","#2F7D6B","#6B4FA0","#B6792B","#3E6DA3","#9A3671","#4C7A34"];

  function lectureOf(node) {
    var occ = (node.occurrences && node.occurrences[0]) || {};
    return occ.position || 1;
  }
  function colorFor(position) {
    return PALETTE[((position || 1) - 1 + PALETTE.length) % PALETTE.length];
  }
  function fmtTime(sec) {
    sec = Math.max(0, Math.round(sec || 0));
    var m = Math.floor(sec / 60), s = sec % 60;
    return m + ":" + (s < 10 ? "0" : "") + s;
  }
  function byId(id) { return document.getElementById(id); }

  // ---- shape the data for force-graph, and precompute degree + prereqs ----
  var degree = {}, prereqOf = {};
  DATA.nodes.forEach(function (n) { degree[n.id] = 0; prereqOf[n.id] = []; });
  (DATA.edges || []).forEach(function (e) {
    if (degree[e.from] === undefined || degree[e.to] === undefined) return;
    degree[e.from]++; degree[e.to]++;
    prereqOf[e.to].push(e.from);           // to-node depends on from-node
  });

  var nodes = DATA.nodes.map(function (n) {
    var occ = (n.occurrences && n.occurrences[0]) || {};
    return {
      id: n.id, label: n.label, definition: n.definition || "",
      video_id: occ.video_id, start: occ.start || 0, position: lectureOf(n),
      deg: degree[n.id] || 0
    };
  });
  var links = (DATA.edges || []).map(function (e) { return { source: e.from, target: e.to }; });
  var nodeById = {};
  nodes.forEach(function (n) { nodeById[n.id] = n; });

  // ---- stats + legend ----
  byId("statNodes").textContent = nodes.length + " concepts";
  byId("statEdges").textContent = links.length + " links";

  var lectures = {};
  nodes.forEach(function (n) { lectures[n.position] = (lectures[n.position] || 0) + 1; });
  var legend = byId("legend");
  Object.keys(lectures).sort(function (a, b) { return a - b; }).forEach(function (pos) {
    var row = document.createElement("div");
    row.className = "legend-item";
    row.innerHTML = '<span class="legend-dot" style="color:' + colorFor(pos) + '"></span>' +
                    '<span><b>Lecture ' + pos + '</b> · ' + lectures[pos] + '</span>';
    legend.appendChild(row);
  });

  // ---- hover-highlight state (dim everything except a node + its links) ----
  var hiNodes = {}, hiLinks = [], hoverId = null;
  function linkEnds(l) { return [(l.source && l.source.id) || l.source, (l.target && l.target.id) || l.target]; }
  function computeHighlight(node) {
    hiNodes = {}; hiLinks = [];
    if (node) {
      hiNodes[node.id] = 1;
      links.forEach(function (l) {
        var e = linkEnds(l);
        if (e[0] === node.id || e[1] === node.id) { hiLinks.push(l); hiNodes[e[0]] = 1; hiNodes[e[1]] = 1; }
      });
    }
  }
  var DIM_NODE = "rgba(27,42,74,0.12)", LINK_BASE = "rgba(27,42,74,0.22)", LINK_DIM = "rgba(27,42,74,0.05)";
  function nodeColorFn(n) { return (hoverId && !hiNodes[n.id]) ? DIM_NODE : colorFor(n.position); }
  function linkColorFn(l) { return !hoverId ? LINK_BASE : (hiLinks.indexOf(l) >= 0 ? "#D24039" : LINK_DIM); }
  function linkWidthFn(l) { return (hoverId && hiLinks.indexOf(l) >= 0) ? 2.4 : 0.7; }
  function partFn(l) { return (hoverId && hiLinks.indexOf(l) >= 0) ? 4 : 2; }

  // ---- build the 3D graph ----
  var Graph = ForceGraph3D()(byId("graph"))
    .graphData({ nodes: nodes, links: links })
    .backgroundColor("rgba(0,0,0,0)")
    .showNavInfo(false)
    .nodeVal(function (n) { return 2 + n.deg * 1.6; })
    .nodeColor(nodeColorFn)
    .nodeOpacity(0.95)
    .nodeLabel(function (n) { return '<div class="gtip">' + n.label +
      '<em>Lecture ' + n.position + ' · ' + fmtTime(n.start) + '</em></div>'; })
    .linkColor(linkColorFn)
    .linkWidth(linkWidthFn)
    .linkDirectionalParticles(partFn)
    .linkDirectionalParticleWidth(2)
    .linkDirectionalParticleColor(function () { return "#D24039"; })
    .linkDirectionalArrowLength(3.4)
    .linkDirectionalArrowRelPos(1)
    .onNodeHover(function (node) {
      hoverId = node ? node.id : null;
      computeHighlight(node);
      Graph.nodeColor(nodeColorFn).linkColor(linkColorFn).linkWidth(linkWidthFn).linkDirectionalParticles(partFn);
      byId("graph").style.cursor = node ? "pointer" : "";
    });

  // Gentle spread so labels don't overlap.
  Graph.d3Force("charge").strength(-150);
  window.__LTGraph = Graph;   // handy for debugging in the console

  // ---- camera focus on a node ----
  function focusNode(n) {
    var dist = 90;
    var r = Math.hypot(n.x || 0, n.y || 0, n.z || 0) || 1;
    var k = 1 + dist / r;
    Graph.cameraPosition({ x: (n.x || 0) * k, y: (n.y || 0) * k, z: (n.z || 0) * k }, n, 1100);
  }

  // ---- concept panel ----
  var panel = byId("panel");
  function openPanel(n) {
    byId("panelLecture").textContent = "Lecture " + n.position;
    byId("panelTitle").textContent = n.label;
    byId("panelDef").textContent = n.definition || "No description available.";
    byId("panelTime").textContent = fmtTime(n.start);

    var pr = (prereqOf[n.id] || []).map(function (id) { return nodeById[id]; }).filter(Boolean);
    var wrap = byId("panelPrereq"), list = byId("panelPrereqList");
    list.innerHTML = "";
    if (pr.length) {
      pr.forEach(function (p) {
        var li = document.createElement("li");
        li.textContent = p.label;
        li.onclick = function () { openPanel(p); focusNode(p); };
        list.appendChild(li);
      });
      wrap.hidden = false;
    } else { wrap.hidden = true; }

    byId("panelWatch").onclick = function () {
      openVideoAt(n.video_id, n.start, n.label, "Lecture " + n.position);
    };
    panel.hidden = false;
  }
  byId("panelClose").onclick = function () { panel.hidden = true; };

  Graph.onNodeClick(function (n) { openPanel(n); focusNode(n); });
  Graph.onBackgroundClick(function () { panel.hidden = true; });

  // ---- video modal: jump to the exact second (reused by the quiz) ----
  var vmodal = byId("vmodal");
  function openVideoAt(videoId, seconds, title, lectureLabel) {
    if (!videoId) { return; }
    var start = Math.max(0, Math.round(seconds || 0));
    byId("vmodalTitle").textContent = title || "Watch this moment";
    byId("vmodalNote").textContent = (lectureLabel ? lectureLabel + " · " : "") +
      "starts at " + fmtTime(start);
    byId("vmodalFrame").innerHTML =
      '<iframe src="https://www.youtube.com/embed/' + videoId + '?start=' + start +
      '&autoplay=1&rel=0" allow="autoplay; encrypted-media" allowfullscreen></iframe>';
    vmodal.hidden = false;
  }
  function closeVideo() { vmodal.hidden = true; byId("vmodalFrame").innerHTML = ""; }
  byId("vmodalClose").onclick = closeVideo;
  vmodal.onclick = function (e) { if (e.target === vmodal) closeVideo(); };
  window.LearnTubeOpenVideoAt = openVideoAt;   // exposed for the quiz remediation

  // ---- intro overlay: fade once the graph has taken shape ----
  var faded = false;
  function fadeIntro() { if (faded) return; faded = true; byId("intro").classList.add("gone"); }
  Graph.onEngineStop(function () { fadeIntro(); Graph.zoomToFit(900, 55); });
  setTimeout(fadeIntro, 4500);                 // safety net
  setTimeout(function () { Graph.zoomToFit(1400, 55); }, 1200);

  // ---- always-on labels: project each node to the screen every frame ----
  var labelLayer = byId("glabels");
  var labelEls = {};
  nodes.forEach(function (n) {
    var el = document.createElement("span");
    el.className = "glabel";
    el.textContent = n.label;
    el.style.borderColor = colorFor(n.position);
    labelLayer.appendChild(el);
    labelEls[n.id] = el;
  });

  function tickLabels() {
    var W = window.innerWidth, H = window.innerHeight;
    var cam = Graph.camera();
    var cp = cam.position, m = cam.matrixWorld.elements;
    var fx = -m[8], fy = -m[9], fz = -m[10];          // camera forward (world)
    for (var i = 0; i < nodes.length; i++) {
      var n = nodes[i], el = labelEls[n.id];
      if (n.x === undefined) { el.style.display = "none"; continue; }
      var inFront = (n.x - cp.x) * fx + (n.y - cp.y) * fy + (n.z - cp.z) * fz;
      var p = inFront > 0 ? Graph.graph2ScreenCoords(n.x, n.y, n.z) : null;
      if (!p || p.x < -40 || p.y < -20 || p.x > W + 40 || p.y > H + 20) {
        el.style.display = "none"; continue;
      }
      el.style.display = "block";
      el.style.opacity = (hoverId && !hiNodes[n.id]) ? "0.15" : "1";
      el.style.transform = "translate(-50%,-50%) translate(" +
        p.x.toFixed(1) + "px," + (p.y - 16 - n.deg).toFixed(1) + "px)";
    }
    requestAnimationFrame(tickLabels);
  }
  requestAnimationFrame(tickLabels);

  // ---- keep the scene alive: slow auto-orbit until the user grabs it ----
  var autoRotate = false, angle = 0, radius = 320, camY = 0;
  setTimeout(function () {
    var cp = Graph.cameraPosition();
    radius = Math.hypot(cp.x, cp.z) || 320;
    camY = cp.y; angle = Math.atan2(cp.x, cp.z);
    autoRotate = true;
  }, 2900);
  byId("graph").addEventListener("pointerdown", function () { autoRotate = false; });
  setInterval(function () {
    if (!autoRotate) return;
    angle += 0.0022;
    Graph.cameraPosition({ x: radius * Math.sin(angle), y: camY, z: radius * Math.cos(angle) });
  }, 30);
})();
