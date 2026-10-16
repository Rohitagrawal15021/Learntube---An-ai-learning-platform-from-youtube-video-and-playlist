import os
import re
import sys
import json
import traceback
from flask import Flask, jsonify, render_template, request, send_file, redirect, url_for

# The pipeline prints debug lines containing transcript text, which can be in any
# language (e.g. Hindi). On Windows the console defaults to cp1252 and those
# prints raise UnicodeEncodeError mid-pipeline — force UTF-8 so they can't.
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding='utf-8', errors='replace')
    except Exception:
        pass

from rag.chat import answer_video_question
import auth

app = Flask(__name__)
app.config['TEMPLATES_AUTO_RELOAD'] = True

# Secret key signs the login session cookie. Set SECRET_KEY in the environment
# for anything beyond local use; the dev fallback keeps logins working locally.
app.secret_key = os.environ.get('SECRET_KEY') or 'learntube-dev-secret-change-me'

auth.init_db()
app.teardown_appcontext(auth.close_db)


@app.context_processor
def inject_current_user():
    """Make the logged-in user available to every template."""
    return {'current_user': auth.current_user()}


def _record_history(kind, ref_id, title):
    """Save an opened playlist/video to the signed-in user's history (no-op if guest)."""
    user = auth.current_user()
    if user is not None:
        try:
            auth.add_history(user['id'], kind, ref_id, title)
        except Exception as exc:  # history is best-effort, never break the page
            print(f"history write failed: {exc}")


def _is_quota_error(exc):
    """True when a failure is really an AI provider rate-limit / quota, not a bug."""
    s = str(exc).lower()
    return ('429' in s or 'resource_exhausted' in s or 'quota' in s
            or 'rate limit' in s or 'rate-limit' in s)


_QUOTA_MSG = ("Today's free AI quota is used up (the Gemini free tier allows only "
              "a handful of generations per day, and translating a non-English "
              "lecture uses several). It resets in a few hours — try again later, "
              "or add a paid/Groq API key.")


# Where generated artifacts (notes / flashcards / transcripts) are cached.
GENERATED_DIR = os.path.join('data', 'generated')

# Video and sample IDs flow into filesystem paths and Chroma filters, so allow
# only a safe charset — no dots, slashes or backslashes — to stop a crafted ID
# from escaping GENERATED_DIR via path traversal.
_SAFE_ID_RE = re.compile(r"^[A-Za-z0-9_-]{1,64}$")


def _is_safe_id(value):
    return bool(value) and bool(_SAFE_ID_RE.match(str(value)))


def ensure_video_indexed(video_id, notes_json):
    """Make sure Chroma holds the current chunks for this video.

    Re-indexes when nothing is stored yet, OR when the stored chunk count no
    longer matches what the chunker now produces — which is how videos indexed
    by the earlier buggy chunker heal themselves the next time they're viewed.
    """
    from rag.embedding.chunker import create_rag_chunks
    from rag.embedding.embedder import create_embeddings
    from rag.vector_store import index_video_chunks, check_chroma

    rag_chunks = create_rag_chunks(notes_json, note_id=video_id)
    if not rag_chunks:
        return

    status = check_chroma(video_id=video_id)
    if (
        status.get('ready_for_retrieval')
        and status.get('video_chunks') == len(rag_chunks)
    ):
        return  # already up to date — nothing to re-embed

    texts = [chunk['text'] for chunk in rag_chunks]
    embeddings = create_embeddings(texts)
    index_video_chunks(video_id=video_id, chunks=rag_chunks, embeddings=embeddings)


# 1. Home Route
@app.route('/')
def home():
    # Read the sample notebook title dynamically from json_txt.json
    sample_title = "Sample Notebook"
    try:
        with open('json_txt.json', 'r', encoding='utf-8') as f:
            sample_data = json.load(f)
        sample_title = sample_data.get('title', sample_title)
    except Exception:
        pass
    return render_template(
        'index.html', notes=[], sample_title=sample_title,
        history=auth.list_history(auth.current_user()['id']) if auth.current_user() else []
    )


# ---- Accounts --------------------------------------------------------------

