from config import generate_with_retry
from google.genai import types


def detailed_notes_chunk(chunk):
    """
    Generates detailed notes for one chunk (or a group of chunks).
    """

    prompt = f"""
You are an expert educator and professional study note writer.

Your task is to convert the following educational lecture transcript into comprehensive study notes.

The goal is NOT to summarize aggressively.

The goal is to rewrite the lecture into clean, structured, easy-to-study notes while preserving all important educational content.

Instructions:

1. Preserve every important concept explained by the instructor.
2. Remove greetings, filler words, jokes and repeated sentences.
3. Keep the original order of topics.
4. Rewrite explanations in simple and professional English.
5. Explain concepts clearly but DO NOT invent new information.
6. Keep all technical terms exactly as used.
7. Preserve important formulas, equations and algorithms.
8. Preserve important code snippets.
9. Preserve examples used by the instructor.
10. Use headings and subheadings.
11. Use bullet points wherever appropriate.
12. Highlight important facts.
13. Mention common mistakes if discussed.
14. Make the notes suitable for self-study.
15. Do NOT shorten the lecture unnecessarily.
16. Return only the study notes.

Lecture Transcript:

{chunk}
"""
    try:
        response = generate_with_retry(
        model="gemini-3.5-flash",
        contents=prompt,
        config=types.GenerateContentConfig(
            temperature=0.2
        )
    )

        return response.text.strip() if response.text else ""

    except Exception as e:
        print(f"Error generating notes: {e}")
        return ""


def detail_notes_chunks(chunks):
    """
    Summarizes transcript chunks in groups of 4.
    """

    detailed_notes_list = []

    group_size = 2

    for i in range(0, len(chunks), group_size):

        # Take 4 chunks at a time
        group = chunks[i:i + group_size]

        # Combine them into one string
        combined_group = "\n\n".join(group)

        print(
    f"Generating notes for group {(i//group_size)+1}/{(len(chunks)-1)//group_size+1}"
)

        notes = detailed_notes_chunk(combined_group)

        detailed_notes_list.append(notes)

    return detailed_notes_list

def _merge_pair(notes_a, notes_b):
    """
    Merges two note sections into one using the LLM.
    Each input is a single group's notes, so the combined prompt stays small.
    """

    combined = notes_a + "\n\n" + notes_b

    prompt = f"""
You are an expert technical educator.

The following text contains study notes generated from different parts of the SAME lecture.

Your task is to merge them into one cohesive set of notes.

Instructions:

1. Merge the two sections into one document.
2. Preserve every important concept.
3. Remove duplicate explanations.
4. Maintain the chronological order of topics.
5. Improve transitions between sections.
6. Keep headings and subheadings.
7. Keep definitions, examples, formulas and code.
8. Use bullet points whenever helpful.
9. Make the notes easy to study.
10. Do NOT summarize further.
11. Do NOT remove educational content.
12. Return only the merged lecture notes.
13. Format the output using Markdown.

Lecture Notes:

{combined}
"""
    response = generate_with_retry(
        model="gemini-3.5-flash",
        contents=prompt,
        config=types.GenerateContentConfig(
            temperature=0.2
        )
    )
    # If the merge comes back empty, don't crash on None — fall back to simply
    # concatenating the two sections so no notes are lost.
    if not getattr(response, "text", None) or not response.text.strip():
        print("Merge returned empty — falling back to concatenated sections.")
        return combined
    return response.text.strip()


def final_detailed_notes(notes_list):
    """
    Merges a list of note sections using pairwise (tree-style) reduction.

    Instead of combining everything into one giant prompt, this merges
    two sections at a time — like a tournament bracket — so each LLM call
    stays small enough for Groq's token limits.

    Example with 4 groups:
        Round 1: [G1+G2] → M1,  [G3+G4] → M2
        Round 2: [M1+M2] → Final
    """
    if not notes_list:
        return ""

    # Filter out empty results from failed LLM calls
    current = [n for n in notes_list if n and n.strip()]

    if not current:
        return ""

    if len(current) == 1:
        return current[0]

    merge_round = 1
    while len(current) > 1:
        next_round = []
        total_pairs = (len(current) + 1) // 2

        for i in range(0, len(current), 2):
            if i + 1 < len(current):
                pair_num = i // 2 + 1
                print(f"Merge round {merge_round}, pair {pair_num}/{total_pairs}: merging...")
                merged = _merge_pair(current[i], current[i + 1])
                next_round.append(merged)
            else:
                # Odd one out — carry forward to next round
                print(f"Merge round {merge_round}: carrying forward unpaired section")
                next_round.append(current[i])

        current = next_round
        merge_round += 1

    print("Pairwise merge complete.")
    return current[0]

