"""
table_extractor.py

Extracts table data from SPO and framework PDFs per company:
- Detects framework and SPO PDFs in each company folder
- Identifies pages containing tables using pdfplumber
- Merges relevant pages into a temporary PDF
- Sends the merged PDF to LLM Whisperer for extraction
- Returns the extracted text per company
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

from config import MAIN_FOLDER , WHISPERER_BASE

# ---------- Configuration ----------
ROOT_FOLDER = MAIN_FOLDER
WHISPERER_BASE = WHISPERER_BASE
WHISPERER_API_KEY = os.getenv("LLMWHISPERER_API_KEY")
# -----------------------------------



def find_framework_and_spo_pdfs(folder_path):
    """
    Return the framework and SPO PDF paths from a given folder.

    Args:
        folder_path (str): Path to the company's folder.

    Returns:
        Tuple[str | None, str | None]: (framework_pdf_path, spo_pdf_path). None if not found.
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




def get_pages_with_tables_pdfplumber(pdf_path):
    """
    Return the 0-based page indices of a PDF that contain tables.

    Args:
        pdf_path (str): Path to the PDF file.

    Returns:
        List[int]: List of page indices containing tables.
    """
    pages_with_tables = []
    with pdfplumber.open(pdf_path) as pdf:
        for i, page in enumerate(pdf.pages):
            tables = page.find_tables()
            if tables and len(tables) > 0:
                pages_with_tables.append(i)
    return pages_with_tables


def assemble_pages_with_pypdf(src_pdf_path, page_indices, writer=None):
    """
    Add selected pages from a source PDF to a PdfWriter object.

    Args:
        src_pdf_path (str): Path to the source PDF.
        page_indices (List[int]): List of 0-based page indices to add.
        writer (PdfWriter, optional): Existing PdfWriter object. Creates new if None.

    Returns:
        PdfWriter: Updated PdfWriter object containing selected pages.
    """
    reader = PdfReader(src_pdf_path)
    if writer is None:
        writer = PdfWriter()
    for idx in page_indices:
        if 0 <= idx < len(reader.pages):
            writer.add_page(reader.pages[idx])
    return writer


def create_label_page_bytes(text):
    """
    Create a single-page PDF as bytes containing a centered label text.

    Args:
        text (str): Label text to place on the PDF page.

    Returns:
        bytes: PDF file content in bytes.
    """
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
    """
    Create a temporary merged PDF containing only pages with tables from framework and SPO PDFs.

    Args:
        framework_pdf (str | None): Path to the framework PDF.
        spo_pdf (str | None): Path to the SPO PDF.
        tmp_suffix (str): Suffix for the temporary file (default ".pdf").

    Returns:
        str | None: Path to the temporary merged PDF, or None if no pages were added.
    """
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
    """
    Send a PDF to LLM Whisperer and return the extracted text.

    Args:
        merged_pdf_path (str): Path to the merged PDF.

    Returns:
        str: Extracted text from the PDF.

    Raises:
        RuntimeError: If Whisperer does not return a valid whisper_hash.
    """
    client = LLMWhispererClientV2(base_url=WHISPERER_BASE, api_key=WHISPERER_API_KEY)
    result = client.whisper(
        file_path=merged_pdf_path,
        mode = "low_cost",
        output_mode = "layout_preserving"
        )
    whisper_hash = result.get("whisper_hash")
    if not whisper_hash:
        raise RuntimeError("Whisperer did not return a whisper_hash.")

    while True:
        status = client.whisper_status(whisper_hash=whisper_hash)
        if status.get("status") == "processed":
            retrieved = client.whisper_retrieve(whisper_hash=whisper_hash)
            break
        time.sleep(5)

    return retrieved["extraction"]["result_text"]

def process_subfolders_in_memory(root_folder):
    """
    Process company subfolders sequentially (memory-efficient version):
    - Finds framework and SPO PDFs in each subfolder.
    - Extracts table pages and merges into a temporary PDF.
    - Sends the merged PDF to LLM Whisperer for text extraction.
    - Yields company name and extracted text one by one.

    Args:
        root_folder (str): Path to the root folder containing company subfolders.

    Yields:
        Tuple[str, str]: (company_name, extracted_text)
    """

    for sub in sorted(os.listdir(root_folder)):
        sub_path = os.path.join(root_folder, sub)
        if not os.path.isdir(sub_path):
            continue

        print(f"\nProcessing company: {sub}")
        framework_pdf, spo_pdf = find_framework_and_spo_pdfs(sub_path)
        if not framework_pdf or not spo_pdf:
            print("  ⚠️ Missing framework or SPO PDF. Skipping.")
            continue

        merged_tmp_path = write_temp_merged_pdf(framework_pdf, spo_pdf)
        if merged_tmp_path is None:
            print("  ⚠️ No table pages found; skipping this company.")
            continue

        try:
            extracted_text = call_whisperer_and_get_text(merged_tmp_path)
            print(f"✅ Extracted text for {sub}")
            yield sub, extracted_text  # <-- yields one company at a time

        except Exception as e:
            print(f"❌ Error extracting text for {sub}: {e}")

        finally:
            if os.path.exists(merged_tmp_path):
                os.remove(merged_tmp_path)
                print("    Temporary merged PDF deleted.")