@app.route('/signup', methods=['GET', 'POST'])
def signup():
    if request.method == 'POST':
        user, err = auth.create_user(request.form.get('email'), request.form.get('password'))
        if err:
            return render_template('auth.html', mode='signup', error=err,
                                   email=request.form.get('email', ''))
        auth.login_session(user)
        return redirect(url_for('home'))
    return render_template('auth.html', mode='signup')


@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        user, err = auth.verify_user(request.form.get('email'), request.form.get('password'))
        if err:
            return render_template('auth.html', mode='login', error=err,
                                   email=request.form.get('email', ''),
                                   next=request.form.get('next', ''))
        auth.login_session(user)
        nxt = request.args.get('next') or request.form.get('next')
        return redirect(nxt or url_for('home'))
    return render_template('auth.html', mode='login', next=request.args.get('next', ''))


@app.route('/logout')
def logout():
    auth.logout_session()
    return redirect(url_for('home'))


def _load_saved_transcript(video_id):
    """Return the plain text of a transcript we already extracted for this video.

    The playlist step (cie/playlist_transcripts.py) saves a timestamped
    transcript per video under data/transcripts/<playlist_id>/<video_id>.json.
    Reusing it means opening a lecture doesn't re-hit YouTube.
    """
    import glob
    candidates = glob.glob(os.path.join('data', 'transcripts', '*', f'{video_id}.json'))
    candidates += glob.glob(os.path.join('data', 'transcripts', f'{video_id}.json'))
    candidates += [os.path.join(GENERATED_DIR, f'{video_id}_transcript.json')]
    for path in candidates:
        if not os.path.isfile(path):
            continue
        try:
            with open(path, 'r', encoding='utf-8') as f:
                data = json.load(f)
        except (OSError, json.JSONDecodeError):
            continue
        segments = data.get('segments') or []
        text = ' '.join(str(s.get('text', '')) for s in segments).strip()
        if text:
            print(f"Reusing extracted transcript for {video_id} ({len(segments)} segments).")
            return text
    return None


class StudyPackError(Exception):
    """A user-facing reason a study pack could not be built (not a bug)."""


