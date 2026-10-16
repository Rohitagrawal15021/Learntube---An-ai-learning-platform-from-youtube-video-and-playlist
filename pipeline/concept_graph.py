"""Build a prerequisite knowledge graph for a playlist from its transcripts.

Input (produced by ``cie/playlist_transcripts.py``):
    data/transcripts/<playlist_id>/
        <video_id>.json  -> {video_id, title, position, segments:[{text,start,...}]}
        manifest.json    -> {playlist_id, playlist_title, videos:[{position, video_id, title}]}

Output:
    data/generated/<playlist_id>_graph.json -> {playlist_id, title, nodes, edges}

Each node is one concept, merged across the videos that teach it:
    {id, label, definition, occurrences:[{video_id, start, position}]}
Each edge means "learn `from` before `to`":
    {from, to}
"""

import json
import re
from pathlib import Path

from google.genai import types

from config import generate_with_retry

PROJECT_ROOT = Path(__file__).resolve().parents[1]
TRANSCRIPTS_DIR = PROJECT_ROOT / "data" / "transcripts"
GENERATED_DIR = PROJECT_ROOT / "data" / "generated"

MODEL = "gemini-3.5-flash"

# Group transcript lines into ~30s blocks before asking the model to anchor a
# concept to a time. Fewer, timestamped blocks keep the prompt small AND let the
# model pick a real timestamp even when captions are in another language.
BLOCK_SECONDS = 30

# Two concepts merge into one node when their embeddings are at least this close
# (cosine on normalised vectors). Tuned to merge "gradient descent" across
# videos without collapsing genuinely different topics.
MERGE_THRESHOLD = 0.82


def _slugify(label):
    """Turn a concept label into a filesystem/URL-safe id."""
    slug = re.sub(r"[^a-z0-9]+", "-", str(label).lower()).strip("-")
    return slug or "concept"


def _parse_json(text):
    """Parse model output that should be JSON, tolerating code fences / stray prose."""
    if not text:
        return None
    cleaned = text.strip()
    # Strip ```json ... ``` fences if the model added them.
    cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned)
    cleaned = re.sub(r"\s*```$", "", cleaned)
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        pass
    # Last resort: grab the first {...} or [...] span.
    match = re.search(r"(\{.*\}|\[.*\])", cleaned, re.DOTALL)
    if match:
        try:
            return json.loads(match.group(1))
        except json.JSONDecodeError:
            return None
    return None


def _group_segments(segments, block_seconds=BLOCK_SECONDS):
    """Collapse many short caption lines into coarse timestamped blocks."""
    blocks = []
    current_text = []
    block_start = None

    for seg in segments:
        start = float(seg.get("start", 0) or 0)
        if block_start is None:
            block_start = start
        current_text.append(str(seg.get("text", "")).strip())
        if start - block_start >= block_seconds:
            blocks.append({"start": round(block_start), "text": " ".join(current_text)})
            current_text = []
            block_start = None

    if current_text:
        blocks.append({"start": round(block_start or 0), "text": " ".join(current_text)})

    return blocks


