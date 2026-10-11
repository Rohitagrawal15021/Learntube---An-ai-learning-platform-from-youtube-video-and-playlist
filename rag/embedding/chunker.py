import json
import re


# --------------------------------------------------
# Configuration
# --------------------------------------------------

# The embedding model (paraphrase-multilingual-MiniLM-L12-v2) truncates input
# at 128 tokens — roughly 90-100 English words, fewer for other languages.
# Chunks larger than that silently lose their tail at embedding time, so keep
# chunks comfortably under that ceiling and overlap them so a sentence split
# across two chunks is still retrievable from either side.
MAX_CHUNK_WORDS = 90
OVERLAP_WORDS = 15


# --------------------------------------------------
# Basic text cleaning
# --------------------------------------------------

def clean_text(text):
    """
    Clean unnecessary whitespace from text.
    """

    if not text:
        return ""

    text = str(text)

    # Replace multiple spaces/newlines
    text = re.sub(r"\s+", " ", text)

    return text.strip()


# --------------------------------------------------
# Split a long section into semantic-ish chunks
# --------------------------------------------------

def split_long_text(text, max_words=MAX_CHUNK_WORDS, overlap_words=OVERLAP_WORDS):
    """
    Split long text on sentence boundaries into chunks of at most ``max_words``.

    Consecutive chunks overlap by roughly ``overlap_words`` words (carried over
    as whole trailing sentences) so a concept that straddles a boundary is still
    retrievable from both chunks.
    """

    text = clean_text(text)

    if not text:
        return []

    words = text.split()

    # Section is already small enough
    if len(words) <= max_words:
        return [text]

    # Split into sentences
    sentences = [
        s.strip()
        for s in re.split(r"(?<=[.!?])\s+", text)
        if s.strip()
    ]

    chunks = []
    current_chunk = []
    current_words = 0

    for sentence in sentences:

        sentence_words = len(sentence.split())

        # If adding this sentence exceeds the limit, flush the current chunk
        # and seed the next one with an overlapping tail.
        if (
            current_words + sentence_words > max_words
            and current_chunk
        ):
            chunks.append(" ".join(current_chunk).strip())

            overlap = []
            overlap_count = 0
            for prev in reversed(current_chunk):
                prev_words = len(prev.split())
                if overlap_count + prev_words > overlap_words and overlap:
                    break
                overlap.insert(0, prev)
                overlap_count += prev_words

            current_chunk = list(overlap)
            current_words = overlap_count

        current_chunk.append(sentence)
        current_words += sentence_words

    # Add remaining text
    if current_chunk:
        chunks.append(
            " ".join(current_chunk).strip()
        )

    return chunks


# --------------------------------------------------
# Create RAG documents from one section
# --------------------------------------------------

def _subtopic_to_text(subtopic):
    """
    Flatten one subtopic dict into a single readable text block.

    The notes schema stores a section's actual teaching content under
    ``sections[].subtopics[]`` — NOT a flat ``section.content`` field. Reading
    the wrong key is what previously caused almost every section to be dropped
    and the whole lecture to collapse into one or two RAG chunks.
    """

    parts = []

    title = clean_text(subtopic.get("title", ""))
    if title:
        parts.append(f"{title}.")

    content = clean_text(subtopic.get("content", ""))
    if content:
        parts.append(content)

    points = [
        clean_text(p)
        for p in (subtopic.get("important_points") or [])
        if clean_text(p)
    ]
    if points:
        parts.append("Important points: " + "; ".join(points) + ".")

    examples = [
        clean_text(e)
        for e in (subtopic.get("examples") or [])
        if clean_text(e)
    ]
    if examples:
        parts.append("Examples: " + "; ".join(examples) + ".")

    mistakes = [
        clean_text(m)
        for m in (subtopic.get("common_mistakes") or [])
        if clean_text(m)
    ]
    if mistakes:
        parts.append("Common mistakes: " + "; ".join(mistakes) + ".")

    return " ".join(parts).strip()


