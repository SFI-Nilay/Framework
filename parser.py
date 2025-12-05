"""
parser.py

This module handles the parsing of extracted PDF text chunks using either Groq or Gemini LLMs.
It supports:

1. Building a TF-IDF index over chunks for retrieval of relevant context.
2. Retrieving top-k relevant chunks for a given prompt.
3. Assembling a context block for LLM input.
4. Calling Groq or Gemini models to extract structured JSON based on prompts.
5. Parsing and returning the LLM outputs as a list of structured JSON objects.
"""

import os
import json
import numpy as np
import time
import re
import openai

from typing import List, Dict, Any
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity
from groq import Groq
from openai import OpenAI

from google import genai
from google.genai import types

from dotenv import load_dotenv
load_dotenv()


# ---------------- TF-IDF Retrieval ---------------- #

def build_tfidf_index(chunks: List[Dict]) -> Dict:
    """
    Build a TF-IDF vectorizer and matrix for a list of text chunks.

    Args:
        chunks (List[Dict]): List of dicts, each containing a 'chunk' key.

    Returns:
        Dict: {
            "vectorizer": TfidfVectorizer object,
            "matrix": TF-IDF feature matrix,
            "texts": List[str] of chunk texts
        }
    """
    texts = [c["chunk"] for c in chunks]
    vectorizer = TfidfVectorizer(stop_words="english", max_features=20000)
    matrix = vectorizer.fit_transform(texts) if texts else None
    return {"vectorizer": vectorizer, "matrix": matrix, "texts": texts}


def retrieve_top_k(query: str, index: Dict, k: int = 5) -> List[int]:
    """
    Retrieve indices of top-k most similar chunks to the query.

    Args:
        query (str): Query string.
        index (Dict): TF-IDF index from `build_tfidf_index`.
        k (int): Number of top results to return.

    Returns:
        List[int]: List of top-k indices into index['texts'] with positive similarity.
    """
    if index["matrix"] is None:
        return []
    qv = index["vectorizer"].transform([query])
    sims = cosine_similarity(qv, index["matrix"]).flatten()
    topk_idx = np.argsort(-sims)[:k]
    return [int(i) for i in topk_idx if sims[i] > 0]


def assemble_context(chunks: List[Dict], top_indices: List[int]) -> str:
    """
    Assemble a human-readable context block from selected chunks.

    Args:
        chunks (List[Dict]): List of chunk dictionaries.
        top_indices (List[int]): List of indices of chunks to include.

    Returns:
        str: Concatenated context string with source, page, and chunk metadata.
    """
    parts = []
    for i in top_indices:
        c = chunks[i]
        header = f"[source: {c.get('source', '?')}] [page: {c.get('page', '?')}] [chunk_idx: {c.get('chunk_index', '?')}]"
        parts.append(header + "\n" + c["chunk"])
    return "\n\n---\n\n".join(parts)


# ---------------- Groq Parsing ---------------- #

def call_groq(model: str, messages: List[Dict], temperature: float = 0.0, max_retries: int = 3) -> Dict:
    """
    Call Groq chat model with retries.

    Args:
        model (str): Groq model name.
        messages (List[Dict]): List of messages with "role" and "content".
        temperature (float): Sampling temperature.
        max_retries (int): Number of retry attempts if call fails.

    Returns:
        Dict: Raw response from Groq API.
    """
    api_key = os.getenv("GROQ_API_KEY")
    if not api_key:
        raise EnvironmentError("GROQ_API_KEY not set in environment.")

    client = Groq(api_key=api_key) if hasattr(Groq, "__call__") else Groq()

    for attempt in range(1, max_retries + 1):
        try:
            response = client.chat.completions.create(
                model=model,
                messages=messages,
                temperature=temperature
            )
            return response
        except Exception as e:
            if attempt == max_retries:
                raise
            time.sleep(1.0 * attempt)


