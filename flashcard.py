import json
from config import generate_with_retry
from google.genai import types


def generate_flashcards(detailed_notes, number_of_flashcards=15):

    # Convert the detailed notes dictionary into JSON text
    notes_json = json.dumps(detailed_notes, ensure_ascii=False, indent=2)

    prompt = f"""
You are an expert educational assessment and flashcard generation system.

Your task is to generate high-quality study flashcards from the structured
lecture notes provided below.

The flashcards will be used by students for active recall and revision.

IMPORTANT RULES:

1. Return ONLY valid JSON.
2. Do NOT include markdown.
3. Do NOT wrap the JSON inside ```json.
4. Generate exactly {number_of_flashcards} flashcards.
5. Use ONLY information present in the provided lecture notes.
6. Do NOT invent facts or information.
7. Cover the important concepts from different sections of the lecture.
8. Avoid generating multiple flashcards asking essentially the same question.
9. Questions should test understanding, not just memorization.
10. Keep answers concise but educational.
11. Preserve technical terminology from the lecture notes.
12. If the lecture contains formulas, algorithms, code, comparisons,
    definitions, examples or important concepts, create appropriate
    flashcards from them.
13. Include a mixture of difficulty levels:
       - easy
       - medium
       - hard
14. Avoid questions whose answers are obvious from the question itself.
15. Each flashcard must be understandable without requiring the student
    to see the original lecture.
16. Return valid JSON that can be parsed directly using json.loads().

FLASHCARD TYPES:

- definition
- concept
- comparison
- application
- formula
- example
- code
- reasoning

Use the most appropriate type for each flashcard.

JSON SCHEMA:

{{
    "flashcards":
    [
        {{
            "id": 1,
            "question": "",
            "answer": "",
            "type": "",
            "difficulty": "",
            "topic": ""
        }}
    ]
}}

LECTURE NOTES:

{notes_json}
"""

    response = generate_with_retry(
        model="gemini-3.5-flash",
        contents=prompt,
        config=types.GenerateContentConfig(
            temperature=0.3,
            response_mime_type="application/json"
        )
    )

    if not response.text:
        print("Gemini returned an empty response.")
        return None

    try:
        flashcards = json.loads(response.text)
        return flashcards

    except json.JSONDecodeError:
        print("Invalid JSON returned by Gemini.")
        print(response.text)
        return None