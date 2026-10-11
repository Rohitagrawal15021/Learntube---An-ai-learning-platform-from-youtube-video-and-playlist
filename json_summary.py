from config import generate_with_retry
import json
from google.genai import types

def change_to_json(final_summary):
    prompt = f"""
You are an expert educator and study note creator.

Your task is to convert the following educational summary into a structured JSON object.

Instructions:

- Do NOT summarize further.
- Preserve all important concepts.
- Keep technical terms unchanged.
- Organize the information logically.
- Return ONLY valid JSON.
- Do not include markdown.
- Do not wrap the JSON inside ```json.
- If any section has no information, return an empty list.

The JSON schema must be:

{{
"title":"",
"overview":"",
"sections":[
{{
"heading":"",
"content":""
}}
],
"key_points":[],
"definitions":[
{{
"term":"",
"meaning":""
}}
],
"examples":[],
"important_terms":[],
"learning_assets":[],
"common_mistakes":[],
"summary":""
}}

Educational Summary:

{final_summary}
"""
    response = generate_with_retry(
        model="gemini-3.5-flash",
        contents=prompt,
        config=types.GenerateContentConfig(
        temperature=0.2,
        response_mime_type="application/json"
        )
    )
    try:
       notes = json.loads(response.text)
       return notes

    except json.JSONDecodeError:
       print("Invalid JSON returned by Gemini.")
       return None
    
    if not response.text:
        print("Gemini returned an empty response.")
        return None