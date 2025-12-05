"""
table_parser.py

Parses extracted table text per company using a Large Language Model (LLM):
- Reads extracted text from memory or cached text files
- Loads instructions and JSON schema from Prompts/prompts_table.json
- Sends extracted text + instructions to the LLM
- Returns structured output as a Python dictionary, ensuring valid JSON even if LLM output is messy
"""

import os
import json
from openai import OpenAI

from config import OPENAI_MODEL , PROMPTS_TABLE

from dotenv import load_dotenv
load_dotenv()

# ---------- Configuration ----------
LLM_API_KEY = os.getenv("OPENAI_API_KEY")
MODEL_NAME = OPENAI_MODEL
PROMPT_JSON_PATH = PROMPTS_TABLE
# -----------------------------------
import json
import re

# def parser_for_table(extracted_text: str, prompt_json_path: str) -> dict:
#     """
#     Use LLM to extract structured info from extracted text according to the prompt JSON.
#     Returns a Python dictionary, ensuring valid JSON even if the LLM output is messy.

#     :param extracted_text: str, text extracted from table PDFs for a company
#     :param prompt_json_path: path to the JSON file containing task_description and output_json_structure
#     :param client: LLM client object
#     :param model_name: model name for the LLM
#     :return: dict, parsed JSON (fallback to {"_raw": <LLM output>} if parsing fails)
#     """
#     client = Groq(api_key=LLM_API_KEY)
#     model_name = MODEL_NAME

#     # Load extraction instructions from JSON
#     with open(prompt_json_path, "r", encoding="utf-8") as f:
#         prompt_data = json.load(f)

#     instruction = prompt_data.get("task_description", "")
#     json_schema = prompt_data.get("output_json_structure", {})

#     # Escape curly braces to avoid f-string issues
#     safe_text = extracted_text.replace("{", "{{").replace("}", "}}")

#     # Construct LLM prompt
#     prompt = f"""
# You are an expert financial analyst specializing in sustainable finance documentation.

# {instruction}

# Analyze the following text extracted from framework and SPO:
# ---
# {safe_text}
# ---

# Return ONLY valid JSON, strictly following this schema:
# {json.dumps(json_schema, indent=2)}

# Important: Output only the JSON object, without any markdown or explanations.
# """

#     # Send request to the LLM
#     response = client.chat.completions.create(
#         model=model_name,
#         messages=[{"role": "user", "content": prompt}],
#         temperature = 0.0
#     )

#     # Get LLM content
#     try:
#         content = response.choices[0].message.content
#     except Exception:
#         content = str(response)

#     # Attempt to parse JSON safely
#     parsed = None
#     try:
#         parsed = json.loads(content)
#     except json.JSONDecodeError:
#         # Try to extract JSON-looking content using regex
#         m = re.search(r'(\{.*\}|\[.*\])', content, flags=re.S)
#         if m:
#             try:
#                 parsed = json.loads(m.group(1))
#             except Exception:
#                 parsed = {"_raw": content}
#         else:
#             parsed = {"_raw": content}

#     # Ensure a dictionary is always returned
#     if not isinstance(parsed, dict):
#         parsed = {"_parsed": parsed}

#     return parsed

def parser_for_table(extracted_text: str, prompt_json_path: str) -> dict:
    """
    Use OpenAI's LLM to extract structured info from extracted text according to the prompt JSON.
    Returns a Python dictionary, ensuring valid JSON even if the LLM output is messy.

    :param extracted_text: str, text extracted from table PDFs for a company
    :param prompt_json_path: path to the JSON file containing task_description and output_json_structure
    :return: dict, parsed JSON (fallback to {"_raw": <LLM output>} if parsing fails)
    """

    # Initialize OpenAI client
    client = OpenAI(api_key=LLM_API_KEY)
    model_name = MODEL_NAME

    # Load extraction instructions from JSON
    with open(prompt_json_path, "r", encoding="utf-8") as f:
        prompt_data = json.load(f)

    instruction = prompt_data.get("task_description", "")
    json_schema = prompt_data.get("output_json_structure", {})

    # Escape curly braces to avoid f-string issues
    safe_text = extracted_text.replace("{", "{{").replace("}", "}}")

    # Construct LLM prompt
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

    # Send request to the OpenAI model
    response = client.chat.completions.create(
        model=model_name,
        messages=[{"role": "user", "content": prompt}],
        temperature=0.0,
    )

    # Get model output
    try:
        content = response.choices[0].message.content
    except Exception:
        content = str(response)

    # Attempt to parse JSON safely
    parsed = None
    try:
        parsed = json.loads(content)
    except json.JSONDecodeError:
        # Try to extract JSON-like content using regex
        m = re.search(r'(\{.*\}|\[.*\])', content, flags=re.S)
        if m:
            try:
                parsed = json.loads(m.group(1))
            except Exception:
                parsed = {"_raw": content}
        else:
            parsed = {"_raw": content}

    # Ensure a dictionary is always returned
    if not isinstance(parsed, dict):
        parsed = {"_parsed": parsed}

    return parsed

    

