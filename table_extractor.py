"""
table_extractor.py
"""

import os
import io
import time
import tempfile
import pdfplumber

from pypdf import PdfReader, PdfWriter
from unstract.llmwhisperer import LLMWhispererClientV2

from dotenv import load_dotenv
load_dotenv()

from config import MAIN_FOLDER, WHISPERER_BASE

# ---------- Configuration ----------
ROOT_FOLDER = MAIN_FOLDER
WHISPERER_BASE = WHISPERER_BASE
# REMOVED: WHISPERER_API_KEY = os.getenv("LLMWHISPERER_API_KEY")  <-- CAUSES ERROR
# -----------------------------------

def find_framework_and_spo_pdfs(folder_path):
    files = os.listdir(folder_path)
    framework = None
    spo = None

    for f in files:
        lf = f.lower()
        if lf.endswith(".pdf"):
            if "framework" in lf and not any(word in lf for word in ["spo", "second", "second-party-opinion"]):
                framework = os.path.join(folder_path, f)
            elif any(word in lf for word in ["spo", "spoc", "second", "second-party-opinion"]):
                spo = os.path.join(folder_path, f)

    pdfs = [os.path.join(folder_path, f) for f in files if f.lower().endswith(".pdf")]
    if not (framework and spo) and len(pdfs) == 2:
        framework, spo = pdfs[0], pdfs[1]

    return framework, spo


def get_pages_with_tables_pdfplumber(pdf_path):
    pages_with_tables = []
    with pdfplumber.open(pdf_path) as pdf:
        for i, page in enumerate(pdf.pages):
            tables = page.find_tables()
            if tables and len(tables) > 0:
                pages_with_tables.append(i)
    return pages_with_tables


def assemble_pages_with_pypdf(src_pdf_path, page_indices, writer=None):
    reader = PdfReader(src_pdf_path)
    if writer is None:
        writer = PdfWriter()
    for idx in page_indices:
        if 0 <= idx < len(reader.pages):
            writer.add_page(reader.pages[idx])
    return writer


def create_label_page_bytes(text):
    from reportlab.pdfgen import canvas
    from reportlab.lib.pagesizes import A4

    buffer = io.BytesIO()
    c = canvas.Canvas(buffer, pagesize=A4)
    width, height = A4
    c.setFont("Helvetica-Bold", 20)
    c.drawCentredString(width / 2, height / 2, text)
    c.showPage()
    c.save()
    buffer.seek(0)
    return buffer.read()


def write_temp_merged_pdf(framework_pdf, spo_pdf, tmp_suffix=".pdf"):
    fw_pages = get_pages_with_tables_pdfplumber(framework_pdf) if framework_pdf else []
    spo_pages = get_pages_with_tables_pdfplumber(spo_pdf) if spo_pdf else []

    print(f"  -> Framework pages with tables: {fw_pages}")
    print(f"  -> SPO pages with tables: {spo_pages}")

    writer = PdfWriter()

    if fw_pages:
        label_bytes = create_label_page_bytes("Framework PDF")
        label_reader = PdfReader(io.BytesIO(label_bytes))
        writer.add_page(label_reader.pages[0])
        writer = assemble_pages_with_pypdf(framework_pdf, fw_pages, writer=writer)

    if spo_pages:
        label_bytes = create_label_page_bytes("Second Party Opinion / SPO")
        label_reader = PdfReader(io.BytesIO(label_bytes))
        writer.add_page(label_reader.pages[0])
        writer = assemble_pages_with_pypdf(spo_pdf, spo_pages, writer=writer)

    if len(writer.pages) == 0:
        print("    No pages added to merged PDF (no tables).")
        return None

    tmp = tempfile.NamedTemporaryFile(delete=False, suffix=tmp_suffix)
    tmp_path = tmp.name
    try:
        with open(tmp_path, "wb") as f:
            writer.write(f)
    finally:
        tmp.close()

    print(f"    Temporary merged PDF written to: {tmp_path}")
    return tmp_path


def call_whisperer_and_get_text(merged_pdf_path):
    # FIX: Fetch API Key right here, right now
    api_key = os.getenv("LLMWHISPERER_API_KEY")
    
    if not api_key:
        raise ValueError("LLMWHISPERER_API_KEY is missing. Please enter it in the sidebar.")

    client = LLMWhispererClientV2(base_url=WHISPERER_BASE, api_key=api_key)
    
    result = client.whisper(
        file_path=merged_pdf_path,
        mode="low_cost",
        output_mode="layout_preserving"
    )
    whisper_hash = result.get("whisper_hash")
    if not whisper_hash:
        raise RuntimeError("Whisperer did not return a whisper_hash.")

    while True:
        status = client.whisper_status(whisper_hash=whisper_hash)
        if status.get("status") == "processed":
            retrieved = client.whisper_retrieve(whisper_hash=whisper_hash)
            break
        elif status.get("status") == "processing_failed":
             raise RuntimeError("LLMWhisperer processing failed on server side.")
        time.sleep(5)

    return retrieved["extraction"]["result_text"]