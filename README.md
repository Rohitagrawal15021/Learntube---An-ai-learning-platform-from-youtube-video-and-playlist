# LearnTube AI — Distributed Video-to-Knowledge & Graph-RAG Platform 🎓🚀

[![Python 3.10+](https://img.shields.io/badge/Python-3.10%2B-blue.svg)](https://www.python.org/)
[![Framework: Flask](https://img.shields.io/badge/Backend-Flask-black.svg)](https://flask.palletsprojects.com/)
[![LLMs: Gemini & Groq](https://img.shields.io/badge/LLM_Routing-Gemini_Flash_%7C_Groq_Llama--3.3--70B-orange.svg)](#)
[![Vector DB: ChromaDB](https://img.shields.io/badge/Vector_Store-ChromaDB-green.svg)](#)

**LearnTube AI** is an end-to-end AI learning platform that transforms raw YouTube lecture videos and multi-video course playlists (50+ lectures) into a structured, interactive educational environment: **schema-validated textbook notes**, **spaced-repetition flashcard decks**, **prerequisite concept knowledge graphs (DAGs)**, and a **timestamp-grounded RAG AI tutor**.

---

## ⚡ Key Engineering Highlights

* **Cost-Aware Gatekeeper Pipeline:** Implements an automated pre-ingestion classifier (`classify_content.py`) using **Gemini Flash** to validate educational intent and reject non-instructional videos (vlogs, gaming, music) *before* triggering heavy multi-pass synthesis, substantially reducing wasted token spend.
* **Cross-Lecture Prerequisite Knowledge Graph (DAG):** Extracts 5–12 core concepts per lecture anchored to 30-second timestamp blocks, deduplicates recurring topics across multi-video playlists via cosine similarity (`paraphrase-multilingual-MiniLM-L12-v2`), infers prerequisite dependencies (*"Learn Concept A before Concept B"*), and resolves circular dependencies into a clean **Directed Acyclic Graph (DAG)**.
* **Latency- & Cost-Optimized Multi-Model Routing:** Routes high-context batch tasks (transcript cleaning, multilingual chunk translation, and JSON textbook synthesis) to **Google Gemini Flash**, while routing real-time conversational RAG queries to **Groq Cloud (`llama-3.3-70b-versatile`)** for sub-second student tutoring.
* **Multilingual Auto-Fallback Caption Engine (CIE):** Prioritizes manual English transcripts and automatically falls back to native/auto-generated captions (Hindi, Spanish, French, etc.) with safe Unicode normalization and chunk-level dynamic translation.
* **Strict Schema Validation:** Enforces deterministic JSON schemas (`detailed_notes_json.py`, `json_summary.py`) to guarantee predictable programmatic rendering and standalone offline HTML generation.

---

## 🏗️ System Architecture & Pipeline Flow

Rather than generating generic text summaries, LearnTube AI processes raw lecture streams through a 5-stage ingestion, structuring, and retrieval pipeline:

```text
1. INGESTION               2. REFINEMENT              3. KNOWLEDGE STRUCTURING           4. RETRIEVAL & TUTORING
┌──────────────────┐       ┌──────────────────┐       ┌────────────────────────────┐      ┌─────────────────────────┐
│ YouTube URL      │       │ Content Filter   │       │ Deep Textbook Notes        │      │ Multilingual Embeddings │
│ (Single/Playlist)│       │ (Is it study?)   │       │ (Formula, Code & Sections) │      │ (Sentence Transformers) │
└────────┬─────────┘       └────────┬─────────┘       └─────────────┬──────────────┘      └────────────┬────────────┘
         │                          │                               │                                  │
         ▼                          ▼                               ▼                                  ▼
┌──────────────────┐       ┌──────────────────┐       ┌────────────────────────────┐      ┌─────────────────────────┐
│ Caption Engine   │──────►│ Text Cleaner &   │──────►│ Structured JSON Notes &    │─────►│ ChromaDB Vector Store & │
│ (Auto-Fallback & │       │ Smart Translator │       │ Active-Recall Flashcards   │      │ 24/7 Groq AI Tutor Chat │
│  Timestamps)     │       │ (Chunk-level)    │       └─────────────┬──────────────┘      └─────────────────────────┘
└──────────────────┘       └──────────────────┘                     │
                                                                    ▼
                                                      ┌────────────────────────────┐
                                                      │ Knowledge Concept Graph    │
                                                      │ (DAG: Learn A before B)    │
                                                      └────────────────────────────┘
```

### Stage-by-Stage Pipeline Breakdown

1. **🎧 Stage 1 — Caption Intelligence Engine (`cie/`):**
   * Accepts single YouTube video URLs or full course playlists (50+ videos) with local metadata caching and manifest tracking.
   * Automatically resolves transcript availability (Manual English $\rightarrow$ Auto English $\rightarrow$ Native Language Fallback) and anchors every segment to exact `start` and `duration` timestamps.
2. **🛡️ Stage 2 — Gatekeeper, Denoising & Chunking (`pipeline/`):**
   * **Educational Classifier:** Filters out non-educational streams before downstream LLM processing.
   * **Transcript Cleaner:** Strips spoken filler words, sponsor reads, and transcription artifacts.
   * **Semantic Chunking & Dynamic Translation:** Splits 2-hour lectures into coherent 500–1,000 word segments and translates non-English segments into standardized English.
3. **📖 Stage 3 — Multi-Pass Synthesis & Active Recall:**
   * Synthesizes transcripts into textbook-grade sections preserving mathematical formulas, code blocks, definitions, and common pitfalls.
   * Outputs strict JSON schemas, standalone responsive HTML pages (`notes.html`), and 15-card active-recall flashcard decks.
4. **🕸️ Stage 4 — Curriculum Architect (`concept_graph.py`):**
   * Computes vector cosine similarity across lectures to merge duplicate concepts across a playlist into unified nodes.
   * Evaluates foundational prerequisites (e.g., *Derivatives $\rightarrow$ Gradient Descent*) and eliminates cycles to construct a valid **Directed Acyclic Graph (DAG)**.
5. **🤖 Stage 5 — Timestamp-Grounded RAG Tutor (`rag/`):**
   * Encodes structured notes and transcript chunks into dense vectors using HuggingFace `paraphrase-multilingual-MiniLM-L12-v2` and indexes them in **ChromaDB**.
   * Retrieves top-$K$ relevant segments during student queries and prompts **Groq (`llama-3.3-70b-versatile`)** to return low-latency answers cited with clickable video timestamps.

---

## 📂 Repository Structure

```text
learntube-ai/
├── app.py                      # Flask web application entry point & route controllers
├── auth.py                     # SQLite user authentication & Werkzeug password hashing
├── config.py                   # API client configuration (Google Gemini, Groq Cloud)
├── detailed_notes.py           # Multi-stage textbook notes synthesis engine
├── detailed_notes_json.py      # Deterministic JSON schema converter for study notes
├── flashcard.py                # Active-recall flashcard deck generator
├── html_generator.py           # Standalone responsive HTML notes exporter
├── summary.py                  # Chunk-level and video-level summarization engine
├── json_summary.py             # Structured JSON summary serializer
├── pipeline_test.py            # CLI end-to-end integration pipeline runner
│
├── cie/                        # Caption Intelligence Engine
│   ├── timestamp_transcript.py # Timestamped transcript extractor with language fallback
│   └── playlist_transcripts.py # Playlist crawler, metadata caching & manifest manager
│
├── pipeline/                   # Core Processing & Graph Pipeline
│   ├── get_transcript.py       # Base transcript retrieval & language resolution
│   ├── classify_content.py     # Pre-ingestion educational content gatekeeper
│   ├── clean_transcript.py     # Spoken noise & filler-word denoiser
│   ├── chunking.py             # Context-preserving semantic text chunker
│   ├── translate.py            # Chunk-level multilingual translator
│   └── concept_graph.py        # Cross-lecture concept deduplication & DAG builder
│
├── rag/                        # Retrieval-Augmented Generation Engine
│   ├── embedding/
│   │   ├── chunker.py          # RAG document chunking processor
│   │   └── embedder.py         # Sentence-Transformers multilingual embedding wrapper
│   ├── vector_store.py         # ChromaDB client, persistent indexing & similarity search
│   ├── retrieval.py            # Context ranking & timestamp retrieval engine
│   └── chat.py                 # Groq Llama-3.3-70B conversational tutor
│
├── templates/                  # Jinja2 frontend templates (Auth, Dashboard, Notes, Course)
└── static/                     # CSS styling & interactive frontend scripts
```

---

## ⚡ Quickstart & Installation

### 1. Clone the Repository
```bash
git clone [https://github.com/Rohitagrawal15021/youtube_summarizer.git](https://github.com/Rohitagrawal15021/youtube_summarizer.git)
cd youtube_summarizer
```

### 2. Create and Activate a Virtual Environment

**Windows (PowerShell / CMD):**
```powershell
python -m venv venv
.\venv\Scripts\activate
```

**Linux / macOS:**
```bash
python3 -m venv venv
source venv/bin/activate
```

### 3. Install Dependencies
```bash
pip install -r requirements.txt
```

### 4. Configure Environment Variables
Create a `.env` file in the project root directory:
```env
GEMINI_API_KEY=your_gemini_api_key_here
GROQ_API_KEY=your_groq_api_key_here
SECRET_KEY=your_flask_secret_key_here
```

---

## 🚀 Usage

### A. Run the End-to-End Pipeline via CLI
Test the full extraction, synthesis, DAG generation, and RAG indexing pipeline on any single video or playlist:

```bash
# Interactive mode (prompts for YouTube URL)
python pipeline_test.py

# Process a single lecture video
python pipeline_test.py "[https://www.youtube.com/watch?v=VIDEO_ID](https://www.youtube.com/watch?v=VIDEO_ID)"

# Process an entire course playlist
python pipeline_test.py "[https://www.youtube.com/playlist?list=PLAYLIST_ID](https://www.youtube.com/playlist?list=PLAYLIST_ID)"
```

### B. Launch the Web Application
```bash
python app.py
```
Open **`http://localhost:5000`** in your browser to access the course dashboard, interactive notes reader, flashcard deck, and AI tutor.

---

## 🛠️ Tech Stack

| Layer | Technologies Used |
| :--- | :--- |
| **Backend & API** | Python 3.10+, Flask, SQLite, Werkzeug Security |
| **LLM Inference** | Google Gemini API (`gemini-2.0-flash`, `gemini-2.5-flash`), Groq Cloud (`llama-3.3-70b-versatile`) |
| **Vector Search & NLP** | ChromaDB, HuggingFace `sentence-transformers` (`paraphrase-multilingual-MiniLM-L12-v2`), `langdetect` |
| **Ingestion & Parsing** | `youtube-transcript-api`, `yt-dlp` |

