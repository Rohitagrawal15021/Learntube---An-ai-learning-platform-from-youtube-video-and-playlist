import json
from config import generate_with_retry
from google.genai import types

def detailed_notes_json(detailed_notes):
    prompt = f"""
You are an expert educator and educational content structuring system.

Your task is to convert the following detailed lecture notes into a well-structured JSON object.

The JSON must preserve all educational information while organizing it into logical sections.

Instructions:

1. Return ONLY valid JSON.
2. Do NOT include markdown.
3. Do NOT wrap the JSON inside ```json.
4. Do NOT summarize aggressively.
5. Preserve every important concept.
6. Preserve the original topic order.
7. Keep technical terms exactly as written.
8. Keep definitions accurate.
9. Preserve formulas, equations, reactions and code snippets.
10. Preserve examples.
11. If a field has no data, return an empty list.
12. The output must be valid JSON that can be parsed directly using json.loads().

JSON Schema:

{{
    "title": "",

    "difficulty": "",

    "estimated_study_time": "",

    "overview": "",

    "sections":
    [
        {{
            "heading":"",

            "subtopics":
            [
                {{
                    "title":"",

                    "content":"",

                    "important_points":[],

                    "examples":[],

                    "learning_assets":
                    [
                        {{
                            "type":"",
                            "title":"",
                            "content":""
                        }}
                    ],

                    "common_mistakes":[]
                }}
            ]
        }}
    ],

    "definitions":
    [
        {{
            "term":"",
            "meaning":""
        }}
    ],

    "important_terms":[],

    "key_takeaways":[],

    "exam_tips":[],

    "memory_tricks":[],

    "frequently_confused_topics":
    [
        {{
            "topic":"",
            "confusion":"",
            "correct_concept":""
        }}
    ],

    "summary":""
}}

Detailed Lecture Notes:

{detailed_notes}
"""
    response = generate_with_retry(
        model="gemini-3.5-flash",
        contents=prompt,
        config=types.GenerateContentConfig(
        temperature=0.2,
        response_mime_type="application/json"
        )
    )
    if not response.text:
       print("Gemini returned an empty response.")
       return None

    try:
        detailed_notes = json.loads(response.text)
        return detailed_notes

    except json.JSONDecodeError:
        print("Invalid JSON returned by Gemini.")
        return None