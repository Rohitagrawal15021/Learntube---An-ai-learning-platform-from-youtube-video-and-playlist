"""Generate study answers from retrieved video chunks with Groq."""

import os
from typing import Any

from dotenv import load_dotenv

from rag.retrieval import retrieve_relevant_chunks


load_dotenv()

DEFAULT_MODEL = "openai/gpt-oss-20b"

SYSTEM_PROMPT = """You are a patient, knowledgeable study tutor helping a student learn from a YouTube video.

Your primary source is the retrieved video passages supplied with the question.
Cite factual statements from those passages with source labels such as [S1].

TOPIC GUARDRAIL (IMPORTANT):
- You must ONLY answer questions related to the video content and the topics
  covered in it.
- If the student asks about something completely unrelated to this video
  (e.g., random trivia, personal questions, topics not covered in the lecture),
  politely decline and say: "That topic isn't covered in this video. I can only
  help with questions related to this lecture. Here are some topics I can help
  with:" and then list 3-4 key topics from the retrieved passages.
- Questions that are tangentially related (e.g., asking for deeper explanation
  of a concept mentioned in the video, or code examples for a topic from the
  video) ARE allowed and should be answered fully.

GUIDELINES:
1. **Explain concepts clearly.** When a student asks about a concept, give a
   thorough explanation with:
   - A clear definition in simple terms
   - An intuitive analogy or real-world example
   - How it connects to other concepts in the video
   - Step-by-step breakdowns for complex ideas

2. **Write code when asked.** If the student asks for code related to a topic
   from the video, provide clean, well-commented code in proper markdown code
   blocks with the correct language tag (```python, ```javascript, etc.).
   Include explanations of how the code works.

3. **Supplement wisely.** Use the retrieved passages as your primary context,
   but you may use your own knowledge to:
   - Explain concepts more clearly than the source material
   - Provide additional examples or analogies
   - Write code implementations of concepts discussed in the video
   - Fill in gaps when the retrieved passages don't fully cover the question
   When adding information beyond the video, note it briefly
   (e.g., "Beyond the video material, …").

4. **Format for readability.** Use markdown formatting:
   - Headings for organized sections
   - Bullet points for lists
   - Code blocks for any code
   - Bold for key terms
   - Tables when comparing concepts
"""


_groq_client = None


def _get_groq_client():
    """Create and cache the Groq SDK client using the server-side API key."""
    global _groq_client

    if _groq_client is None:
        api_key = os.getenv("GROQ_API_KEY")
        if not api_key:
            raise RuntimeError("GROQ_API_KEY is missing from the server environment.")

        try:
            from groq import Groq
        except ModuleNotFoundError as exc:
            if exc.name == "groq":
                raise RuntimeError(
                    "The Groq SDK is not installed. Run: python -m pip install groq"
                ) from exc
            raise

        _groq_client = Groq(api_key=api_key)

    return _groq_client


def _source_label(index: int, match: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    """Format one retrieved chunk for the prompt and API response."""
    metadata = match.get("metadata") or {}
    source_id = f"S{index}"
    section = metadata.get("section") or metadata.get("title") or "Video notes"
    chunk_index = metadata.get("chunk_index")

    source_text = f"[{source_id}] Section: {section}"
    if chunk_index is not None:
        source_text += f"; chunk {chunk_index}"
    source_text += f"\n{match.get('text', '')}"

    source_result = {
        "id": source_id,
        "section": section,
        "chunk_index": chunk_index,
        "similarity": match.get("similarity"),
        "text": match.get("text", ""),
    }
    for key in ("start_time", "start_seconds", "timestamp"):
        if key in metadata:
            source_result["timestamp"] = metadata[key]
            break

    return source_text, source_result


def answer_video_question(
    question: str,
    video_id: str,
    top_k: int = 5,
) -> dict[str, Any]:
    """Retrieve context for one video and ask Groq to answer from it."""
    question = (question or "").strip()
    video_id = (video_id or "").strip()

    if not question:
        raise ValueError("question must not be empty")
    if not video_id:
        raise ValueError("video_id must not be empty")

    matches = retrieve_relevant_chunks(
        query=question,
        video_id=video_id,
        top_k=top_k,
    )

    if not matches:
        return {
            "answer": "I couldn't find relevant information in this video's material.",
            "sources": [],
            "model": None,
        }

    prompt_sources = []
    response_sources = []
    for index, match in enumerate(matches, start=1):
        prompt_source, response_source = _source_label(index, match)
        prompt_sources.append(prompt_source)
        response_sources.append(response_source)

    user_message = (
        "Retrieved passages from the current video:\n\n"
        + "\n\n".join(prompt_sources)
        + f"\n\nStudent question:\n{question}"
    )

    # RAG chat benefits from a reasoning model (gpt-oss) for deeper Q&A.
    # This is intentionally separate from GROQ_MODEL which is used by the
    # pipeline fallback (translation, summarisation) where non-reasoning
    # models like qwen are preferred to avoid wasting tokens on thinking.
    model = os.getenv("GROQ_RAG_MODEL", DEFAULT_MODEL)
    completion = _get_groq_client().chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_message},
        ],
        temperature=0.2,
        max_completion_tokens=2048,
    )

    answer = completion.choices[0].message.content
    if not answer:
        raise RuntimeError("Server error: Unable to generate answer.")

    return {
        "answer": answer.strip(),
        "sources": response_sources,
        "model": model,
    }