def build_study_pack(youtube_url):
    """Build (or load from cache) the full study pack for one video.

    Returns (json_data, video_id, from_cache). json_data has flashcards + summary
    merged in. Raises ValueError for a bad URL, StudyPackError for a user-facing
    problem (not educational / unusable transcript).
    """
    from pipeline.get_transcript import get_transcript, get_transcript_segments, get_video_id
    video_id = get_video_id(youtube_url)

    notes_path = os.path.join(GENERATED_DIR, f'{video_id}_notes.json')
    flashcards_path = os.path.join(GENERATED_DIR, f'{video_id}_flashcards.json')

    # ---- cache hit ----
    if os.path.isfile(notes_path):
        with open(notes_path, 'r', encoding='utf-8') as f:
            json_data = json.load(f)
        if os.path.isfile(flashcards_path):
            with open(flashcards_path, 'r', encoding='utf-8') as f:
                fc = json.load(f)
            if fc and 'flashcards' in fc:
                json_data['flashcards'] = fc['flashcards']
        quiz_path = os.path.join(GENERATED_DIR, f'{video_id}_quiz.json')
        if os.path.isfile(quiz_path):
            with open(quiz_path, 'r', encoding='utf-8') as f:
                qd = json.load(f)
            if qd.get('quiz'):
                json_data['quiz'] = qd['quiz']
        try:
            ensure_video_indexed(video_id, json_data)
        except Exception as e:
            print(f"RAG cache check failed: {e}")
        return json_data, video_id, True

    # ---- full pipeline ----
    os.makedirs(GENERATED_DIR, exist_ok=True)
    # Prefer a transcript already extracted for this video. Otherwise fetch the
    # TIMESTAMPED segments once and save them, so the quiz can anchor each
    # question to the video timeline for ANY video — not just playlist ones.
    transcript = _load_saved_transcript(video_id)
    if not transcript:
        try:
            segments = get_transcript_segments(youtube_url)
        except Exception as exc:
            print(f"timestamped transcript fetch failed: {exc}")
            segments = []
        if segments:
            with open(os.path.join(GENERATED_DIR, f'{video_id}_transcript.json'), 'w', encoding='utf-8') as sf:
                json.dump({'video_id': video_id, 'segments': segments}, sf, ensure_ascii=False)
            transcript = ' '.join(s.get('text', '') for s in segments).strip()
        if not transcript:
            transcript = get_transcript(youtube_url)
    with open(os.path.join(GENERATED_DIR, f'{video_id}_transcript.txt'), 'w', encoding='utf-8') as tf:
        tf.write(transcript)

    from pipeline.classify_content import is_study_content
    if not is_study_content(transcript):
        raise StudyPackError("This doesn't appear to be an educational video. "
                             "LearnTube only works with lectures and tutorials.")

    from langdetect import detect
    language = detect(transcript)
    from pipeline.clean_transcript import clean_transcript
    cleaned = clean_transcript(transcript)
    from pipeline.chunking import chunk_text
    chunks = chunk_text(cleaned)

    if language == "en":
        translated_chunks = chunks
    else:
        from pipeline.translate import translate_chunks
        translated_chunks = translate_chunks(chunks)

    from summary import summarize_chunks, final_summary
    summary_sections = summarize_chunks(translated_chunks)
    plain_summary = (final_summary("\n\n".join(s for s in summary_sections if s))
                     if summary_sections else "")

    from detailed_notes import detail_notes_chunks, final_detailed_notes
    final_notes = final_detailed_notes(detail_notes_chunks(translated_chunks))
    from detailed_notes_json import detailed_notes_json
    json_data = detailed_notes_json(final_notes)
    if not json_data:
        raise StudyPackError("Couldn't structure notes for this video — the "
                             "transcript may be too short or unclear.")

    if plain_summary:
        json_data['summary'] = plain_summary
    json_data['video_id'] = video_id

    from flashcard import generate_flashcards
    flashcards_data = generate_flashcards(json_data)

    try:
        ensure_video_indexed(video_id, json_data)
    except Exception as e:
        print(f"RAG indexing failed: {e}")

    with open(notes_path, 'w', encoding='utf-8') as f:
        json.dump(json_data, f, indent=4, ensure_ascii=False)
    if flashcards_data:
        with open(flashcards_path, 'w', encoding='utf-8') as f:
            json.dump(flashcards_data, f, indent=4, ensure_ascii=False)
    if plain_summary:
        with open(os.path.join(GENERATED_DIR, f'{video_id}_summary.txt'), 'w', encoding='utf-8') as f:
            f.write(plain_summary)
    if flashcards_data and 'flashcards' in flashcards_data:
        json_data['flashcards'] = flashcards_data['flashcards']

    # Timestamp-anchored quiz built from the transcript (wrong answers can jump
    # the student to the exact moment in the video).
    try:
        from pipeline.quiz_gen import generate_quiz
        quiz = generate_quiz(video_id, json_data.get('title'))
        if quiz:
            with open(os.path.join(GENERATED_DIR, f'{video_id}_quiz.json'), 'w', encoding='utf-8') as f:
                json.dump({'quiz': quiz}, f, indent=2, ensure_ascii=False)
            json_data['quiz'] = quiz
    except Exception as e:
        print(f"Quiz generation failed: {e}")

    return json_data, video_id, False


# 2. Processing Route — full pipeline
@app.route('/process', methods=['POST'])
def process_video():

    youtube_url = request.form.get('youtube_url', '').strip()

    # ---- Handle sample notebook shortcut ----
    if not youtube_url or youtube_url == '__sample__':
        try:
            with open('json_txt.json', 'r', encoding='utf-8') as f:
                json_data = json.load(f)
        except (OSError, json.JSONDecodeError) as e:
            print(f"Could not load sample notebook: {e}")
            return render_template(
                'index.html',
                notes=[],
                error="The sample notebook is unavailable right now. Please try a YouTube URL instead."
            )

        # Derive a stable, filesystem-safe video ID from the JSON content.
        # Use a stored video_id if present and safe, otherwise slugify the title.
        sample_id = json_data.get('video_id')
        if not _is_safe_id(sample_id):
            title = json_data.get('title', 'sample-notebook')
            slug = re.sub(r'[^a-z0-9]+', '-', title.lower()).strip('-')[:40] or 'notebook'
            sample_id = 'sample-' + slug

        # Ensure the sample content is indexed in RAG so the chat works
        try:
            ensure_video_indexed(sample_id, json_data)
        except Exception as e:
            print(f"Sample RAG indexing failed: {e}")  # chat will say "no content found"

        return render_template(
            'notes.html',
            notes_json=json_data,
            chat_video_id=sample_id,
        )

    # ---- Full pipeline for real YouTube URLs (SAME pipeline as the playlist
    # flow — both go through build_study_pack). ----
    try:
        json_data, video_id, _cached = build_study_pack(youtube_url)
    except ValueError as e:
        return render_template('index.html', notes=[], error=f"Invalid YouTube URL: {e}")
    except StudyPackError as e:
        return render_template('index.html', notes=[], error=str(e))
    except Exception as e:
        if _is_quota_error(e):
            return render_template('index.html', notes=[], error=_QUOTA_MSG)
        traceback.print_exc()
        return render_template(
            'index.html', notes=[],
            error=f"Something went wrong while processing the video. Please try again. ({type(e).__name__})"
        )

    _record_history('video', video_id, json_data.get('title'))
    return render_template('notes.html', notes_json=json_data, chat_video_id=video_id)


