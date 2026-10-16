/**
 * LearnTube — Course Map (cream notebook theme)
 *
 * A flat, layered knowledge graph. Every concept is always rendered — nothing
 * is hidden behind a collapse toggle, so search, selection and prerequisite
 * links all address the same visible set of pills.
 *
 * Two layouts, one renderer:
 *   - Curriculum: columns are lectures, rows are concepts in taught order.
 *   - Prereq flow: columns are prerequisite depth, so you read left to right.
 *
 * Interaction is deliberately plain: a pill is a button. Hover previews the
 * prerequisite path; clicking opens the detail panel. Zoom/pan is bound to the
 * canvas background only, so it can never swallow a click on a pill.
 */

(function () {
  "use strict";

  const GRAPH = window.__GRAPH__ || { nodes: [], edges: [] };
  const LECTURES = window.__LECTURES__ || [];

  const NODES = (GRAPH.nodes || []).filter((n) => n && n.id);
  const EDGES = (GRAPH.edges || []).filter(
    (e) => e && NODES.some((n) => n.id === e.from) && NODES.some((n) => n.id === e.to)
  );

  const byId = {};
  NODES.forEach((n) => {
    byId[n.id] = n;
  });

  // Edge {from, to} reads "learn `from` before `to`".
  const parents = {};
  NODES.forEach((n) => {
    parents[n.id] = [];
  });
  EDGES.forEach((e) => {
    parents[e.to].push(e.from);
  });

  // ---- Lecture colour, keyed to the lecture a concept is taught in ----------
  const PALETTE = [
    "#2F7D6B", "#E86A5C", "#6B4FA0", "#B6792B",
    "#3E6DA3", "#9A3671", "#4C7A34", "#C25A2E",
  ];
  const lectureOf = (node) => {
    const occ = (node.occurrences && node.occurrences[0]) || {};
    return occ.position || 1;
  };
  const lectureColor = (pos) => PALETTE[(Math.max(1, pos || 1) - 1) % PALETTE.length];

  // ---- Layout constants ----------------------------------------------------
  const LEVEL_GAP = 330;      // horizontal distance between columns
  const NODE_GAP = 18;        // vertical gap between pills in a column
  const PILL_HEIGHT = 40;
  const PILL_MIN = 150;
  const PILL_MAX = 280;

  // ---- DOM -----------------------------------------------------------------
  const $ = (id) => document.getElementById(id);
  const panel = $("panel");
  const vmodal = $("vmodal");
  const searchInput = $("search");
  const datalist = $("conceptList");

  const statNodes = $("statNodes");
  const statEdges = $("statEdges");
  const statNodesText = $("statNodesText");
  const statEdgesText = $("statEdgesText");

  const nodesCountStr = `${NODES.length} concept${NODES.length === 1 ? "" : "s"}`;
  const edgesCountStr = `${EDGES.length} link${EDGES.length === 1 ? "" : "s"}`;

  if (statNodesText) statNodesText.textContent = nodesCountStr;
  else if (statNodes) statNodes.textContent = nodesCountStr;

  if (statEdgesText) statEdgesText.textContent = edgesCountStr;
  else if (statEdges) statEdges.textContent = edgesCountStr;

  if (datalist) {
    datalist.innerHTML = "";
    NODES.forEach((n) => {
      const opt = document.createElement("option");
      opt.value = n.label;
      datalist.appendChild(opt);
    });
  }

  // ---- Text measurement (so pills fit their labels) ------------------------
  const measureCanvas = document.createElement("canvas");
  const measureCtx = measureCanvas.getContext("2d");
  const FONT = "600 13.5px Archivo, system-ui, sans-serif";

  function pillWidth(label) {
    measureCtx.font = FONT;
    const w = measureCtx.measureText(label || "").width;
    return Math.min(PILL_MAX, Math.max(PILL_MIN, Math.ceil(w) + 34));
  }

  function truncateToPill(label, width) {
    measureCtx.font = FONT;
    if (measureCtx.measureText(label).width <= width - 30) return label;
    let text = label;
    while (text.length > 4 && measureCtx.measureText(text + "…").width > width - 30) {
      text = text.slice(0, -1);
    }
    return text + "…";
  }

  function fmtTime(sec) {
    sec = Math.max(0, Math.round(sec || 0));
    return `${Math.floor(sec / 60)}:${String(sec % 60).padStart(2, "0")}`;
  }

  function cleanTitle(title) {
    if (!title) return "";
    let t = title.trim();
    t = t.replace(/^(?:lecture|lec|module|chapter|part|#)?\s*\d+\s*[:\-–|•]\s*/i, "");
    t = t.replace(/\s*[|\-–]\s*(?:full course|crash course|playlist|tutorial).*$/i, "");
    return t.trim() || title.trim();
  }

  const lectureMeta = (pos) => LECTURES.find((l) => l.position === pos) || {};

  // ---- Layout --------------------------------------------------------------
  // Every node gets {x, y, w, h}; x is the column, y the vertical centre.
  function buildLayout(mode) {
    const levels = new Map();          // level index -> [node]
    const levelOf = {};

    if (mode === "prereq") {
      // Longest-path depth: a concept sits one column right of its deepest parent.
      const depth = {};
      const visiting = new Set();
      const depthOf = (id) => {
        if (depth[id] !== undefined) return depth[id];
        if (visiting.has(id)) return 0;          // cycle guard (shouldn't happen)
        visiting.add(id);
        const ps = parents[id] || [];
        depth[id] = ps.length ? 1 + Math.max(...ps.map(depthOf)) : 0;
        visiting.delete(id);
        return depth[id];
      };
      NODES.forEach((n) => {
        depthOf(n.id);
      });
      NODES.forEach((n) => {
        const d = depth[n.id] || 0;
        levelOf[n.id] = d;
        if (!levels.has(d)) levels.set(d, []);
        levels.get(d).push(n);
      });
    } else {
      // Curriculum: one column per lecture, concepts in taught order.
      const byLecture = new Map();
      NODES.forEach((n) => {
        const pos = lectureOf(n);
        if (!byLecture.has(pos)) byLecture.set(pos, []);
        byLecture.get(pos).push(n);
      });
      // Any lecture in the manifest with no concepts still gets its column.
      LECTURES.forEach((l) => {
        const pos = l.position || 1;
        if (!byLecture.has(pos)) byLecture.set(pos, []);
      });
      const ordered = Array.from(byLecture.keys()).sort((a, b) => a - b);
      ordered.forEach((pos, i) => {
        const list = byLecture.get(pos).slice();
        list.sort((a, b) => {
          const oa = (a.occurrences && a.occurrences[0]) || {};
          const ob = (b.occurrences && b.occurrences[0]) || {};
          return (oa.start || 0) - (ob.start || 0) || a.label.localeCompare(b.label);
        });
        levelOf[pos] = i;
        levels.set(i, list);
      });
    }

    const placed = {};
    let maxColumnHeight = 0;
    let maxColumnWidth = 0;

    levels.forEach((list, levelIndex) => {
      // Each column is vertically centred on y = 0, so the whole map reads
      // outward from the middle rather than hanging off the top-left.
      // `y` stored here is the pill's TOP edge, matching the <g> transform.
      const total =
        list.length * PILL_HEIGHT + NODE_GAP * Math.max(0, list.length - 1);
      maxColumnHeight = Math.max(maxColumnHeight, total);

      let y = -total / 2;
      list.forEach((n) => {
        const w = pillWidth(n.label);
        maxColumnWidth = Math.max(maxColumnWidth, w);
        placed[n.id] = {
          x: levelIndex * LEVEL_GAP,
          y,
          w,
          h: PILL_HEIGHT,
          level: levelIndex,
        };
        y += PILL_HEIGHT + NODE_GAP;
      });
    });

    const columnCount = Math.max(1, levels.size);
    return {
      placed,
      levelOf,
      // Content spans x ∈ [0, width] and y ∈ [-height/2, +height/2].
      width: columnCount * LEVEL_GAP + maxColumnWidth,
      height: maxColumnHeight + PILL_HEIGHT * 2,
      columnCount,
    };
  }

  // ---- SVG scaffolding -----------------------------------------------------
  const svg = d3.select("#tree-svg");
  svg.selectAll("*").remove();

  const defs = svg.append("defs");
  defs
    .append("marker")
    .attr("id", "arrowhead")
    .attr("viewBox", "0 -5 10 10")
    .attr("refX", 9)
    .attr("refY", 0)
    .attr("markerWidth", 7)
    .attr("markerHeight", 7)
    .attr("orient", "auto")
    .append("path")
    .attr("d", "M0,-5L10,0L0,5")
    .attr("fill", "rgba(27,42,74,0.55)");

  // One background rect gives zoom/pan a surface that is never a pill.
  const gRoot = svg.append("g").attr("class", "graph-root");
  gRoot
    .append("rect")
    .attr("class", "graph-background")
    .attr("x", -100000)
    .attr("y", -100000)
    .attr("width", 200000)
    .attr("height", 200000)
    .attr("fill", "transparent");

  const gLinks = gRoot.append("g").attr("class", "links-layer");
  const gNodes = gRoot.append("g").attr("class", "nodes-layer");

  const zoom = d3
    .zoom()
    .scaleExtent([0.08, 2.2])
    // Refuse to start a pan/drag when the gesture begins on a pill or a
    // control. Without this, D3 treats the few pixels of movement in a normal
    // click as a pan and cancels the click event — the original bug where
    // clicking a concept appeared to do nothing.
    .filter((event) => {
      if (event.type === "wheel") return true;
      const t = event.target;
      if (t && t.closest &&
          t.closest(".tree-node, .tree-controls, .topbar, .panel, .vmodal, .list-modal, button, a, input")) {
        return false;
      }
      return true;
    })
    .on("zoom", (event) => {
      gRoot.attr("transform", event.transform);
    });

  svg.call(zoom).on("dblclick.zoom", null);

  // Content spans x ∈ [0, width] and y ∈ [-height/2, +height/2], so framing it
  // means mapping that box onto the viewport.
  function fitToView(duration = 500) {
    if (!layout) return;
    const w = window.innerWidth;
    const h = window.innerHeight;
    const margin = 70;
    const scale = Math.min(
      1.15,
      Math.max(0.08, Math.min((w - margin * 2) / layout.width, (h - margin * 2) / layout.height))
    );
    const tx = w / 2 - (layout.width / 2) * scale;
    const ty = h / 2; // the map is already centred on y = 0
    svg
      .transition()
      .duration(duration)
      .ease(d3.easeCubicOut)
      .call(zoom.transform, d3.zoomIdentity.translate(tx, ty).scale(scale));
  }

  // Bring one node into view, biased to the left so the detail panel (which
  // covers the right edge) never hides it.
  function centerOn(nodeId, duration = 500, scale) {
    const p = layout && layout.placed[nodeId];
    if (!p) return;
    const target = scale || Math.max(0.55, d3.zoomTransform(svg.node()).k);
    const w = window.innerWidth;
    const h = window.innerHeight;
    const tx = w * 0.34 - (p.x + p.w / 2) * target;
    const ty = h / 2 - (p.y + p.h / 2) * target;
    svg
      .transition()
      .duration(duration)
      .ease(d3.easeCubicOut)
      .call(zoom.transform, d3.zoomIdentity.translate(tx, ty).scale(target));
  }

  // ---- Render --------------------------------------------------------------
  let layout = null;
  let selectedId = null;

  function render(mode) {
    layout = buildLayout(mode);

    // Each column is already centred on y = 0 and starts at x = 0, so the
    // only thing left to do is frame it. Nothing is shifted here.

    // Links: an elbow from the right edge of `from` to the left edge of `to`.
    const links = EDGES.map((e) => ({ from: e.from, to: e.to })).filter(
      (l) => layout.placed[l.from] && layout.placed[l.to]
    );

    const linkSel = gLinks
      .selectAll("path.tree-link")
      .data(links, (d) => `${d.from}->${d.to}`);

    linkSel.exit().remove();

    linkSel
      .enter()
      .append("path")
      .attr("class", "tree-link")
      .attr("marker-end", "url(#arrowhead)")
      .merge(linkSel)
      .attr("d", (d) => {
        const s = layout.placed[d.from];
        const t = layout.placed[d.to];
        const sx = s.x + s.w;
        const sy = s.y + s.h / 2;
        const tx = t.x;
        const ty = t.y + t.h / 2;
        const midX = sx + Math.max(24, (tx - sx) / 2);
        return `M ${sx} ${sy} C ${midX} ${sy}, ${midX} ${ty}, ${tx} ${ty}`;
      });

    // Nodes: a <g> per concept, positioned at its column/row.
    const nodeSel = gNodes
      .selectAll("g.tree-node")
      .data(NODES, (d) => d.id);

    nodeSel.exit().remove();

    const nodeEnter = nodeSel
      .enter()
      .append("g")
      .attr("class", "tree-node")
      .attr("tabindex", 0)
      .attr("role", "button");

    nodeEnter.append("rect").attr("class", "node-pill");
    nodeEnter.append("text").attr("class", "node-label");
    nodeEnter.append("circle").attr("class", "focus-ring").attr("r", 20).style("display", "none");

    const all = nodeEnter.merge(nodeSel);

    all
      .attr("transform", (d) => {
        const p = layout.placed[d.id];
        return `translate(${p.x},${p.y})`;
      })
      .attr("aria-label", (d) => d.label)
      .classed("is-selected", (d) => d.id === selectedId);

    all
      .select("rect.node-pill")
      .attr("width", (d) => layout.placed[d.id].w)
      .attr("height", PILL_HEIGHT)
      .style("stroke", (d) => lectureColor(lectureOf(d)))
      .style("stroke-width", "2px")
      .style("fill", (d) => "#FDFCF8")
      .style("pointer-events", "all");

    all
      .select("text.node-label")
      .attr("x", 17)
      .attr("y", PILL_HEIGHT / 2)
      .text((d) => truncateToPill(d.label, layout.placed[d.id].w));

    all.select("circle.focus-ring").attr("cx", 20).attr("cy", PILL_HEIGHT / 2);

    // --- interaction: the whole pill <g> is the button -----------------------
    all
      .on("click", (event, d) => {
        event.stopPropagation();
        select(d.id);
      })
      .on("keydown", (event, d) => {
        if (event.key === "Enter" || event.key === " ") {
          event.preventDefault();
          select(d.id);
        }
      })
      .on("pointerenter", (event, d) => highlightPath(d.id))
      .on("pointerleave", () => highlightPath(selectedId))
      .on("focus", (event, d) => highlightPath(d.id))
      .on("blur", () => highlightPath(selectedId));
  }

  // ---- Path highlighting ---------------------------------------------------
  function ancestorsOf(id) {
    const seen = new Set();
    const stack = [id];
    while (stack.length) {
      const cur = stack.pop();
      if (seen.has(cur)) continue;
      seen.add(cur);
      (parents[cur] || []).forEach((p) => stack.push(p));
    }
    return seen;
  }

  function highlightPath(id) {
    if (!id) {
      gLinks.selectAll("path.tree-link").classed("path-highlight", false).classed("dimmed", false);
      gNodes.selectAll("g.tree-node").classed("dimmed", false);
      return;
    }
    const path = ancestorsOf(id);
    gLinks.selectAll("path.tree-link").each(function (l) {
      const on = path.has(l.from) && path.has(l.to);
      d3.select(this).classed("path-highlight", on).classed("dimmed", !on);
    });
    gNodes.selectAll("g.tree-node").classed("dimmed", (d) => !path.has(d.id));
  }

  // ---- Selection + detail panel -------------------------------------------
  function setText(id, value) {
    const el = $(id);
    if (el) el.textContent = value;
  }

  function showPanel() {
    if (!panel) return;
    panel.classList.remove("is-hidden");
    panel.hidden = false;
    panel.removeAttribute("hidden");
    panel.style.display = "block";
  }

  function select(id) {
    selectedId = id;
    gNodes.selectAll("g.tree-node").classed("is-selected", (d) => d.id === id);

    const node = byId[id];
    if (!node) return;

    highlightPath(id);

    const pos = lectureOf(node);
    const meta = lectureMeta(pos);
    const lecLabel = meta.title ? cleanTitle(meta.title) : `Lecture ${pos}`;
    const occ = (node.occurrences && node.occurrences[0]) || {};
    const videoId = occ.video_id;

    setText("panelLecture", `Lecture ${pos} • ${lecLabel}`);
    setText("panelTitle", node.label);
    setText("panelDef", node.definition || "No definition was recorded for this concept.");
    setText("panelTime", fmtTime(occ.start));

    // Prerequisites
    const prereqIds = parents[id] || [];
    const list = $("panelPrereqList");
    const heading = $("panelPrereqHeading");
    const sub = $("panelPrereqSub");
    const box = $("panelPrereq");

    if (list && box) {
      list.innerHTML = "";
      if (prereqIds.length) {
        if (heading) heading.textContent = "⚠️ Learn these first:";
        if (sub) sub.textContent = `This concept builds on ${prereqIds.length} earlier one${prereqIds.length === 1 ? "" : "s"}.`;
        prereqIds.forEach((pid) => {
          const pn = byId[pid];
          if (!pn) return;
          const li = document.createElement("li");
          li.textContent = "← " + pn.label;
          li.title = `Go to ${pn.label}`;
          li.onclick = (e) => {
            e.stopPropagation();
            select(pid);
            centerOn(pid, 500);
          };
          list.appendChild(li);
        });
      } else {
        if (heading) heading.textContent = "✅ Foundational concept";
        if (sub) sub.textContent = "Nothing has to be learned before this one.";
      }
      box.style.display = "block";
    }

    // Watch-this-moment
    const watch = $("panelWatch");
    if (watch) {
      if (videoId) {
        watch.style.display = "flex";
        watch.onclick = () => openVideoAt(videoId, occ.start, node.label, `Lecture ${pos}`);
      } else {
        watch.style.display = "none";
      }
    }

    const notes = $("panelNotes");
    if (notes) {
      if (videoId) {
        notes.href = `/study/${encodeURIComponent(videoId)}`;
        notes.style.display = "flex";
        notes.innerHTML = "<span>📖</span> Open full notes, quiz &amp; AI tutor";
      } else {
        notes.style.display = "none";
      }
    }

    showPanel();

    // Ink ring pulse
    const sel = gNodes.selectAll("g.tree-node").filter((d) => d.id === id);
    sel
      .select(".focus-ring")
      .style("display", "block")
      .style("opacity", 1)
      .transition()
      .duration(1100)
      .style("opacity", 0)
      .on("end", function () {
        d3.select(this).style("display", "none");
      });
  }

  // ---- Video modal ---------------------------------------------------------
  function openVideoAt(videoId, seconds, title, label) {
    if (!vmodal || !videoId) return;
    const start = Math.max(0, Math.round(seconds || 0));
    setText("vmodalTitle", title || "Watch this moment");
    setText("vmodalBadge", label || "Lecture");
    setText("vmodalNote", `Starts at ${fmtTime(start)}`);
    const frame = $("vmodalFrame");
    if (frame) {
      frame.innerHTML =
        `<iframe src="https://www.youtube.com/embed/${encodeURIComponent(videoId)}` +
        `?start=${start}&autoplay=1&rel=0" allow="autoplay; encrypted-media" allowfullscreen></iframe>`;
    }
    vmodal.hidden = false;
    vmodal.removeAttribute("hidden");
  }

  function closeVideo() {
    if (!vmodal) return;
    vmodal.hidden = true;
    vmodal.setAttribute("hidden", "");
    const frame = $("vmodalFrame");
    if (frame) frame.innerHTML = "";
  }

  const vmodalClose = $("vmodalClose");
  if (vmodalClose) vmodalClose.onclick = closeVideo;
  if (vmodal) {
    vmodal.onclick = (e) => {
      if (e.target === vmodal) closeVideo();
    };
  }

  const panelClose = $("panelClose");
  if (panelClose) {
    panelClose.onclick = () => {
      panel.classList.add("is-hidden");
      panel.hidden = true;
      panel.setAttribute("hidden", "");
      panel.style.display = "none";
      selectedId = null;
      gNodes.selectAll("g.tree-node").classed("is-selected", false);
      highlightPath(null);
    };
  }

  // ---- Concepts Catalog Modal ----------------------------------------------
  const conceptsModal = $("conceptsModal");
  const conceptsModalClose = $("conceptsModalClose");
  const modalConceptSearch = $("modalConceptSearch");
  const modalConceptCount = $("modalConceptCount");
  const conceptsLectureTags = $("conceptsLectureTags");
  const modalConceptsList = $("modalConceptsList");

  let activeLectureFilter = null; // null = all

  function openConceptsModal() {
    if (!conceptsModal) return;
    conceptsModal.hidden = false;
    conceptsModal.removeAttribute("hidden");
    if (modalConceptCount) modalConceptCount.textContent = NODES.length;
    renderLectureFilterTags();
    renderConceptsList(modalConceptSearch ? modalConceptSearch.value : "");
    if (modalConceptSearch) {
      setTimeout(() => modalConceptSearch.focus(), 60);
    }
  }

  function closeConceptsModal() {
    if (!conceptsModal) return;
    conceptsModal.hidden = true;
    conceptsModal.setAttribute("hidden", "");
  }

  function renderLectureFilterTags() {
    if (!conceptsLectureTags) return;
    conceptsLectureTags.innerHTML = "";

    // "All" tag
    const allBtn = document.createElement("button");
    allBtn.type = "button";
    allBtn.className = `filter-tag ${activeLectureFilter === null ? "active" : ""}`;
    allBtn.textContent = `All (${NODES.length})`;
    allBtn.onclick = () => {
      activeLectureFilter = null;
      renderLectureFilterTags();
      renderConceptsList(modalConceptSearch ? modalConceptSearch.value : "");
    };
    conceptsLectureTags.appendChild(allBtn);

    // Group counts by lecture
    const lectureCounts = {};
    NODES.forEach((n) => {
      const pos = lectureOf(n);
      lectureCounts[pos] = (lectureCounts[pos] || 0) + 1;
    });

    const positions = Object.keys(lectureCounts).map(Number).sort((a, b) => a - b);
    positions.forEach((pos) => {
      const tag = document.createElement("button");
      tag.type = "button";
      tag.className = `filter-tag ${activeLectureFilter === pos ? "active" : ""}`;
      const meta = lectureMeta(pos);
      const lecLabel = meta.title ? cleanTitle(meta.title) : `Lecture ${pos}`;
      tag.textContent = `Lec ${pos} (${lectureCounts[pos]})`;
      tag.title = `Lecture ${pos}: ${lecLabel}`;
      tag.onclick = () => {
        activeLectureFilter = activeLectureFilter === pos ? null : pos;
        renderLectureFilterTags();
        renderConceptsList(modalConceptSearch ? modalConceptSearch.value : "");
      };
      conceptsLectureTags.appendChild(tag);
    });
  }

  function renderConceptsList(filterText = "") {
    if (!modalConceptsList) return;
    modalConceptsList.innerHTML = "";

    const q = (filterText || "").trim().toLowerCase();
    const filtered = NODES.filter((n) => {
      const pos = lectureOf(n);
      if (activeLectureFilter !== null && pos !== activeLectureFilter) return false;
      if (!q) return true;
      const labelMatch = (n.label || "").toLowerCase().includes(q);
      const defMatch = (n.definition || "").toLowerCase().includes(q);
      const meta = lectureMeta(pos);
      const lecMatch = (meta.title || "").toLowerCase().includes(q);
      return labelMatch || defMatch || lecMatch;
    });

    if (modalConceptCount) modalConceptCount.textContent = filtered.length;

    if (filtered.length === 0) {
      const empty = document.createElement("div");
      empty.className = "list-modal-empty";
      empty.textContent = "No matching concepts found.";
      modalConceptsList.appendChild(empty);
      return;
    }

    filtered.forEach((n) => {
      const pos = lectureOf(n);
      const color = lectureColor(pos);
      const prereqCount = (parents[n.id] || []).length;

      const item = document.createElement("div");
      item.className = "concept-list-item";
      item.setAttribute("role", "button");
      item.setAttribute("tabindex", "0");

      const main = document.createElement("div");
      main.className = "concept-item-main";

      const titleRow = document.createElement("div");
      titleRow.className = "concept-item-title-row";

      const badge = document.createElement("span");
      badge.className = "concept-item-lecture";
      badge.style.backgroundColor = color;
      badge.textContent = `Lecture ${pos}`;
      titleRow.appendChild(badge);

      const title = document.createElement("div");
      title.className = "concept-item-title";
      title.textContent = n.label;
      titleRow.appendChild(title);

      main.appendChild(titleRow);

      if (n.definition) {
        const def = document.createElement("p");
        def.className = "concept-item-def";
        def.textContent = n.definition;
        main.appendChild(def);
      }

      item.appendChild(main);

      const metaCol = document.createElement("div");
      metaCol.className = "concept-item-meta";

      const prereqBadge = document.createElement("span");
      prereqBadge.className = "concept-item-prereq";
      prereqBadge.textContent = prereqCount === 0 ? "Foundational" : `${prereqCount} prereq${prereqCount === 1 ? "" : "s"}`;
      metaCol.appendChild(prereqBadge);

      const jumpBtn = document.createElement("span");
      jumpBtn.className = "concept-item-jump";
      jumpBtn.innerHTML = `<span>Focus</span> ➔`;
      metaCol.appendChild(jumpBtn);

      item.appendChild(metaCol);

      item.onclick = () => {
        closeConceptsModal();
        select(n.id);
        centerOn(n.id, 500, 1);
      };

      item.onkeydown = (e) => {
        if (e.key === "Enter" || e.key === " ") {
          e.preventDefault();
          item.click();
        }
      };

      modalConceptsList.appendChild(item);
    });
  }

  if (conceptsModalClose) conceptsModalClose.onclick = closeConceptsModal;
  if (conceptsModal) {
    conceptsModal.onclick = (e) => {
      if (e.target === conceptsModal) closeConceptsModal();
    };
  }
  if (modalConceptSearch) {
    modalConceptSearch.addEventListener("input", (e) => {
      renderConceptsList(e.target.value);
    });
  }

  // ---- Prerequisite Links Modal --------------------------------------------
  const linksModal = $("linksModal");
  const linksModalClose = $("linksModalClose");
  const modalLinkSearch = $("modalLinkSearch");
  const modalLinkCount = $("modalLinkCount");
  const modalLinksList = $("modalLinksList");
  const btnToggleAllLinks = $("btnToggleAllLinks");
  const toggleAllLinksText = $("toggleAllLinksText");

  let allLinksActive = false;

  function openLinksModal() {
    if (!linksModal) return;
    linksModal.hidden = false;
    linksModal.removeAttribute("hidden");
    if (modalLinkCount) modalLinkCount.textContent = EDGES.length;
    renderLinksList(modalLinkSearch ? modalLinkSearch.value : "");
    if (modalLinkSearch) {
      setTimeout(() => modalLinkSearch.focus(), 60);
    }
  }

  function closeLinksModal() {
    if (!linksModal) return;
    linksModal.hidden = true;
    linksModal.setAttribute("hidden", "");
  }

  function renderLinksList(filterText = "") {
    if (!modalLinksList) return;
    modalLinksList.innerHTML = "";

    const q = (filterText || "").trim().toLowerCase();
    const filtered = EDGES.filter((e) => {
      const fromNode = byId[e.from];
      const toNode = byId[e.to];
      if (!fromNode || !toNode) return false;
      if (!q) return true;
      return (
        fromNode.label.toLowerCase().includes(q) ||
        toNode.label.toLowerCase().includes(q)
      );
    });

    if (modalLinkCount) modalLinkCount.textContent = filtered.length;

    if (filtered.length === 0) {
      const empty = document.createElement("div");
      empty.className = "list-modal-empty";
      empty.textContent = "No matching prerequisite links found.";
      modalLinksList.appendChild(empty);
      return;
    }

    filtered.forEach((e) => {
      const fromNode = byId[e.from];
      const toNode = byId[e.to];
      if (!fromNode || !toNode) return;

      const fromPos = lectureOf(fromNode);
      const toPos = lectureOf(toNode);

      const item = document.createElement("div");
      item.className = "link-list-item";
      item.setAttribute("role", "button");
      item.setAttribute("tabindex", "0");

      const flow = document.createElement("div");
      flow.className = "link-connection-flow";

      // From Chip
      const fromChip = document.createElement("span");
      fromChip.className = "link-node-chip";
      const fromDot = document.createElement("span");
      fromDot.style.cssText = `display:inline-block;width:8px;height:8px;border-radius:50%;background:${lectureColor(fromPos)};flex-shrink:0;`;
      fromChip.appendChild(fromDot);
      fromChip.appendChild(document.createTextNode(fromNode.label));
      flow.appendChild(fromChip);

      // Arrow
      const arrow = document.createElement("span");
      arrow.className = "link-arrow";
      arrow.textContent = "➔";
      arrow.title = "is prerequisite for";
      flow.appendChild(arrow);

      // To Chip
      const toChip = document.createElement("span");
      toChip.className = "link-node-chip";
      const toDot = document.createElement("span");
      toDot.style.cssText = `display:inline-block;width:8px;height:8px;border-radius:50%;background:${lectureColor(toPos)};flex-shrink:0;`;
      toChip.appendChild(toDot);
      toChip.appendChild(document.createTextNode(toNode.label));
      flow.appendChild(toChip);

      item.appendChild(flow);

      const jumpBtn = document.createElement("span");
      jumpBtn.className = "link-item-jump";
      jumpBtn.textContent = "Inspect on Map";
      item.appendChild(jumpBtn);

      item.onclick = () => {
        closeLinksModal();
        select(toNode.id);
        centerOn(toNode.id, 500, 1);
      };

      item.onkeydown = (ev) => {
        if (ev.key === "Enter" || ev.key === " ") {
          ev.preventDefault();
          item.click();
        }
      };

      modalLinksList.appendChild(item);
    });
  }

  function toggleAllLinksHighlight() {
    allLinksActive = !allLinksActive;
    if (allLinksActive) {
      gLinks.selectAll("path.tree-link").classed("path-highlight", true).classed("dimmed", false);
      gNodes.selectAll("g.tree-node").classed("dimmed", false);
      if (toggleAllLinksText) toggleAllLinksText.textContent = "Reset link highlighting";
    } else {
      highlightPath(selectedId);
      if (toggleAllLinksText) toggleAllLinksText.textContent = "Highlight all links";
    }
  }

  if (btnToggleAllLinks) btnToggleAllLinks.onclick = toggleAllLinksHighlight;
  if (linksModalClose) linksModalClose.onclick = closeLinksModal;
  if (linksModal) {
    linksModal.onclick = (e) => {
      if (e.target === linksModal) closeLinksModal();
    };
  }
  if (modalLinkSearch) {
    modalLinkSearch.addEventListener("input", (e) => {
      renderLinksList(e.target.value);
    });
  }

  // Wire topbar stat buttons
  if (statNodes) {
    statNodes.onclick = (e) => {
      e.stopPropagation();
      openConceptsModal();
    };
  }
  if (statEdges) {
    statEdges.onclick = (e) => {
      e.stopPropagation();
      openLinksModal();
    };
  }

  document.addEventListener("keydown", (e) => {
    if (e.key === "Escape") {
      closeVideo();
      closeConceptsModal();
      closeLinksModal();
      if (panel) {
        panel.classList.add("is-hidden");
        panel.hidden = true;
        panel.setAttribute("hidden", "");
        panel.style.display = "none";
      }
    }
  });

  // ---- Toolbar -------------------------------------------------------------
  const wire = (id, fn) => {
    const el = $(id);
    if (el) el.onclick = fn;
  };

  wire("btnZoomIn", () => svg.transition().duration(220).call(zoom.scaleBy, 1.3));
  wire("btnZoomOut", () => svg.transition().duration(220).call(zoom.scaleBy, 0.7));
  wire("btnFit", () => fitToView(500));
  wire("btnCenter", () => {
    const first = NODES[0];
    if (first) {
      select(first.id);
      centerOn(first.id, 500, 1);
    }
  });

  // ---- Search --------------------------------------------------------------
  function findConcept(query) {
    const q = String(query || "").trim().toLowerCase();
    if (!q) return null;
    let exact = NODES.find((n) => n.label.toLowerCase() === q);
    if (exact) return exact;
    return NODES.find((n) => n.label.toLowerCase().includes(q)) || null;
  }

  function goto(query) {
    const node = findConcept(query);
    if (!node) return;
    select(node.id);
    centerOn(node.id, 550, 1);
  }

  if (searchInput) {
    searchInput.addEventListener("change", () => goto(searchInput.value));
    searchInput.addEventListener("keydown", (e) => {
      if (e.key === "Enter") {
        e.preventDefault();
        goto(searchInput.value);
      }
    });
  }

  // ---- Initial paint -------------------------------------------------------
  let currentMode = "curriculum";

  function start(mode) {
    currentMode = mode;
    selectedId = null;
    const keepClose = panel && panel.classList.contains("is-hidden");
    render(mode);
    if (keepClose) highlightPath(null);
    fitToView(0);

    // Open on the first foundational concept so the panel is not empty.
    const startNode = NODES.find((n) => (parents[n.id] || []).length === 0) || NODES[0];
    if (startNode) {
      setTimeout(() => select(startNode.id), 120);
    }
  }

  wire("btnModeCurriculum", () => {
    if (currentMode === "curriculum") return;
    const a = $("btnModeCurriculum");
    const b = $("btnModePrereq");
    if (a) a.classList.add("active");
    if (b) b.classList.remove("active");
    start("curriculum");
  });

  wire("btnModePrereq", () => {
    if (currentMode === "prereq") return;
    const a = $("btnModeCurriculum");
    const b = $("btnModePrereq");
    if (b) b.classList.add("active");
    if (a) a.classList.remove("active");
    start("prereq");
  });

  window.addEventListener("resize", () => fitToView(200));

  start("curriculum");
})();
