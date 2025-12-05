"""
extractor.py

This module provides utilities to extract and chunk textual data from PDF files,
specifically designed for SPO and Framework PDFs in the SPO-Framework-Extractor pipeline.

Functions:
- extract_text_from_pdf(pdf_path: str) -> List[str]
    Extracts raw text from each page of a PDF and returns a list of page texts.

- chunk_text(text: str, chunk_size: int = 2000, overlap: int = 200) -> List[str]
    Splits a single string into overlapping text chunks of specified size.

- extract_chunks_from_two_pdfs(framework_pdf: str, spo_pdf: str, chunk_size: int = 500, 
                               overlap: int = 200, folder_name: str = None) -> List[Dict]
    Extracts and chunks text from two PDFs (framework and SPO) and returns a list
    of dictionaries containing chunk data, source, page number, chunk index, and folder.
"""

import pdfplumber
from typing import List, Dict

def extract_text_from_pdf(path: str) -> List[str]:
    """
    Extract text from a PDF file.

    Args:
        path (str): Path to the PDF file.

    Returns:
        List[str]: List of strings, one per page. Index 0 corresponds to page 1.
                   If a page has no text, returns an empty string for that page.
    """
    pages = []
    with pdfplumber.open(path) as pdf:
        for p in pdf.pages:
            text = p.extract_text() or ""
            pages.append(text)
    return pages


def chunk_text(text: str, chunk_size: int = 2000, overlap: int = 200) -> List[str]:
    """
    Split a string into overlapping text chunks.

    Args:
        text (str): Input text to be chunked.
        chunk_size (int): Maximum number of characters per chunk. Default is 2000.
        overlap (int): Number of characters to overlap between consecutive chunks. Default is 200.

    Returns:
        List[str]: List of text chunks. Returns an empty list if text is empty.
    """
    if not text:
        return []
    chunks = []
    step = chunk_size - overlap
    i = 0
    while i < len(text):
        chunk = text[i:i + chunk_size]
        chunks.append(chunk.strip())
        i += step
    return chunks


def extract_chunks_from_two_pdfs(
    framework_pdf: str,
    spo_pdf: str,
    chunk_size: int = 500,
    overlap: int = 200,
    folder_name: str = None
) -> List[Dict]:
    """
    Extract text from two PDFs (framework and SPO), chunk each page, and return structured chunks.

    Args:
        framework_pdf (str): Path to the framework PDF.
        spo_pdf (str): Path to the SPO PDF.
        chunk_size (int): Maximum characters per chunk. Default is 500.
        overlap (int): Number of overlapping characters between chunks. Default is 200.
        folder_name (str, optional): Name of the folder/company associated with these PDFs.

    Returns:
        List[Dict]: A list of dictionaries, each representing a chunk:
            {
                "chunk": str,          # Chunk text
                "source": str,         # "framework" or "spo"
                "page": int,           # Page number (1-indexed)
                "chunk_index": int,    # Index of chunk on this page (1-indexed)
                "folder": str or None  # Folder/company name
            }
    """
    all_chunks = []

    for path, source in [(framework_pdf, "framework"), (spo_pdf, "spo")]:
        pages = extract_text_from_pdf(path)
        for idx, page_text in enumerate(pages, start=1):
            page_chunks = chunk_text(page_text, chunk_size=chunk_size, overlap=overlap)
            for c_idx, chunk in enumerate(page_chunks, start=1):
                all_chunks.append({
                    "chunk": chunk,
                    "source": source,
                    "page": idx,
                    "chunk_index": c_idx,
                    "folder": folder_name
                })

    return all_chunks