def _cap_blocks(blocks, max_chars=11000):
    """Keep a prompt within the free-tier token budget by evenly sampling blocks
    across the whole lecture (so we still cover start → end, not just the intro)."""
    total = sum(len(b.get("text", "")) + 12 for b in blocks)
    if total <= max_chars or len(blocks) <= 2:
        return blocks
    step = max(1, total // max_chars)          # sample every step-th block
    sampled = blocks[::step] or blocks[:1]
    out, used = [], 0
    for b in sampled:
        c = len(b.get("text", "")) + 12
        if used + c > max_chars and out:
            break
        out.append(b)
        used += c
    return out


def _snap_to_block(start, blocks):
    """Snap a model-supplied time to the nearest real block start."""
    if not blocks:
        return 0
    try:
        target = float(start)
    except (TypeError, ValueError):
        return blocks[0]["start"]
    return min((b["start"] for b in blocks), key=lambda s: abs(s - target))


def extract_video_concepts(transcript, position=None, title=None):
    """One light LLM pass over a single video's transcript -> concept list.

    Returns a list of {label, definition, start, video_id, position}. The model
    reads the timestamped blocks and picks the second where each concept is
    first introduced, so this works even for non-English captions.
    """
    segments = transcript.get("segments") or []
    video_id = transcript.get("video_id", "")
    position = position if position is not None else transcript.get("position")
    title = title or transcript.get("title") or video_id

    blocks = _group_segments(segments)
    if not blocks:
        return []

    prompt_blocks = _cap_blocks(blocks)   # keep the prompt within free-tier limits
    numbered = "\n".join(f"[{b['start']}] {b['text']}" for b in prompt_blocks)

    prompt = f"""You are mapping the key concepts taught in one lecture of a course.

Lecture position in course: {position}
Lecture title: {title}

Below is the transcript, split into blocks. Each block begins with its start
time in seconds in square brackets, e.g. [120]. The captions may be in another
language — ALWAYS answer in English.

List the 5 to 12 most important concepts this lecture teaches, in the order they
are taught. For each concept return:
- "label": a short concept name (2-5 words), in English
- "definition": one plain-English sentence explaining it
- "start": the start-time number (from a [number] marker) of the block where the
  concept is FIRST introduced

Return ONLY valid JSON, no markdown, in exactly this shape:
{{"concepts": [{{"label": "", "definition": "", "start": 0}}]}}

Transcript:
{numbered}
"""

    response = generate_with_retry(
        model=MODEL,
        contents=prompt,
        config=types.GenerateContentConfig(
            temperature=0.2,
            response_mime_type="application/json",
        ),
    )

    data = _parse_json(getattr(response, "text", "") or "")
    if isinstance(data, dict):
        raw = data.get("concepts") or data.get("items") or []
    elif isinstance(data, list):
        raw = data
    else:
        raw = []

    concepts = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        label = str(item.get("label", "")).strip()
        definition = str(item.get("definition", "")).strip()
        if not label:
            continue
        concepts.append({
            "label": label,
            "definition": definition,
            "start": _snap_to_block(item.get("start", 0), blocks),
            "video_id": video_id,
            "position": position,
        })

    return concepts


def _dot(a, b):
    return sum(x * y for x, y in zip(a, b))


def merge_concepts(all_concepts):
    """Merge concepts that recur across videos into single nodes.

    Uses the project's multilingual embedder: two concepts merge when their
    (label + definition) vectors are at least ``MERGE_THRESHOLD`` close, with an
    exact normalised-label match as a cheap first test. Each node keeps every
    place it is taught in ``occurrences`` (earliest position = where to send a
    student for remediation).
    """
    if not all_concepts:
        return []

    # Lazy import: pulls in SentenceTransformer only when actually building.
    from rag.embedding.embedder import create_embeddings

    texts = [f"{c['label']}. {c['definition']}" for c in all_concepts]
    vectors = create_embeddings(texts)

    nodes = []          # each: {id, label, definition, occurrences, _vec}
    used_ids = set()

    for concept, vector in zip(all_concepts, vectors):
        norm_label = concept["label"].strip().lower()
        occurrence = {
            "video_id": concept["video_id"],
            "start": concept["start"],
            "position": concept["position"],
        }

        match = None
        for node in nodes:
            if node["_norm_label"] == norm_label or _dot(node["_vec"], vector) >= MERGE_THRESHOLD:
                match = node
                break

        if match:
            match["occurrences"].append(occurrence)
            continue

        base_id = _slugify(concept["label"])
        node_id = base_id
        suffix = 2
        while node_id in used_ids:
            node_id = f"{base_id}-{suffix}"
            suffix += 1
        used_ids.add(node_id)

        nodes.append({
            "id": node_id,
            "label": concept["label"],
            "definition": concept["definition"],
            "occurrences": [occurrence],
            "_norm_label": norm_label,
            "_vec": vector,
        })

    # Sort each node's occurrences so the earliest teaching spot is first, and
    # order nodes by where they first appear in the course.
    for node in nodes:
        node["occurrences"].sort(key=lambda o: (o["position"] or 0, o["start"]))
    nodes.sort(key=lambda n: (n["occurrences"][0]["position"] or 0, n["occurrences"][0]["start"]))

    # Drop the private helper fields before returning.
    for node in nodes:
        node.pop("_norm_label", None)
        node.pop("_vec", None)

    return nodes


def _first_position(node):
    return node["occurrences"][0]["position"] or 0


def _detect_prerequisites_batch(nodes):
    """Ask the LLM which concepts must be understood before which (one batch)."""
    if len(nodes) < 2:
        return []

    listing = "\n".join(
        f"{node['id']} (first taught in lecture {_first_position(node)}): "
        f"{node['label']} — {node['definition']}"
        for node in nodes
    )

    prompt = f"""You are building a prerequisite map for a course.

Here are the concepts, each with a stable id and the lecture it is first taught in:
{listing}

List the prerequisite relationships: pairs where one concept must be understood
BEFORE another makes sense. Use ONLY the ids above. Do not invent ids. Only
include genuine conceptual dependencies (not every pair). Prefer edges that go
from earlier-taught toward later-taught concepts.

Return ONLY valid JSON in exactly this shape:
{{"edges": [{{"from": "<id>", "to": "<id>"}}]}}
"""

    response = generate_with_retry(
        model=MODEL,
        contents=prompt,
        config=types.GenerateContentConfig(
            temperature=0.2,
            response_mime_type="application/json",
        ),
    )

    data = _parse_json(getattr(response, "text", "") or "")
    raw = data.get("edges", []) if isinstance(data, dict) else (data if isinstance(data, list) else [])

    known = {node["id"] for node in nodes}
    edges = []
    seen = set()
    for item in raw:
        if not isinstance(item, dict):
            continue
        src = str(item.get("from", "")).strip()
        dst = str(item.get("to", "")).strip()
        if src in known and dst in known and src != dst and (src, dst) not in seen:
            edges.append({"from": src, "to": dst})
            seen.add((src, dst))

    return edges


# Maximum concepts per LLM call for prerequisite detection.
# 40 keeps prompts well under token limits while producing dense edges.
PREREQ_BATCH_SIZE = 40
PREREQ_OVERLAP = 10  # Overlap between windows so cross-boundary edges form


def detect_prerequisites(nodes):
    """Detect prerequisite edges, batching large concept lists into windows.

    For small playlists (≤ PREREQ_BATCH_SIZE concepts) this is a single LLM
    call. For larger ones, a sliding window ensures every pair of nearby
    concepts gets a chance to form an edge.
    """
    if len(nodes) < 2:
        return []

    if len(nodes) <= PREREQ_BATCH_SIZE:
        return _detect_prerequisites_batch(nodes)

    # Sliding window over concepts (sorted by first occurrence)
    all_edges = []
    seen = set()
    step = PREREQ_BATCH_SIZE - PREREQ_OVERLAP

    for start in range(0, len(nodes), step):
        window = nodes[start : start + PREREQ_BATCH_SIZE]
        if len(window) < 2:
            break

        print(f"    Detecting prerequisites for concepts {start + 1}–{start + len(window)} of {len(nodes)}...")
        batch_edges = _detect_prerequisites_batch(window)

        for edge in batch_edges:
            key = (edge["from"], edge["to"])
            if key not in seen:
                all_edges.append(edge)
                seen.add(key)

    print(f"    Total prerequisite edges detected: {len(all_edges)}")
    return all_edges


def make_dag(nodes, edges):
    """Remove cycles so the graph is a clean DAG (a valid learning order)."""
    import networkx as nx

    pos = {node["id"]: _first_position(node) for node in nodes}

    graph = nx.DiGraph()
    graph.add_nodes_from(pos)
    for edge in edges:
        graph.add_edge(edge["from"], edge["to"])

    # Repeatedly find a cycle and drop its most "backwards" edge (the one that
    # points from a later-taught concept to an earlier one).
    guard = 0
    while not nx.is_directed_acyclic_graph(graph) and guard < 1000:
        guard += 1
        try:
            cycle = nx.find_cycle(graph)
        except nx.NetworkXNoCycle:
            break
        drop = max(cycle, key=lambda e: pos.get(e[0], 0) - pos.get(e[1], 0))
        graph.remove_edge(drop[0], drop[1])

    kept = set(graph.edges())
    return [edge for edge in edges if (edge["from"], edge["to"]) in kept]


def _load_playlist(playlist_dir):
    """Return (playlist_id, title, [transcript dicts in course order])."""
    playlist_dir = Path(playlist_dir)
    manifest_path = playlist_dir / "manifest.json"

    order = []          # list of (position, video_id, title)
    title = playlist_dir.name
    playlist_id = playlist_dir.name

    if manifest_path.exists():
        with open(manifest_path, encoding="utf-8") as fh:
            manifest = json.load(fh)
        playlist_id = manifest.get("playlist_id", playlist_id)
        title = manifest.get("playlist_title", title)
        for item in manifest.get("videos", []):
            if item.get("status") in ("success", "cached") or (playlist_dir / f"{item.get('video_id')}.json").exists():
                order.append((item.get("position"), item["video_id"], item.get("title")))
    else:
        # No manifest: fall back to every <video_id>.json in the folder.
        for path in sorted(playlist_dir.glob("*.json")):
            if path.name == "manifest.json":
                continue
            with open(path, encoding="utf-8") as fh:
                data = json.load(fh)
            order.append((data.get("position"), data.get("video_id", path.stem), data.get("title")))

    order.sort(key=lambda t: (t[0] if t[0] is not None else 0))

    transcripts = []
    for position, video_id, vtitle in order:
        path = playlist_dir / f"{video_id}.json"
        if not path.exists():
            continue
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)
        data.setdefault("video_id", video_id)
        data.setdefault("position", position)
        data.setdefault("title", vtitle)
        transcripts.append(data)

    return playlist_id, title, transcripts


