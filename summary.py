from config import generate_with_retry
from google.genai import types


def summarize_chunk(chunk):
    """
    Summarizes one chunk (or a group of chunks).
    """

    prompt = f"""
You are an expert AI study assistant.

Your task is to summarize the following educational transcript.

Instructions:
1. Preserve all important concepts and key ideas.
2. Keep technical terms exactly as they appear.
3. Remove filler words, repetitions, greetings, and unrelated conversation.
4. Maintain the logical order of topics.
5. Do NOT add any information that is not present in the text.
6. Do NOT explain beyond what the speaker says.
7. Write in simple and clear English so students can easily understand.
8. Keep code snippets, formulas, and algorithms if they are important.
9. Return the summary in well-structured paragraphs.
10. Return ONLY the summarized study notes.

Transcript:
{chunk}
"""

    response = generate_with_retry(
        model="gemini-2.0-flash",
        contents=prompt,
        config=types.GenerateContentConfig(
            temperature=0.2
        )
    )

    if not response.text:
        print("Gemini returned an empty summary.")
        return ""

    return response.text.strip()


def summarize_chunks(chunks):
    """
    Summarizes transcript chunks in groups of 4.
    """

    summarized_chunks = []

    group_size = 4

    for i in range(0, len(chunks), group_size):

        # Take 4 chunks at a time
        group = chunks[i:i + group_size]

        # Combine them into one string
        combined_group = "\n\n".join(group)

        print(f"Summarizing Group {(i // group_size) + 1}...")

        summarized_chunk = summarize_chunk(combined_group)

        summarized_chunks.append(summarized_chunk)

    return summarized_chunks


def final_summary(combined_chunk):
    """
    Combines all group summaries into one final summary.
    """

    print("\n📝 Generating Final Study Notes...\n")

    prompt = f"""
You are an expert educator and technical note-maker.

The following text contains summaries of different sections of the same educational lecture.

Your task is to combine these section summaries into one coherent, well-structured final summary.

Instructions:
1. Merge all summaries into a single document.
2. Maintain the original order of topics.
3. Remove duplicate or repeated information.
4. Preserve all important concepts, definitions, and technical terms.
5. Preserve important formulas, algorithms, and code-related explanations.
6. Improve the logical flow between paragraphs.
7. Use simple and clear English suitable for students.
8. Do NOT add any new information or examples.
9. Do NOT remove important concepts.
10. Return ONLY the final summary.

Section Summaries:
{combined_chunk}
"""

    response = generate_with_retry(
        model="gemini-2.0-flash",
        contents=prompt,
        config=types.GenerateContentConfig(
            temperature=0.2
        )
    )

    if not response.text:
        print("Gemini returned an empty final summary.")
        return ""

    return response.text.strip()