# Video-scoped RAG chat endpoint. The video ID in the URL also scopes Chroma
# retrieval, so a question only searches chunks indexed for that video.
@app.route('/api/videos/<video_id>/chat', methods=['POST'])
def chat_with_video(video_id):
    if not _is_safe_id(video_id):
        return jsonify({'error': 'Invalid video id.'}), 400

    payload = request.get_json(silent=True) or {}
    question = payload.get('question', '')

    if not isinstance(question, str) or not question.strip():
        return jsonify({'error': 'Please provide a question.'}), 400

    try:
        result = answer_video_question(
            question=question,
            video_id=video_id,
        )
        return jsonify(result)
    except ValueError as exc:
        return jsonify({'error': str(exc)}), 400
    except RuntimeError as exc:
        return jsonify({'error': str(exc)}), 503
    except Exception:
        app.logger.exception('Video chat request failed')
        return jsonify({'error': 'Server error: Unable to process chat request at this time.'}), 500


# ---- Playlist / knowledge-graph routes ------------------------------------

def _playlist_id_from_url(url):
    """Pull the playlist id (?list=...) out of a YouTube URL, or accept a bare id."""
    if not url:
        return None
    match = re.search(r'[?&]list=([A-Za-z0-9_-]+)', url)
    if match:
        return match.group(1)
    candidate = url.strip()
    return candidate if _is_safe_id(candidate) else None


@app.route('/course/<playlist_id>')
def course_page(playlist_id):
    """Render the 3D knowledge-graph course screen for a built playlist."""
    if not _is_safe_id(playlist_id):
        return 'Invalid playlist id.', 400
    graph_path = os.path.join(GENERATED_DIR, f'{playlist_id}_graph.json')
    if not os.path.isfile(graph_path):
        return render_template(
            'index.html', notes=[],
            error="That course map hasn't been built yet. Build its knowledge graph first."
        )
    with open(graph_path, 'r', encoding='utf-8') as f:
        graph = json.load(f)
    _record_history('playlist', playlist_id, graph.get('title'))
    lectures = load_playlist_lectures(playlist_id)
    return render_template('course.html', playlist_id=playlist_id, graph=graph, lectures=lectures)


@app.route('/api/playlists/<playlist_id>/graph')
def playlist_graph(playlist_id):
    """Serve the saved knowledge-graph JSON for a playlist."""
    if not _is_safe_id(playlist_id):
        return jsonify({'error': 'Invalid playlist id.'}), 400
    graph_path = os.path.join(GENERATED_DIR, f'{playlist_id}_graph.json')
    if not os.path.isfile(graph_path):
        return jsonify({'error': 'Graph not found for this playlist.'}), 404
    return send_file(graph_path, mimetype='application/json')


@app.route('/playlist', methods=['POST'])
def open_playlist():
    """Take a playlist link and open its course map if the graph is built."""
    url = request.form.get('playlist_url', '').strip()
    playlist_id = _playlist_id_from_url(url)
    if not playlist_id or not _is_safe_id(playlist_id):
        return render_template('index.html', notes=[], error="That doesn't look like a YouTube playlist link.")
    graph_path = os.path.join(GENERATED_DIR, f'{playlist_id}_graph.json')
    if os.path.isfile(graph_path):
        return redirect(url_for('course_page', playlist_id=playlist_id))
    # Not built yet — kick off the build (extract transcripts + knowledge graph).
    return redirect(url_for('build_playlist_page', playlist_id=playlist_id))