def build_graph(playlist_id=None, playlist_dir=None, limit=None, save=True):
    """Build and (optionally) save the knowledge graph for one playlist."""
    if playlist_dir is None:
        if playlist_id is None:
            raise ValueError("Pass playlist_id or playlist_dir")
        playlist_dir = TRANSCRIPTS_DIR / playlist_id

    playlist_id, title, transcripts = _load_playlist(playlist_dir)
    if limit:
        transcripts = transcripts[:limit]

    all_concepts = []
    for transcript in transcripts:
        concepts = extract_video_concepts(transcript)
        print(f"  [{transcript.get('position')}] {transcript.get('title')}: {len(concepts)} concepts")
        all_concepts.extend(concepts)

    nodes = merge_concepts(all_concepts)
    edges = detect_prerequisites(nodes)
    edges = make_dag(nodes, edges)

    graph = {"playlist_id": playlist_id, "title": title, "nodes": nodes, "edges": edges}

    if save:
        GENERATED_DIR.mkdir(parents=True, exist_ok=True)
        out_path = GENERATED_DIR / f"{playlist_id}_graph.json"
        with open(out_path, "w", encoding="utf-8") as fh:
            json.dump(graph, fh, indent=2, ensure_ascii=False)
        print(f"\nSaved graph to {out_path}")

    return graph


if __name__ == "__main__":
    import sys

    if len(sys.argv) > 1:
        target = sys.argv[1]
    else:
        # Default: the single playlist folder under data/transcripts, if any.
        folders = [p for p in TRANSCRIPTS_DIR.glob("*") if p.is_dir()]
        if not folders:
            raise SystemExit("No playlist folders found under data/transcripts/")
        target = folders[0].name

    lim = int(sys.argv[2]) if len(sys.argv) > 2 else None

    print(f"Building knowledge graph for: {target}" + (f" (first {lim} videos)" if lim else ""))
    result = build_graph(playlist_id=target, limit=lim)

    print(f"\nNodes: {len(result['nodes'])}   Edges: {len(result['edges'])}")
    print("\nSample concepts:")
    for node in result["nodes"][:8]:
        occ = node["occurrences"][0]
        print(f"  - {node['label']} (lec {occ['position']} @ {occ['start']}s)")
    print("\nSample prerequisites (learn A before B):")
    labels = {n["id"]: n["label"] for n in result["nodes"]}
    for edge in result["edges"][:10]:
        print(f"  - {labels.get(edge['from'], edge['from'])}  ->  {labels.get(edge['to'], edge['to'])}")
