"""
main.py

This is the main pipeline file for the SPO-Framework-Extractor project. 

It orchestrates the processing of PDFs in the 'Main_framework' folder by:
1. Identifying framework and SPO PDF pairs in each subfolder.
2. Extracting text chunks from the PDFs using `extractor.py`.
3. Parsing the chunks with LLMs using `parser.py`.
4. Writing structured output to Excel using `writer.py`.

Additionally, it handles the tabular pipeline:
1. Extract tables from PDFs using `table_extractor.py`.
2. Parse tables using `table_parser.py`.
3. Write tabular output to Excel using `table_writer.py`.

Functions:
- find_pdf_pair(folder_path: str) -> Tuple[str, str]: Identifies framework and SPO PDFs in a folder.
- main(): Runs the textual data pipeline for all subfolders.
- main_table(): Runs the tabular data pipeline for all subfolders.
"""

import os
import re
import json
import time

from extractor import extract_chunks_from_two_pdfs
from parser import parse_with_llm_groq #for Groq
from parser import parse_with_llm_gemini #for Gemini
from parser import parse_with_llm_openai #for OpenAI
from writer import write_to_excel   

from table_extractor import process_subfolders_in_memory
from table_parser import parser_for_table #Currently Using OpenAI Parsing
from table_writer import writer_to_excel_table

from config import EXCEL_FILE, MAIN_FOLDER, GROQ_MODEL, GEMINI_MODEL, OPENAI_MODEL
from config import TOP_K, CHUNK_SIZE, OVERLAP , PROMPTS_FILE , PROMPTS_TABLE




def find_pdf_pair(folder_path: str):
    """
    Identify and return the framework and SPO PDF pair in a folder.

    Framework PDF:
        - Must contain 'framework' but NOT 'spo', 'second', or 'second-party-opinion'.
    SPO PDF:
        - Must contain 'spo', 'spoc', 'second', or 'second-party-opinion'.

    If the folder contains exactly two PDFs and no strict match is found, the two PDFs
    are assumed to be the framework and SPO pair.

    Args:
        folder_path (str): Path to the folder containing PDF files.

    Returns:
        Tuple[str, str]: Paths to the framework PDF and SPO PDF respectively.
                         Returns (None, None) if no valid pair is found.
    """
    files = os.listdir(folder_path)
    framework = None
    spo = None

    for f in files:
        lf = f.lower()
        if lf.endswith(".pdf"):
            # Strict framework condition
            if "framework" in lf and not any(word in lf for word in ["spo", "second", "second-party-opinion"]):
                framework = os.path.join(folder_path, f)
            # SPO detection
            elif any(word in lf for word in ["spo", "spoc", "second", "second-party-opinion"]):
                spo = os.path.join(folder_path, f)

    # Fallback: if exactly two PDFs exist, assume they're a pair
    pdfs = [os.path.join(folder_path, f) for f in files if f.lower().endswith(".pdf")]
    if not (framework and spo) and len(pdfs) == 2:
        framework, spo = pdfs[0], pdfs[1]

    return framework, spo



def main():
    """
    Run the textual data pipeline for all subfolders in MAIN_FOLDER.

    Workflow:
    1. Iterate over subfolders.
    2. Find framework and SPO PDF pair.
    3. Extract text chunks using extractor.
    4. Parse chunks using LLM (Gemini or Groq).
    5. Write structured results to Excel immediately.
    """

    for sub in sorted(os.listdir(MAIN_FOLDER)):
        subp = os.path.join(MAIN_FOLDER, sub)
        if not os.path.isdir(subp):
            continue
        print(f"Processing folder: {subp}")
        framework, spo = find_pdf_pair(subp)
        if not framework or not spo:
            print(f"  Skipping {sub}: could not find a pair of PDFs (framework & spo).")
            continue

        chunks = extract_chunks_from_two_pdfs(framework, spo,chunk_size=CHUNK_SIZE, overlap=OVERLAP,folder_name=sub)

        #Use this if you want to use Groq model
        #results = parse_with_llm_groq(chunks, PROMPTS_FILE, groq_model=GROQ_MODEL, top_k=TOP_K)
        
        #Use this if you want to use OpenAI model
        results = parse_with_llm_openai(chunks, PROMPTS_FILE, openai_model= OPENAI_MODEL, top_k = TOP_K)

        # # Use this if you want to use Gemini model
        # results = parse_with_llm_gemini(chunks,PROMPTS_FILE,gemini_model=GEMINI_MODEL,top_k=TOP_K)

        # Write each result immediately into Excel
        for r in results:
            run_for = r.get("run_for")
            json_result = r.get("result", {})
            if run_for and isinstance(json_result, dict):
                write_to_excel(json_result, run_for=run_for)
                
    
def main_table():
    """
    Run the tabular data pipeline sequentially for each subfolder in MAIN_FOLDER.

    Workflow:
    1. Extract tables (via process_subfolders_in_memory, now yields results per company).
    2. Parse tables using table_parser.
    3. Write parsed data into Excel via table_writer.
    """

    for company, text in process_subfolders_in_memory(MAIN_FOLDER):
        try:
            parsed_dict = parser_for_table(text, PROMPTS_TABLE)
            writer_to_excel_table(parsed_dict, EXCEL_FILE)
            print(f"✅ Completed pipeline for {company}\n")
        except Exception as e:
            print(f"❌ Error processing {company}: {e}")
            continue


if __name__ == "__main__":
    start_time = time.time()    
    main()
    main_table()
    print("Processing completed :)")
    end_time = time.time()
    print("Total execution time:", end_time - start_time, "seconds")
    