@app.route('/build/<playlist_id>')
def build_playlist_page(playlist_id):
    """Show the 'building your course' screen for a not-yet-processed playlist."""
    if not _is_safe_id(playlist_id):
        return 'Invalid playlist id.', 400
    graph_path = os.path.join(GENERATED_DIR, f'{playlist_id}_graph.json')
    if os.path.isfile(graph_path):
        return redirect(url_for('course_page', playlist_id=playlist_id))
    return render_template('build_playlist.html', playlist_id=playlist_id)


def _playlist_looks_educational(playlist_id, max_check=3):
    """Sample a few of the playlist's transcripts and ask the classifier whether
    this is study content. Fail-open: if we can't read/classify any, allow it."""
    import glob as _glob
    from pipeline.classify_content import is_study_content
    folder = os.path.join('data', 'transcripts', playlist_id)
    paths = [p for p in _glob.glob(os.path.join(folder, '*.json'))
             if not p.endswith('manifest.json')]
    checked = 0
    for path in paths:
        if checked >= max_check:
            break
        try:
            with open(path, 'r', encoding='utf-8') as fh:
                data = json.load(fh)
        except (OSError, json.JSONDecodeError):
            continue
        segs = data.get('segments') or []
        text = ' '.join(str(s.get('text', '')) for s in segs[:250]).strip()
        if not text:
            continue
        checked += 1
        try:
            if is_study_content(text):
                return True
        except Exception:
            return True  # classifier/LLM trouble → don't block the user
    return checked == 0  # couldn't judge any → allow; judged some, none study → block


@app.route('/api/playlists/<playlist_id>/build', methods=['POST'])
def build_playlist_api(playlist_id):
    """Extract the playlist's transcripts and build its knowledge graph."""
    if not _is_safe_id(playlist_id):
        return jsonify({'error': 'Invalid playlist id.'}), 400
    graph_path = os.path.join(GENERATED_DIR, f'{playlist_id}_graph.json')
    if os.path.isfile(graph_path):
        return jsonify({'ok': True, 'playlist_id': playlist_id})
    url = f'https://www.youtube.com/playlist?list={playlist_id}'
    try:
        from cie.playlist_transcripts import process_playlist
        actual_id = process_playlist(url) or playlist_id
        if not _playlist_looks_educational(actual_id):
            return jsonify({'error': "This playlist doesn't look like educational content. "
                                     "LearnTube only builds courses from lectures, tutorials "
                                     "and study material."}), 422
        from pipeline.concept_graph import build_graph
        build_graph(playlist_id=actual_id)
        return jsonify({'ok': True, 'playlist_id': actual_id})
    except Exception as e:
        if _is_quota_error(e):
            app.logger.warning('AI quota exhausted during playlist build')
            return jsonify({'error': _QUOTA_MSG}), 429
        app.logger.exception('Playlist build failed')
        return jsonify({'error': f'Could not build this playlist ({type(e).__name__}).'}), 500


@app.route('/video/<video_id>')
def view_video(video_id):
    """Re-open a already-processed video's notes (used by history / continue)."""
    if not _is_safe_id(video_id):
        return 'Invalid video id.', 400
    notes_path = os.path.join(GENERATED_DIR, f'{video_id}_notes.json')
    if not os.path.isfile(notes_path):
        return render_template(
            'index.html', notes=[], sample_title='Sample Notebook',
            history=auth.list_history(auth.current_user()['id']) if auth.current_user() else [],
            error="That video hasn't been processed yet. Paste its link to generate notes."
        )
    with open(notes_path, 'r', encoding='utf-8') as f:
        json_data = json.load(f)
    flashcards_path = os.path.join(GENERATED_DIR, f'{video_id}_flashcards.json')
    if os.path.isfile(flashcards_path):
        with open(flashcards_path, 'r', encoding='utf-8') as f:
            fc = json.load(f)
        if fc and 'flashcards' in fc:
            json_data['flashcards'] = fc['flashcards']
    quiz_path = os.path.join(GENERATED_DIR, f'{video_id}_quiz.json')
    if os.path.isfile(quiz_path):
        with open(quiz_path, 'r', encoding='utf-8') as f:
            qd = json.load(f)
        if qd.get('quiz'):
            json_data['quiz'] = qd['quiz']
    try:
        ensure_video_indexed(video_id, json_data)
    except Exception as e:
        print(f"RAG index (view_video) failed: {e}")
    _record_history('video', video_id, json_data.get('title'))
    return render_template('notes.html', notes_json=json_data, chat_video_id=video_id)


