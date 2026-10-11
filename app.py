import os
import re
import json
import traceback
from flask import Flask, jsonify, render_template, request, send_file, redirect, url_for

from rag.chat import answer_video_question
import auth

app = Flask(__name__)

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

    # ---- Full pipeline for real YouTube URLs ----
    try:
        # Step 1: Extract video ID
        from pipeline.get_transcript import get_transcript, get_video_id
        video_id = get_video_id(youtube_url)

        # ---- Cache Check: If already processed, return immediately ----
        notes_path = os.path.join(GENERATED_DIR, f'{video_id}_notes.json')
        flashcards_path = os.path.join(GENERATED_DIR, f'{video_id}_flashcards.json')
        if os.path.isfile(notes_path):
            print(f"Cache hit! Loading existing notes for {video_id}...")
            with open(notes_path, 'r', encoding='utf-8') as f:
                json_data = json.load(f)

            if os.path.isfile(flashcards_path):
                with open(flashcards_path, 'r', encoding='utf-8') as f:
                    flashcards_data = json.load(f)
                if flashcards_data and 'flashcards' in flashcards_data:
                    json_data['flashcards'] = flashcards_data['flashcards']

            # Ensure RAG database has this video's chunks, and heal any index
            # built by the earlier buggy chunker (chunk count will differ).
            try:
                ensure_video_indexed(video_id, json_data)
            except Exception as e:
                print(f"RAG Cache Check Failed: {e}")

            _record_history('video', video_id, json_data.get('title'))
            return render_template(
                'notes.html',
                notes_json=json_data,
                chat_video_id=video_id,
            )
        # -------------------------------------------------------------

        # Step 2: Fetch transcript
        transcript = get_transcript(youtube_url)

        # Step 2b: Save raw transcript to a per-video text file. Scoping it by
        # video_id stops concurrent requests from clobbering a shared file.
        os.makedirs(GENERATED_DIR, exist_ok=True)
        transcript_path = os.path.join(GENERATED_DIR, f'{video_id}_transcript.txt')
        with open(transcript_path, 'w', encoding='utf-8') as tf:
            tf.write(transcript)

        # Step 3: Check if it's educational content
        from pipeline.classify_content import is_study_content
        if not is_study_content(transcript):
            return render_template(
                'index.html',
                notes=[],
                error="This doesn't appear to be an educational video. LearnTube only works with lectures, tutorials, and educational content."
            )

        # Step 4: Detect language to ensure it's actually English
        from langdetect import detect
        language = detect(transcript)

        # Step 5: Clean transcript
        from pipeline.clean_transcript import clean_transcript
        cleaned = clean_transcript(transcript)

        # Step 6: Chunk the transcript
        from pipeline.chunking import chunk_text
        chunks = chunk_text(cleaned)

        # Step 7: Fallback LLM Translation
        # Most of the time, get_transcript already got us English from YouTube.
        # But if YT translation was disabled, this kicks in as a safety net.
        if language == "en":
            translated_chunks = chunks
        else:
            print(f"YouTube translation failed (detected {language}). Falling back to LLM translation...")
            from pipeline.translate import translate_chunks
            translated_chunks = translate_chunks(chunks)

        # Step 7b: Generate a plain-text summary from the (translated) transcript.
        # Kept as its own pipeline so the notes page can show a quick-read
        # overview and the RAG index can embed it alongside the notes.
        from summary import summarize_chunks, final_summary
        summary_sections = summarize_chunks(translated_chunks)
        plain_summary = (
            final_summary("\n\n".join(s for s in summary_sections if s))
            if summary_sections else ""
        )

        # Step 8: Generate detailed notes
        from detailed_notes import detail_notes_chunks, final_detailed_notes
        detailed_notes_list = detail_notes_chunks(translated_chunks)
        final_notes = final_detailed_notes(detailed_notes_list)

        # Step 9: Convert to structured JSON
        from detailed_notes_json import detailed_notes_json
        json_data = detailed_notes_json(final_notes)

        if not json_data:
            return render_template(
                'index.html',
                notes=[],
                error="Failed to generate structured notes. The video may be too short or the transcript may be unclear. Please try another video."
            )

        # Attach the generated summary + video id so they show in the UI and are
        # included when the notes are indexed for RAG below.
        if plain_summary:
            json_data['summary'] = plain_summary
        json_data['video_id'] = video_id

        # Step 10: Generate flashcards
        from flashcard import generate_flashcards
        flashcards_data = generate_flashcards(json_data)

        # Step 11: Index this video's chunks for RAG chat.
        try:
            ensure_video_indexed(video_id, json_data)
        except Exception as e:
            print(f"RAG indexing failed: {e}")

        # Step 12: Save outputs (for caching / reuse)
        os.makedirs(GENERATED_DIR, exist_ok=True)
        with open(os.path.join(GENERATED_DIR, f'{video_id}_notes.json'), 'w', encoding='utf-8') as f:
            json.dump(json_data, f, indent=4, ensure_ascii=False)

        if flashcards_data:
            with open(os.path.join(GENERATED_DIR, f'{video_id}_flashcards.json'), 'w', encoding='utf-8') as f:
                json.dump(flashcards_data, f, indent=4, ensure_ascii=False)

        if plain_summary:
            with open(os.path.join(GENERATED_DIR, f'{video_id}_summary.txt'), 'w', encoding='utf-8') as f:
                f.write(plain_summary)

        # Merge flashcards into the notes JSON for the frontend
        if flashcards_data and 'flashcards' in flashcards_data:
            json_data['flashcards'] = flashcards_data['flashcards']

        _record_history('video', video_id, json_data.get('title'))
        return render_template(
            'notes.html',
            notes_json=json_data,
            chat_video_id=video_id,
        )

    except ValueError as e:
        return render_template(
            'index.html',
            notes=[],
            error=f"Invalid YouTube URL: {e}"
        )
    except Exception as e:
        traceback.print_exc()
        return render_template(
            'index.html',
            notes=[],
            error=f"Something went wrong while processing the video. Please try again. ({type(e).__name__})"
        )


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
    return render_template('course.html', playlist_id=playlist_id, graph=graph)


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
    return render_template(
        'index.html', notes=[],
        error="This playlist hasn't been processed yet. Build its knowledge graph, then open the course."
    )


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
    try:
        ensure_video_indexed(video_id, json_data)
    except Exception as e:
        print(f"RAG index (view_video) failed: {e}")
    _record_history('video', video_id, json_data.get('title'))
    return render_template('notes.html', notes_json=json_data, chat_video_id=video_id)


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
