"""
Configuration file for the SPO Framework project.

Contains constants used across the project, including file paths,
model names, and parameters for text chunking and retrieval.
"""

# Path to the Excel file where data is stored
EXCEL_FILE = "Output.xlsx"
# Folder containing all main framework files
MAIN_FOLDER = "Main_spo_framework"

# LLM model names
GROQ_MODEL = "llama-3.3-70b-versatile"
GEMINI_MODEL = "gemini-2.5-flash"
OPENAI_MODEL = "gpt-4.1-mini"

#Contains the Prompts FIle
PROMPTS_FILE = "Prompts/prompts_spo_framework.json"
PROMPTS_TABLE = "Prompts/prompts_table.json"

#Whisper Base
WHISPERER_BASE = "https://llmwhisperer-api.us-central.unstract.com/api/v2"

# Retrieval parameters
TOP_K = 6          # Number of top results to retrieve
CHUNK_SIZE = 2000  # Size of text chunks for processing
OVERLAP = 200      # Overlap between consecutive chunks
