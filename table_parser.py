"""
table_parser.py
"""

import os
import json
import re
from openai import OpenAI
from dotenv import load_dotenv

from config import OPENAI_MODEL, PROMPTS_TABLE

load_dotenv()

# ---------- Configuration ----------
# REMOVED: LLM_API_KEY = os.getenv("OPENAI_API_KEY") <-- CAUSES ERROR
MODEL_NAME = OPENAI_MODEL
# -----------------------------------

def parser_for_table(extracted_text: str, prompt_json_path: str) -> dict:
    # FIX: Fetch API Key right here
    api_key = os.getenv("OPENAI_API_KEY")
    
    if not api_key:
        raise ValueError("OPENAI_API_KEY is missing. Please enter it in the sidebar.")

    client = OpenAI(api_key=api_key)
    
    # Load extraction instructions from JSON
    with open(prompt_json_path, "r", encoding="utf-8") as f:
        prompt_data = json.load(f)

    instruction = prompt_data.get("task_description", "")
    json_schema = prompt_data.get("output_json_structure", {})

    safe_text = extracted_text.replace("{", "{{").replace("}", "}}")

    prompt = f"""
You are an expert financial analyst specializing in sustainable finance documentation.

{instruction}

Analyze the following text extracted from framework and SPO:
---
{safe_text}
---

Return ONLY valid JSON, strictly following this schema:
{json.dumps(json_schema, indent=2)}

Important: Output only the JSON object, without any markdown or explanations.
"""

    response = client.chat.completions.create(
        model=MODEL_NAME,
        messages=[{"role": "user", "content": prompt}],
        temperature=0.0,
    )

    try:
        content = response.choices[0].message.content
    except Exception:
        content = str(response)

    try:
        parsed = json.loads(content)
    except json.JSONDecodeError:
        m = re.search(r'(\{.*\}|\[.*\])', content, flags=re.S)
        if m:
            try:
                parsed = json.loads(m.group(1))
            except Exception:
                parsed = {"_raw": content}
        else:
            parsed = {"_raw": content}

    if not isinstance(parsed, dict):
        parsed = {"_parsed": parsed}

    return parsed