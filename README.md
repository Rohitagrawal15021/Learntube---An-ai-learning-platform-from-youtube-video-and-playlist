# LearnTube AI — Intelligent Video-to-Knowledge Learning Platform 🎓🚀

[![Python Version](https://img.shields.io/badge/python-3.10%20%7C%203.11%20%7C%203.12-blue.svg)](https://www.python.org/)
[![Framework](https://img.shields.io/badge/framework-Flask-black.svg)](https://flask.palletsprojects.com/)
[![Vector DB](https://img.shields.io/badge/vectordb-ChromaDB-purple.svg)](https://www.trychroma.com/)
[![LLM Powered](https://img.shields.io/badge/AI-Gemini%20%2B%20Groq-orange.svg)](https://groq.com/)
[![License](https://img.shields.io/badge/license-MIT-green.svg)](LICENSE)

> **LearnTube AI** is an intelligent learning platform that transforms YouTube lecture videos and multi-video playlists into an interactive, easy-to-learn educational experience: comprehensive textbook-grade notes, active-recall flashcard decks, prerequisite concept knowledge graphs, and a 24/7 conversational AI study tutor grounded in video transcripts via RAG.

---

## 🌟 Key Features

- **🎯 Intelligent Caption Engine (CIE)**
  - Extracts timestamped transcript segments for single videos or full playlists.
  - Automatic language fallback: prioritizes English, seamlessly falls back to any available transcript language.
  - Safe Unicode processing for multilingual video titles and transcripts.

- **🕸️ Prerequisite Knowledge Concept Graph**
  - Identifies 5–12 core learning concepts per lecture anchored to 30-second timestamp blocks.
  - Merges duplicate/recurring concepts across lectures using multilingual vector embedding similarity.
  - Infers prerequisite learning dependencies ("learn concept A before concept B") and generates a clean Directed Acyclic Graph (DAG).

- **📝 Deep Study Notes & Schema Validation**
  - Synthesizes transcripts into textbook-grade study notes.
  - Enforces strict JSON schemas for predictable programmatic rendering.
  - Generates standalone, responsive HTML notes pages.

- **🎴 Active-Recall Flashcards**
  - Automatically generates question-answer flashcard decks from core concepts and definitions.

- **💬 Transcripts-Grounded RAG Chat Tutor**
  - Chunks notes and transcripts into semantically coherent units.
  - Indexes chunks into ChromaDB vector database with multilingual embeddings (`paraphrase-multilingual-MiniLM-L12-v2`).
  - High-speed conversational AI responses powered by Groq (`llama-3.3-70b-versatile`) with source citation links.

- **🔐 Lightweight Authentication & Web Interface**
  - Secure SQLite-backed user authentication with Werkzeug password hashing.
  - Modern web dashboard featuring courses overview, notes reader, flashcard viewer, and real-time chat widget.

---

## 🏗️ Architecture & Pipeline Flow

```text
[ YouTube Video / Playlist URL ]
               │
               ▼
┌────────────────────────────────────────┐
│     Caption Intelligence Engine        │  <-- Timestamp extraction & language fallback
└──────────────────┬─────────────────────┘
                   │
                   ▼
┌────────────────────────────────────────┐
│   Educational Content Classification   │  <-- Filters non-study content
└──────────────────┬─────────────────────┘
                   │
                   ▼
┌────────────────────────────────────────┐
│  Cleaning, Chunking & Translation      │  <-- Clean text, semantic chunking, translation
└──────────────────┬─────────────────────┘
                   │
         ┌─────────┴─────────┐
         ▼                   ▼
┌──────────────────┐ ┌────────────────────────┐
│ Detailed Notes   │ │ Concept Graph Builder  │
│ & JSON Synthesis │ │ (Nodes, Edges & DAG)   │
└────────┬─────────┘ └────────────────────────┘
         │
         ├───────────────────────┬──────────────────────┐
         ▼                       ▼                      ▼
┌──────────────────┐   ┌──────────────────┐   ┌──────────────────┐
│ Active-Recall    │   │ ChromaDB Vector  │   │ Interactive HTML │
│ Flashcards       │   │ Store & RAG Chat │   │ Notes Export     │
└──────────────────┘   └──────────────────┘   └──────────────────┘
```

---

## 📂 Project Structure

```text
youtube_summarizer/
├── app.py                      # Flask application entry point & routes
├── auth.py                     # User authentication & session handling (SQLite)
├── config.py                   # API clients configuration (Gemini, Groq)
├── detailed_notes.py           # Multi-stage detailed notes generation
├── detailed_notes_json.py      # Structured JSON notes schema converter
├── flashcard.py                # Study flashcards generator
├── html_generator.py           # Standalone HTML notes generator
├── summary.py                  # Chunk and video summarization engine
├── json_summary.py             # JSON structured summary generator
├── pipeline_test.py            # End-to-end integration pipeline runner
│
├── cie/                        # Caption Intelligence Engine
│   ├── timestamp_transcript.py # Timestamped extractor with language fallback
│   └── playlist_transcripts.py # Playlist crawler, metadata caching & manifest
│
├── pipeline/                   # Core Processing Pipeline
│   ├── get_transcript.py       # Base transcript retrieval & language resolution
│   ├── classify_content.py     # Educational content validator
│   ├── clean_transcript.py     # Transcript cleaning & filler word removal
│   ├── chunking.py             # Transcript text chunker
│   ├── translate.py            # Dynamic non-English translator
│   └── concept_graph.py        # Knowledge concept graph & prerequisite builder
│
├── rag/                        # Retrieval-Augmented Generation
│   ├── embedding/
│   │   ├── chunker.py          # Structured RAG document chunking
│   │   └── embedder.py         # Multilingual sentence transformer embeddings
│   ├── vector_store.py         # ChromaDB client, indexing & similarity queries
│   ├── retrieval.py            # Query-context retrieval engine
│   └── chat.py                 # Groq-powered AI tutor chat engine
│
├── templates/                  # Frontend HTML templates (Auth, Dashboard, Notes, Course)
└── static/                     # Frontend styling & interactive JavaScript modules
```

---

## ⚡ Quickstart & Installation

### 1. Clone the Repository
```bash
git clone https://github.com/Rohitagrawal15021/youtube_summarizer.git
cd youtube_summarizer
```

### 2. Create and Activate Virtual Environment
```bash
# Windows
python -m venv venv
.\venv\Scripts\activate

# Linux / macOS
python3 -m venv venv
source venv/bin/activate
```

### 3. Install Dependencies
```bash
pip install -r requirements.txt
```

### 4. Configure Environment Variables
Create a `.env` file in the project root:
```env
GEMINI_API_KEY=your_gemini_api_key_here
GROQ_API_KEY=your_groq_api_key_here
SECRET_KEY=your_flask_secret_key_here
```

---

## 🚀 Running the Project

### A. Run Full Pipeline Test (CLI)
Test all components end-to-end on any YouTube video or playlist:
```bash
# Interactive mode (prompts for URL):
python pipeline_test.py

# Single video:
python pipeline_test.py "https://www.youtube.com/watch?v=VIDEO_ID"

# Full Playlist:
python pipeline_test.py "https://www.youtube.com/playlist?list=PLAYLIST_ID"
```

### B. Launch the Web Application
```bash
python app.py
```
Visit `http://localhost:5000` in your browser.

---

## 🛠️ Tech Stack & Libraries

- **Language:** Python 3.10+
- **Web Framework:** Flask
- **LLM Providers:** Google Gemini API (`gemini-2.0-flash`, `gemini-3.5-flash`), Groq Cloud (`llama-3.3-70b-versatile`)
- **Vector Store:** ChromaDB
- **Embeddings:** HuggingFace `sentence-transformers` (`paraphrase-multilingual-MiniLM-L12-v2`)
- **Captions & Extraction:** `youtube-transcript-api`, `yt-dlp`
- **Language Detection:** `langdetect`