def _fmt_time(sec):
    sec = max(0, int(sec or 0))
    return f"{sec // 60}:{sec % 60:02d}"


def compute_study_plan(graph):
    """Turn the knowledge graph into a prioritised, prerequisite-ordered plan.

    - reading order respects prerequisites (a concept never appears before one
      it depends on), then ranks by importance;
    - importance = how many later concepts depend on it (its "reach"), so the
      foundations that unlock the most come first;
    - concepts are banded into Start here / Core / Advanced by prerequisite depth.
    """
    import networkx as nx

    nodes = {n['id']: n for n in graph.get('nodes', [])}
    G = nx.DiGraph()
    G.add_nodes_from(nodes.keys())
    for e in graph.get('edges', []):
        if e['from'] in nodes and e['to'] in nodes:
            G.add_edge(e['from'], e['to'])

    reach = {nid: len(nx.descendants(G, nid)) for nid in G.nodes}
    depth = {}
    for nid in nx.topological_sort(G):
        preds = list(G.predecessors(nid))
        depth[nid] = 0 if not preds else 1 + max(depth[p] for p in preds)

    max_reach = max(reach.values()) if reach else 0
    pos = {nid: ((nodes[nid].get('occurrences') or [{}])[0].get('position') or 0) for nid in nodes}
    # Reading order: prerequisites first (depth), then course order, then importance.
    ordered = sorted(nodes.keys(), key=lambda nid: (depth[nid], pos[nid], -reach[nid], nodes[nid]['label']))

    bands = {
        'foundations': {'key': 'foundations', 'name': 'Backbone · unlocks the most', 'items': []},
        'core':        {'key': 'core',        'name': 'Core · build on these',       'items': []},
        'advanced':    {'key': 'advanced',    'name': 'Details & extras',             'items': []},
    }
    for rank, nid in enumerate(ordered, 1):
        n = nodes[nid]
        occ = (n.get('occurrences') or [{}])[0]
        importance = round(reach[nid] / max_reach * 100) if max_reach else 0
        item = {
            'rank': rank,
            'label': n['label'],
            'definition': n.get('definition', ''),
            'unlocks': reach[nid],
            'importance': importance,
            'depth': depth[nid],
            'video_id': occ.get('video_id'),
            'start': occ.get('start', 0),
            'start_fmt': _fmt_time(occ.get('start', 0)),
            'position': occ.get('position'),
            'prereqs': [nodes[p]['label'] for p in G.predecessors(nid) if p in nodes],
        }
        # Segregate by importance (how much the concept unlocks), not raw depth,
        # so the few backbone concepts stand out from the many leaf details.
        if importance >= 25:
            key = 'foundations'
        elif importance >= 5:
            key = 'core'
        else:
            key = 'advanced'
        bands[key]['items'].append(item)

    band_list = [b for b in (bands['foundations'], bands['core'], bands['advanced']) if b['items']]
    return {'title': graph.get('title', 'Course'), 'bands': band_list, 'total': len(ordered)}


def load_playlist_lectures(playlist_id):
    """List the playlist's videos in order (position, title, video_id, cached?).

    Reads the manifest the playlist step saved at
    data/transcripts/<playlist_id>/manifest.json so a student can open any
    lecture's full study page by video, not just by concept.
    """
    path = os.path.join('data', 'transcripts', playlist_id, 'manifest.json')
    if not os.path.isfile(path):
        return []
    try:
        with open(path, 'r', encoding='utf-8') as f:
            manifest = json.load(f)
    except (OSError, json.JSONDecodeError):
        return []
    lectures = []
    for v in manifest.get('videos', []):
        vid = v.get('video_id')
        if not vid or not _is_safe_id(vid):
            continue
        lectures.append({
            'position': v.get('position'),
            'video_id': vid,
            'title': v.get('title') or vid,
            'cached': os.path.isfile(os.path.join(GENERATED_DIR, f'{vid}_notes.json')),
        })
    lectures.sort(key=lambda x: x['position'] or 0)
    return lectures


