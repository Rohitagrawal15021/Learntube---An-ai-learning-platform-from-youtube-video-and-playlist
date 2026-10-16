"""Generate a timestamp-anchored multiple-choice quiz for one video.

Each question is grounded in the lecture transcript and carries the second in
the video where its answer is discussed, so a wrong answer can send the student
straight to that moment (the quiz → YouTube-timeline idea).
"""

import glob
import json
import os
import re

from google.genai import types

from config import generate_with_retry

MODEL = "gemini-3.5-flash"
BLOCK_SECONDS = 45


def _load_segments(video_id):
    """Find the timestamped transcript saved for this video, return its segments."""
    paths = glob.glob(os.path.join("data", "transcripts", "*", f"{video_id}.json"))
    paths += glob.glob(os.path.join("data", "transcripts", f"{video_id}.json"))
    paths += [os.path.join("data", "generated", f"{video_id}_transcript.json")]
    for path in paths:
        if not os.path.isfile(path):
            continue
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
        except (OSError, json.JSONDecodeError):
            continue
        segs = data.get("segments") or []
        if segs:
            return segs
    return []


def _group_blocks(segments, block_seconds=BLOCK_SECONDS):
    """Collapse caption lines into coarse timestamped blocks."""
    blocks, cur, start = [], [], None
    for seg in segments:
        s = float(seg.get("start", 0) or 0)
        if start is None:
            start = s
        cur.append(str(seg.get("text", "")).strip())
        if s - start >= block_seconds:
            blocks.append({"start": round(start), "text": " ".join(cur)})
            cur, start = [], None
    if cur:
        blocks.append({"start": round(start or 0), "text": " ".join(cur)})
    return blocks


def _cap_blocks(blocks, max_chars=11000):
    """Evenly sample blocks so the quiz prompt fits the free-tier token budget."""
    total = sum(len(b.get("text", "")) + 12 for b in blocks)
    if total <= max_chars or len(blocks) <= 2:
        return blocks
    step = max(1, total // max_chars)
    sampled = blocks[::step] or blocks[:1]
    out, used = [], 0
    for b in sampled:
        c = len(b.get("text", "")) + 12
        if used + c > max_chars and out:
            break
        out.append(b)
        used += c
    return out


def _parse_json(text):
    if not text:
        return None
    cleaned = re.sub(r"^```(?:json)?\s*", "", text.strip())
    cleaned = re.sub(r"\s*```$", "", cleaned)
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        m = re.search(r"(\{.*\}|\[.*\])", cleaned, re.DOTALL)
        if m:
            try:
                return json.loads(m.group(1))
            except json.JSONDecodeError:
                return None
    return None


def generate_quiz(video_id, title=None, n=8):
    """Return a list of timestamp-anchored MCQs for this video (or [] if no transcript)."""
    segments = _load_segments(video_id)
    if not segments:
        return []
    blocks = _group_blocks(segments)
    if not blocks:
        return []
    prompt_blocks = _cap_blocks(blocks)   # keep the prompt within free-tier limits
    valid_starts = set(b["start"] for b in prompt_blocks)
    numbered = "\n".join(f"[{b['start']}] {b['text']}" for b in prompt_blocks)

    prompt = f"""You are writing a quiz on one lecture, titled "{title or video_id}".

Below is the transcript in blocks. Each block starts with its start-time in
seconds in square brackets, e.g. [120]. The captions may be in another language
— ALWAYS write the quiz in English.

Write {n} multiple-choice questions that test understanding of this lecture.
For each question:
- "question": a clear question in English
- "options": exactly 4 short answer options, all plausible
- "answer_index": the index (0-3) of the correct option
- "explanation": one sentence saying why the answer is right
- "start": the start-time number (from a [number] marker) of the block where
  this is explained, so the student can rewatch that moment

Only ask things the transcript actually covers. Return ONLY valid JSON:
{{"questions": [{{"question":"","options":["","","",""],"answer_index":0,"explanation":"","start":0}}]}}

Transcript:
{numbered}
"""

    response = generate_with_retry(
        model=MODEL,
        contents=prompt,
        config=types.GenerateContentConfig(temperature=0.3, response_mime_type="application/json"),
    )
    data = _parse_json(getattr(response, "text", "") or "")
    raw = data.get("questions") if isinstance(data, dict) else (data if isinstance(data, list) else [])

    def snap(start):
        try:
            target = float(start)
        except (TypeError, ValueError):
            return blocks[0]["start"]
        return min(valid_starts, key=lambda s: abs(s - target))

    quiz = []
    for i, item in enumerate(raw or []):
        if not isinstance(item, dict):
            continue
        q = str(item.get("question", "")).strip()
        opts = item.get("options") or []
        opts = [str(o).strip() for o in opts if str(o).strip()]
        try:
            ai = int(item.get("answer_index", 0))
        except (TypeError, ValueError):
            ai = 0
        if not q or len(opts) != 4 or not (0 <= ai < 4):
            continue
        quiz.append({
            "id": f"q{i}",
            "question": q,
            "options": opts,
            "answer_index": ai,
            "explanation": str(item.get("explanation", "")).strip(),
            "start": snap(item.get("start", 0)),
            "video_id": video_id,
        })
    return quiz