def parse_with_llm_groq(chunks: List[Dict], prompts_path: str, groq_model: str, top_k: int = 5) -> List[Dict]:
    """
    Parse chunks using Groq LLM based on provided prompts.
    """
    with open(prompts_path, "r", encoding="utf-8") as f:
        prompts = json.load(f)

    results = []

    for p in prompts:
        run_for = p.get("run_for", "both").lower()
        relevant_chunks = (
            [c for c in chunks if c.get("source") == "framework"] if run_for == "framework"
            else [c for c in chunks if c.get("source") == "spo"] if run_for == "spo"
            else chunks
        )

        index = build_tfidf_index(relevant_chunks)
        query = p.get("instruction") or p.get("query") or ""
        top_idx = retrieve_top_k(query, index, k=top_k)
        context = assemble_context(relevant_chunks, top_idx)

        system_msg = {
            "role": "system",
            "content": (
                "You are a JSON extraction assistant. Use ONLY the provided CONTEXT to answer. "
                "Output must be valid JSON and must match the provided schema or example. "
                "If a field cannot be found in the context, set it to null or an empty string."
            )
        }

        user_content = (
            f"CONTEXT:\n\n{context}\n\n"
            f"INSTRUCTION:\n\n{p['instruction']}\n\n"
            f"OUTPUT_SCHEMA / EXAMPLE:\n\n{json.dumps(p['json_schema'], indent=2)}\n\n"
            "Return ONLY the JSON (no extra commentary)."
        )
        user_msg = {"role": "user", "content": user_content}

        resp = call_groq(model=groq_model, messages=[system_msg, user_msg], temperature=0.0)

        try:
            content = resp.choices[0].message.content
        except Exception:
            content = str(resp)

        try:
            parsed = json.loads(content)
        except Exception:
            m = re.search(r'(\{.*\}|\[.*\])', content, flags=re.S)
            if m:
                try:
                    parsed = json.loads(m.group(1))
                except Exception:
                    parsed = {"_raw": content}
            else:
                parsed = {"_raw": content}

        results.append({
            "prompt_id": p.get("id"),
            "run_for": run_for,
            "result": parsed,
            "used_context_indices": top_idx,
            "raw_model_output": content
        })

    return results


# ---------------- Gemini Parsing ---------------- #

def call_gemini(model_gemini: str, messages: List[Dict], temperature: float = 0.0, max_retries: int = 3) -> Dict:
    """
    Call Gemini chat model with retries.
    """
    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        raise EnvironmentError("GEMINI_API_KEY not set in environment.")

    client = genai.Client(api_key=api_key)

    for attempt in range(1, max_retries + 1):
        try:
            user_messages = [m["content"] for m in messages if m["role"] == "user"]
            system_messages = [m["content"] for m in messages if m["role"] == "system"]

            response = client.models.generate_content(
                model=model_gemini,
                contents=user_messages,
                config=types.GenerateContentConfig(
                    system_instruction=system_messages,
                    temperature=temperature
                )
            )
            return response
        except Exception:
            if attempt == max_retries:
                raise
            time.sleep(1.0 * attempt)


def parse_with_llm_gemini(chunks: List[Dict], prompts_path: str, gemini_model: str, top_k: int = 5) -> List[Dict]:
    """
    Parse chunks using Gemini LLM based on provided prompts.
    """
    with open(prompts_path, "r", encoding="utf-8") as f:
        prompts = json.load(f)

    results = []

    for p in prompts:
        run_for = p.get("run_for", "both").lower()
        relevant_chunks = (
            [c for c in chunks if c.get("source") == "framework"] if run_for == "framework"
            else [c for c in chunks if c.get("source") == "spo"] if run_for == "spo"
            else chunks
        )

        index = build_tfidf_index(relevant_chunks)
        query = p.get("instruction") or p.get("query") or ""
        top_idx = retrieve_top_k(query, index, k=top_k)
        context = assemble_context(relevant_chunks, top_idx)

        system_msg = {
            "role": "system",
            "content": (
                "You are a JSON extraction assistant. Use ONLY the provided CONTEXT to answer. "
                "Output must be valid JSON and must match the provided schema or example. "
                "If a field cannot be found in the context, set it to null or an empty string."
            )
        }

        user_content = (
            f"CONTEXT:\n\n{context}\n\n"
            f"INSTRUCTION:\n\n{p['instruction']}\n\n"
            f"OUTPUT_SCHEMA / EXAMPLE:\n\n{json.dumps(p['json_schema'], indent=2)}\n\n"
            "Return ONLY the JSON (no extra commentary)."
        )
        user_msg = {"role": "user", "content": user_content}

        resp = call_gemini(model_gemini=gemini_model, messages=[system_msg, user_msg], temperature=0.0)

        print(getattr(resp, 'usage_metadata', None))

        try:
            content = resp.text
        except Exception:
            content = str(resp)

        try:
            parsed = json.loads(content)
        except Exception:
            m = re.search(r'(\{.*\}|\[.*\])', content, flags=re.S)
            if m:
                try:
                    parsed = json.loads(m.group(1))
                except Exception:
                    parsed = {"_raw": content}
            else:
                parsed = {"_raw": content}

        results.append({
            "prompt_id": p.get("id"),
            "run_for": run_for,
            "result": parsed,
            "used_context_indices": top_idx,
            "raw_model_output": content
        })

    return results