@app.route('/plan/<playlist_id>')
def study_plan(playlist_id):
    """A prioritised study-plan dashboard built from the knowledge graph."""
    if not _is_safe_id(playlist_id):
        return 'Invalid playlist id.', 400
    graph_path = os.path.join(GENERATED_DIR, f'{playlist_id}_graph.json')
    if not os.path.isfile(graph_path):
        return render_template('index.html', notes=[],
                               error="That course map hasn't been built yet.")
    with open(graph_path, 'r', encoding='utf-8') as f:
        graph = json.load(f)
    plan = compute_study_plan(graph)
    _record_history('playlist', playlist_id, graph.get('title'))
    return render_template('plan.html', playlist_id=playlist_id, plan=plan,
                           lectures=load_playlist_lectures(playlist_id))


@app.route('/study/<video_id>')
def study_video(video_id):
    """Open the full study page (notes/summary/quiz/chat) for a video —
    generating it on the fly the first time it's opened."""
    if not _is_safe_id(video_id):
        return 'Invalid video id.', 400
    notes_path = os.path.join(GENERATED_DIR, f'{video_id}_notes.json')
    if os.path.isfile(notes_path):
        return redirect(url_for('view_video', video_id=video_id))
    return render_template('generate.html', video_id=video_id)


@app.route('/api/videos/<video_id>/generate', methods=['POST'])
def generate_video(video_id):
    """Run the full pipeline for one video id (called by the generate page)."""
    if not _is_safe_id(video_id):
        return jsonify({'error': 'Invalid video id.'}), 400
    url = f'https://www.youtube.com/watch?v={video_id}'
    try:
        json_data, vid, _cached = build_study_pack(url)
        _record_history('video', vid, json_data.get('title'))
        return jsonify({'ok': True, 'video_id': vid})
    except ValueError as e:
        return jsonify({'error': f'Invalid video: {e}'}), 400
    except StudyPackError as e:
        return jsonify({'error': str(e)}), 422
    except Exception as e:
        if _is_quota_error(e):
            app.logger.warning('AI quota exhausted during video generation')
            return jsonify({'error': _QUOTA_MSG}), 429
        app.logger.exception('Study pack generation failed')
        return jsonify({'error': 'Could not generate notes for this video.'}), 500


# 5. Transcript file route — view a video's raw transcript
@app.route('/transcript/<video_id>')
def view_transcript(video_id):
    """Serve a video's saved transcript."""
    if not _is_safe_id(video_id):
        return 'Invalid video id.', 400
    transcript_path = os.path.join(GENERATED_DIR, f'{video_id}_transcript.txt')
    if not os.path.isfile(transcript_path):
        return 'No transcript available for this video yet.', 404
    return send_file(
        transcript_path,
        mimetype='text/plain; charset=utf-8',
    )


# 6. Download notes JSON
@app.route('/download/<video_id>')
def download_notes(video_id):
    """Download the generated notes as a JSON file."""
    if not _is_safe_id(video_id):
        return 'Invalid video id.', 400
    notes_path = os.path.join(GENERATED_DIR, f'{video_id}_notes.json')
    if not os.path.isfile(notes_path):
        return 'Notes not found for this video.', 404

    return send_file(
        notes_path,
        mimetype='application/json',
        as_attachment=True,
        download_name=f'{video_id}_notes.json'
    )


# 3. Flashcards API (legacy global deck). The notes page now reads per-video
# flashcards from the injected lecture data; this stays only as a fallback and
# must never 500 the page when the file is missing.
@app.route('/api/flashcards')
def get_flashcards():
    try:
        with open('flashcards.json', 'r', encoding='utf-8') as f:
            flashcards = json.load(f)
        return jsonify(flashcards)
    except (OSError, json.JSONDecodeError):
        return jsonify({'flashcards': []})


# 4. Dummy Notes Page Route
@app.route('/notes_page')
def notes_page():
    return "History coming soon!"


if __name__ == '__main__':
    # Debug mode exposes the interactive Werkzeug debugger (arbitrary code
    # execution) — keep it OFF unless FLASK_DEBUG is explicitly set.
    debug = os.environ.get('FLASK_DEBUG', '').lower() in ('1', 'true', 'yes', 'on')
    app.run(debug=debug, port=int(os.environ.get('PORT', 5000)))
