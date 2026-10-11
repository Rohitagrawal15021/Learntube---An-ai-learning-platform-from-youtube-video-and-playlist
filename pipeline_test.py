import os
import sys
import json

os.environ["PYTHONUNBUFFERED"] = "1"

# Ensure UTF-8 output encoding for Windows terminals
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)

from langdetect import detect

# Pipeline modules
from pipeline.get_transcript import get_transcript, get_video_id
from pipeline.classify_content import is_study_content
from pipeline.clean_transcript import clean_transcript
from pipeline.chunking import chunk_text
from pipeline.translate import translate_chunks
from pipeline.concept_graph import (
    extract_video_concepts,
    merge_concepts,
    detect_prerequisites,
    make_dag,
    build_graph,
)

# CIE modules (timestamped captions & playlist processing)
from cie.timestamp_transcript import get_timestamped_transcript
from cie.playlist_transcripts import process_playlist

# Notes & JSON generation modules
from detailed_notes import detail_notes_chunks, final_detailed_notes
from detailed_notes_json import detailed_notes_json

# Flashcards module
from flashcard import generate_flashcards

# HTML generator module
from html_generator import generate_html

# RAG modules
from rag.embedding.chunker import create_rag_chunks
from rag.embedding.embedder import create_embeddings
from rag.vector_store import index_video_chunks, query_video_chunks
from rag.retrieval import retrieve_relevant_chunks
from rag.chat import answer_video_question


def run_playlist_pipeline(playlist_url):
    """Executes the full playlist processing and concept graph pipeline."""
    print("\n==================================================")
    print("📋 STARTING PLAYLIST PROCESSING PIPELINE")
    print("==================================================")
    print(f"🔗 Playlist URL: {playlist_url}")
    
    # Step 1: Download & cache timestamped transcripts for playlist
    process_playlist(playlist_url)

    # Step 2: Build the prerequisite concept graph
    print("\n🕸️ Building Cross-Video Knowledge Concept Graph...")
    # Extract playlist ID from URL or folder
    import re
    match = re.search(r"list=([a-zA-Z0-9_-]+)", playlist_url)
    playlist_id = match.group(1) if match else "playlist"
    
    try:
        graph = build_graph(playlist_id=playlist_id)
        print(f"\n✅ Concept Graph successfully built with {len(graph['nodes'])} nodes and {len(graph['edges'])} prerequisite edges!")
    except Exception as e:
        print(f"⚠️ Error building graph: {e}")