# ---------------- OpenAI Parsing ---------------- #

def call_openai(model: str, messages: List[Dict], temperature: float = 0.0, max_retries: int = 3) -> Dict:
    """
    Call OpenAI chat model with retries.

    Args:
        model (str): OpenAI model name.
        messages (List[Dict]): List of messages with "role" and "content".
        temperature (float): Sampling temperature.
        max_retries (int): Number of retry attempts if call fails.

    Returns:
        Dict: Raw response from OpenAI API.
    """
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        raise EnvironmentError("OPENAI_API_KEY not set in environment.")
    
    client = OpenAI(api_key=api_key)

    for attempt in range(1, max_retries + 1):
        try:
            response = client.chat.completions.create(
                model=model,
                messages=messages,
                temperature=temperature
            )
            return response
        except Exception as e:
            if attempt == max_retries:
                raise
            time.sleep(1.0 * attempt)


def parse_with_llm_openai(chunks: List[Dict], prompts_path: str, openai_model: str, top_k: int = 5) -> List[Dict]:
    """
    Parse chunks using OpenAI LLM based on provided prompts.
    """
    with open(prompts_path, "r", encoding="utf-8") as f:
        prompts = json.load(f)

    results = []

    for p in prompts:
        run_for = p.get("run_for", "both").lower()
        relevant_chunks = (
            [c for c in chunks if c.get("source") == "framework"] if run_for == "framework"
            else [c for c in chunks if c.get("source") == "spo"] if run_for == "spo"
            else chunks
        )

        index = build_tfidf_index(relevant_chunks)
        query = p.get("instruction") or p.get("query") or ""
        top_idx = retrieve_top_k(query, index, k=top_k)
        context = assemble_context(relevant_chunks, top_idx)

        system_msg = {
            "role": "system",
            "content": (
                "You are a JSON extraction assistant. Use ONLY the provided CONTEXT to answer. "
                "Output must be valid JSON and must match the provided schema or example. "
                "If a field cannot be found in the context, set it to null or an empty string."
            )
        }

        user_content = (
            f"CONTEXT:\n\n{context}\n\n"
            f"INSTRUCTION:\n\n{p['instruction']}\n\n"
            f"OUTPUT_SCHEMA / EXAMPLE:\n\n{json.dumps(p['json_schema'], indent=2)}\n\n"
            "Return ONLY the JSON (no extra commentary)."
        )
        user_msg = {"role": "user", "content": user_content}

        resp = call_openai(model=openai_model, messages=[system_msg, user_msg], temperature=0.0)

        try:
            content = resp.choices[0].message.content
        except Exception:
            content = str(resp)

        try:
            parsed = json.loads(content)
        except Exception:
            m = re.search(r'(\{.*\}|\[.*\])', content, flags=re.S)
            if m:
                try:
                    parsed = json.loads(m.group(1))
                except Exception:
                    parsed = {"_raw": content}
            else:
                parsed = {"_raw": content}

        results.append({
            "prompt_id": p.get("id"),
            "run_for": run_for,
            "result": parsed,
            "used_context_indices": top_idx,
            "raw_model_output": content
        })

    return results