def create_section_chunks(
    heading,
    content,
    note_id,
    title,
    subtopic_index=0
):
    """
    Convert one subtopic's flattened text into
    RAG-ready documents.
    """

    heading = clean_text(heading)
    content = clean_text(content)

    if not content:
        return []

    text_chunks = split_long_text(content)

    documents = []

    for index, chunk in enumerate(text_chunks):

        # Include heading inside the actual document.
        # This helps retrieval understand the context.
        document_text = (
            f"Topic: {heading}\n\n"
            f"{chunk}"
        )

        documents.append({
            "text": document_text,

            "metadata": {
                "note_id": str(note_id),
                "title": title,
                "section": heading,
                "subtopic_index": subtopic_index,
                "chunk_index": index,
                "source_type": "section"
            }
        })

    return documents


# --------------------------------------------------
# Create RAG chunks from JSON
# --------------------------------------------------

def create_rag_chunks(
    json_file="json_txt.json",
    note_id="default_note"
):
    """
    Read detailed notes JSON and convert it into
    structure-aware RAG documents.
    Supports passing a file path or an already-parsed JSON dictionary.
    """

    if isinstance(json_file, dict):
        notes = json_file
    else:
        with open(
            json_file,
            "r",
            encoding="utf-8"
        ) as file:
            notes = json.load(file)

    title = notes.get(
        "title",
        "Untitled Lecture"
    )

    rag_documents = []

    # --------------------------------------------------
    # 1. Overview
    # --------------------------------------------------

    overview = clean_text(
        notes.get("overview", "")
    )

    if overview:

        rag_documents.append({
            "text": (
                f"Topic: Overview\n\n"
                f"{overview}"
            ),

            "metadata": {
                "note_id": str(note_id),
                "title": title,
                "section": "Overview",
                "chunk_index": 0,
                "source_type": "overview"
            }
        })

    # --------------------------------------------------
    # 2. Main sections
    # --------------------------------------------------

    sections = notes.get(
        "sections",
        []
    )

    for section in sections:

        heading = section.get(
            "heading",
            ""
        )

        subtopics = section.get("subtopics", []) or []

        # New schema: teaching content lives in subtopics. Older note files may
        # still carry a flat "content" string — handle both.
        if subtopics:
            for sub_index, subtopic in enumerate(subtopics):
                sub_text = _subtopic_to_text(subtopic)
                rag_documents.extend(
                    create_section_chunks(
                        heading=heading,
                        content=sub_text,
                        note_id=note_id,
                        title=title,
                        subtopic_index=sub_index,
                    )
                )
        else:
            rag_documents.extend(
                create_section_chunks(
                    heading=heading,
                    content=section.get("content", ""),
                    note_id=note_id,
                    title=title,
                )
            )

    # --------------------------------------------------
    # 3. Definitions
    # --------------------------------------------------

    definitions = notes.get(
        "definitions",
        []
    )

    for index, definition in enumerate(definitions):

        term = clean_text(
            definition.get("term", "")
        )

        meaning = clean_text(
            definition.get("meaning", "")
        )

        if not term or not meaning:
            continue

        document_text = (
            f"Definition: {term}\n\n"
            f"{meaning}"
        )

        rag_documents.append({
            "text": document_text,

            "metadata": {
                "note_id": str(note_id),
                "title": title,
                "section": "Definitions",
                "term": term,
                "chunk_index": index,
                "source_type": "definition"
            }
        })

    # --------------------------------------------------
    # 4. Important terms
    # --------------------------------------------------

    important_terms = notes.get(
        "important_terms",
        []
    )

    if important_terms:

        terms_text = ", ".join(
            clean_text(term)
            for term in important_terms
            if term
        )

        if terms_text:

            rag_documents.append({
                "text": (
                    "Important Terms:\n\n"
                    + terms_text
                ),

                "metadata": {
                    "note_id": str(note_id),
                    "title": title,
                    "section": "Important Terms",
                    "chunk_index": 0,
                    "source_type": "important_terms"
                }
            })

    # --------------------------------------------------
    # 5. Key takeaways
    # --------------------------------------------------

    key_takeaways = notes.get(
        "key_takeaways",
        []
    )

    for index, takeaway in enumerate(
        key_takeaways
    ):

        takeaway = clean_text(takeaway)

        if not takeaway:
            continue

        rag_documents.append({
            "text": (
                "Key Takeaway:\n\n"
                + takeaway
            ),

            "metadata": {
                "note_id": str(note_id),
                "title": title,
                "section": "Key Takeaways",
                "chunk_index": index,
                "source_type": "key_takeaway"
            }
        })

    # --------------------------------------------------
    # 6. Exam tips
    # --------------------------------------------------

    exam_tips = notes.get(
        "exam_tips",
        []
    )

    for index, tip in enumerate(exam_tips):

        tip = clean_text(tip)

        if not tip:
            continue

        rag_documents.append({
            "text": (
                "Exam Tip:\n\n"
                + tip
            ),

            "metadata": {
                "note_id": str(note_id),
                "title": title,
                "section": "Exam Tips",
                "chunk_index": index,
                "source_type": "exam_tip"
            }
        })

    # --------------------------------------------------
    # 6b. Memory tricks
    # --------------------------------------------------

    memory_tricks = notes.get("memory_tricks", [])

    for index, trick in enumerate(memory_tricks):

        trick = clean_text(trick)

        if not trick:
            continue

        rag_documents.append({
            "text": (
                "Memory Trick:\n\n"
                + trick
            ),

            "metadata": {
                "note_id": str(note_id),
                "title": title,
                "section": "Memory Tricks",
                "chunk_index": index,
                "source_type": "memory_trick"
            }
        })

    # --------------------------------------------------
    # 6c. Frequently confused topics
    # --------------------------------------------------

    confused = notes.get("frequently_confused_topics", [])

    for index, item in enumerate(confused):

        topic = clean_text(item.get("topic", ""))
        confusion = clean_text(item.get("confusion", ""))
        correct = clean_text(item.get("correct_concept", ""))

        if not topic and not confusion and not correct:
            continue

        document_text = (
            f"Frequently Confused: {topic}\n\n"
            f"Common confusion: {confusion}\n\n"
            f"Correct concept: {correct}"
        )

        rag_documents.append({
            "text": document_text,

            "metadata": {
                "note_id": str(note_id),
                "title": title,
                "section": "Frequently Confused Topics",
                "topic": topic,
                "chunk_index": index,
                "source_type": "frequently_confused"
            }
        })

    # --------------------------------------------------
    # 7. Final summary
    # --------------------------------------------------

    summary = clean_text(
        notes.get("summary", "")
    )

    if summary:

        rag_documents.append({
            "text": (
                "Lecture Summary:\n\n"
                + summary
            ),

            "metadata": {
                "note_id": str(note_id),
                "title": title,
                "section": "Summary",
                "chunk_index": 0,
                "source_type": "summary"
            }
        })

    return rag_documents


# --------------------------------------------------
# Testing
# --------------------------------------------------

if __name__ == "__main__":
    chunks = create_rag_chunks(
        json_file="json_txt.json",
        note_id="test_note_001"
    )
    print(f"\nTotal RAG documents: {len(chunks)}\n")

    # Generate embeddings for each chunk text
    from rag.embedding.embedder import create_embeddings
    texts = [chunk["text"] for chunk in chunks]
    embeddings = create_embeddings(texts)

    for i, (chunk, embedding) in enumerate(zip(chunks, embeddings)):
        print("=" * 70)
        print(f"Chunk {i + 1}")
        print("\nMetadata:")
        print(chunk["metadata"])
        print("\nText (first 500 chars):")
        print(chunk["text"][:500])
        print("\nEmbedding (first 5 values):")
        print(embedding[:5])
        print()