def run_single_video_pipeline(url):
    """Executes the complete single-video AI study notes & RAG pipeline."""
    try:
        video_id = get_video_id(url)
        print(f"🎬 Video ID: {video_id}")
    except Exception as e:
        print(f"⚠️ Could not parse video ID from URL: {e}")
        video_id = "test_video"

    # Step 2: Extract timestamped transcript with language fallback
    print("\n📥 Step 2: Fetching timestamped transcript...")
    timestamped_data = None
    try:
        timestamped_data = get_timestamped_transcript(url)
        transcript = " ".join([seg["text"] for seg in timestamped_data.get("segments", [])])
        print(f"✅ Timestamped transcript extracted ({len(timestamped_data.get('segments', []))} segments).")
    except Exception as e:
        print(f"⚠️ Timestamped fetch fallback to standard transcript extractor: {e}")
        transcript = get_transcript(url)

    # Step 3: Check whether the video is educational
    print("\n🎓 Step 3: Classifying content (Educational check)...")
    if not is_study_content(transcript):
        print("❌ This is not an educational video. Aborting pipeline.")
        return
    print("✅ Video confirmed as educational content.")

    # Step 4: Detect language only once
    print("\n🌐 Step 4: Detecting language...")
    language = detect(transcript)
    print(f"🌐 Detected Language: {language}")

    # Step 5: Clean transcript
    print("\n🧹 Step 5: Cleaning transcript...")
    cleaned = clean_transcript(transcript)
    print("------ CLEANED TRANSCRIPT (Preview) ------")
    print(cleaned[:300] + ("..." if len(cleaned) > 300 else ""))

    # Step 6: Chunk the cleaned transcript
    print("\n🧩 Step 6: Chunking transcript...")
    chunks = chunk_text(cleaned)
    print(f"Total Transcript Chunks: {len(chunks)}")

    # Step 7: Translate only if required
    print("\n🌍 Step 7: Translating transcript chunks...")
    if language == "en":
        print("✅ Transcript is already in English. Skipping translation.")
        translated_chunks = chunks
    else:
        print("🌍 Translating transcript chunks into English...")
        translated_chunks = translate_chunks(chunks)

    # Display translated chunks preview
    print("------ TRANSLATED CHUNKS (Preview) ------")
    for i, chunk in enumerate(translated_chunks[:2], start=1):
        print(f"Chunk {i}: {chunk[:80]}...")

    # Step 8: Generating detailed notes for each chunk
    print("\n📝 Step 8: Generating detailed notes from chunks...")
    detailed_notes_list = detail_notes_chunks(translated_chunks)
    final_notes = final_detailed_notes(detailed_notes_list)

    print("\n========== FINAL NOTES DEBUG ==========")
    print("Type:", type(final_notes))
    if final_notes:
        print("Length:", len(final_notes))
        print(final_notes[:300] + "...\n")
    else:
        print("⚠️ final_notes is EMPTY!")

    # Step 9: Convert notes to structured JSON
    print("\n🔄 Step 9: Converting notes to structured JSON format...")
    json_txt = detailed_notes_json(final_notes)
    if json_txt:
        print("✅ Detailed Notes JSON Generated Successfully.")
    else:
        print("⚠️ Could not generate notes JSON.")

    # Step 10: Generate flashcards
    print("\n🎴 Step 10: Generating study flashcards...")
    flashcards_data = None
    if json_txt:
        try:
            flashcards_data = generate_flashcards(json_txt, number_of_flashcards=15)
            if flashcards_data and "flashcards" in flashcards_data:
                print(f"✅ Generated {len(flashcards_data['flashcards'])} flashcards successfully.")
                json_txt["flashcards"] = flashcards_data["flashcards"]
            else:
                print("⚠️ Flashcards response did not contain expected structure.")
        except Exception as e:
            print(f"⚠️ Error generating flashcards: {e}")
    else:
        print("⚠️ Skipping flashcard generation as detailed notes JSON is missing.")

    # Step 11: Concept Extraction & Knowledge Graph
    print("\n🕸️ Step 11: Extracting concepts & prerequisite graph...")
    concept_graph_data = None
    try:
        transcript_for_concepts = timestamped_data if timestamped_data else {
            "video_id": video_id,
            "title": json_txt.get("title", video_id) if json_txt else video_id,
            "segments": [{"text": c, "start": i * 30, "duration": 30} for i, c in enumerate(translated_chunks)]
        }
        concepts = extract_video_concepts(transcript_for_concepts, position=1, title=json_txt.get("title", video_id) if json_txt else video_id)
        if concepts:
            nodes = merge_concepts(concepts)
            edges = detect_prerequisites(nodes)
            edges = make_dag(nodes, edges)
            concept_graph_data = {
                "video_id": video_id,
                "title": json_txt.get("title", video_id) if json_txt else video_id,
                "nodes": nodes,
                "edges": edges,
            }
            print(f"✅ Extracted {len(nodes)} core concepts and {len(edges)} prerequisite relationships.")
            if json_txt:
                json_txt["concept_graph"] = concept_graph_data
    except Exception as e:
        print(f"⚠️ Concept extraction note: {e}")

    # Step 12: Save generated files
    print("\n💾 Step 12: Saving generated files...")
    os.makedirs("data/generated", exist_ok=True)
    if json_txt:
        json_txt['video_id'] = video_id
        with open("json_txt.json", "w", encoding="utf-8") as file:
            json.dump(json_txt, file, indent=4, ensure_ascii=False)
        with open(f"data/generated/{video_id}_notes.json", "w", encoding="utf-8") as file:
            json.dump(json_txt, file, indent=4, ensure_ascii=False)
        print(f"✅ Saved json_txt.json and data/generated/{video_id}_notes.json")

    if flashcards_data:
        with open("flashcards.json", "w", encoding="utf-8") as file:
            json.dump(flashcards_data, file, indent=4, ensure_ascii=False)
        with open(f"data/generated/{video_id}_flashcards.json", "w", encoding="utf-8") as file:
            json.dump(flashcards_data, file, indent=4, ensure_ascii=False)
        print(f"✅ Saved flashcards.json and data/generated/{video_id}_flashcards.json")

    if concept_graph_data:
        with open(f"data/generated/{video_id}_graph.json", "w", encoding="utf-8") as file:
            json.dump(concept_graph_data, file, indent=2, ensure_ascii=False)
        print(f"✅ Saved data/generated/{video_id}_graph.json")

    # Step 13: Generate HTML notes page
    print("\n🌐 Step 13: Generating HTML notes page...")
    try:
        generate_html(input_file="json_txt.json", output_file="notes.html")
        print("✅ Generated notes.html successfully.")
    except Exception as e:
        print(f"⚠️ Error generating HTML page: {e}")

    # Step 14: Create RAG documents/chunks
    print("\n========== Step 14: RAG CHUNKING ==========")
    if json_txt:
        print("📄 Creating structured RAG chunks from notes JSON...")
        rag_chunks = create_rag_chunks(json_txt, note_id=video_id)
    else:
        print("📄 Creating RAG chunks directly from transcript...")
        rag_chunks = [
            {
                "text": chunk,
                "metadata": {
                    "video_id": video_id,
                    "chunk_index": i,
                    "source_type": "transcript",
                },
            }
            for i, chunk in enumerate(translated_chunks)
        ]

    print(f"Total RAG Chunks prepared: {len(rag_chunks)}")

    # Step 15: Generate Embeddings
    print("\n========== Step 15: GENERATING EMBEDDINGS ==========")
    texts = [chunk["text"] for chunk in rag_chunks]
    embeddings = create_embeddings(texts)
    print(f"✅ Generated {len(embeddings)} embeddings (Dimension: {len(embeddings[0]) if embeddings else 0})")

    # Step 16: Store in ChromaDB Vector Database
    print(f"\n========== Step 16: INDEXING INTO CHROMADB ==========")
    indexed_count = index_video_chunks(
        video_id=video_id,
        chunks=rag_chunks,
        embeddings=embeddings,
    )
    print(f"✅ Successfully indexed {indexed_count} chunks into ChromaDB for video '{video_id}'!")

    # Step 17: Test retrieval with a sample query
    print("\n========== Step 17: TESTING RETRIEVAL ==========")
    sample_query = "What is the key concept or takeaway?"
    print(f"🔎 Sample Query: \"{sample_query}\"")
    results = retrieve_relevant_chunks(
        query=sample_query,
        video_id=video_id,
        top_k=2,
    )

    for rank, match in enumerate(results, start=1):
        print(f"\nMatch {rank} [Similarity: {match['similarity']:.4f}]:")
        print(f"  Text: {match['text'][:200]}...")

    # Step 18: Test RAG Chat answering with Groq
    print("\n========== Step 18: TESTING RAG CHAT TUTOR (Groq AI) ==========")
    try:
        chat_response = answer_video_question(
            question=sample_query,
            video_id=video_id,
        )
        print("🤖 RAG Tutor Answer:")
        print(chat_response.get("answer"))
        print("\n📚 Sources used:")
        for src in chat_response.get("sources", []):
            print(f"  - [{src.get('id')}] {src.get('section')}")
    except Exception as e:
        print(f"⚠️ Error testing RAG chat tutor: {e}")

    print("\n==================================================")
    print("🎉 FULL PIPELINE TEST COMPLETED SUCCESSFULLY!")
    print("==================================================")


if __name__ == "__main__":
    print("==================================================")
    print("🚀 STARTING YOUTUBE SUMMARIZER INTEGRATED PIPELINE")
    print("==================================================")

    # Step 1: Get YouTube URL (Video or Playlist)
    if len(sys.argv) > 1 and sys.argv[1].strip():
        url = sys.argv[1].strip()
        print(f"🎬 Using URL from command line argument: {url}")
    else:
        try:
            url = input("\nPaste YouTube Video or Playlist URL (or press Enter for sample test): ").strip()
        except (EOFError, KeyboardInterrupt):
            url = ""

    if not url:
        url = "https://www.youtube.com/watch?v=aircAruvnKk"
        print(f"ℹ️ No URL provided, using default test URL: {url}")

    # Check if URL is a Playlist or Single Video
    if "list=" in url and "watch" not in url or "playlist" in url:
        run_playlist_pipeline(url)
    else:
        run_single_video_pipeline(url)