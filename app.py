import streamlit as st
import os
import tempfile
import time
from difflib import SequenceMatcher
from pathlib import Path

# Import your existing modules
import config
from extractor import extract_chunks_from_two_pdfs
from parser import parse_with_llm_openai
from writer import write_to_excel
from table_extractor import write_temp_merged_pdf, call_whisperer_and_get_text
from table_parser import parser_for_table
from table_writer import writer_to_excel_table

# --- Page Config ---
st.set_page_config(page_title="SPO Framework Extractor", layout="wide")

st.title("📄 SPO Framework & Table Extractor (Batch Mode)")
st.markdown("Upload multiple PDFs. The app will automatically pair **Frameworks** with **SPOs** based on filenames and process them into a single report.")

# --- Sidebar: Configuration ---
with st.sidebar:
    st.header("Configuration")
    
    openai_api_key = st.text_input("OpenAI API Key", type="password", value=os.getenv("OPENAI_API_KEY", ""))
    whisperer_api_key = st.text_input("LLMWhisperer API Key", type="password", value=os.getenv("LLMWHISPERER_API_KEY", ""))
    
    st.divider()
    
    openai_model = st.selectbox("OpenAI Model", ["gpt-4o", "gpt-4o-mini", "gpt-4-turbo"], index=1)
    
    # Update Config globals
    config.OPENAI_MODEL = openai_model
    if openai_api_key:
        os.environ["OPENAI_API_KEY"] = openai_api_key
    if whisperer_api_key:
        os.environ["LLMWHISPERER_API_KEY"] = whisperer_api_key

# --- Helper: Smart Pairing ---
def match_pairs(file_list):
    """
    Groups uploaded files into (Framework, SPO) pairs based on filename similarity.
    Returns: 
        pairs: List of dicts {'framework': file, 'spo': file, 'name': str}
        unmatched: List of files that couldn't be paired
    """
    frameworks = []
    spos = []
    others = []

    # 1. Bucket files
    for f in file_list:
        fname = f.name.lower()
        if "framework" in fname and not any(x in fname for x in ["spo", "second", "opinion"]):
            frameworks.append(f)
        elif any(x in fname for x in ["spo", "second", "opinion"]):
            spos.append(f)
        else:
            others.append(f)

    pairs = []
    used_spos = set()

    # 2. Match Frameworks to nearest SPO
    for fw in frameworks:
        best_match = None
        best_score = 0.0
        fw_name = fw.name.lower()

        for spo in spos:
            if spo in used_spos:
                continue
            
            # Simple similarity ratio
            score = SequenceMatcher(None, fw_name, spo.name.lower()).ratio()
            
            # Boost score if they share a prefix (e.g. "Tesla_Framework" vs "Tesla_SPO")
            common_prefix_len = 0
            for c1, c2 in zip(fw_name, spo.name.lower()):
                if c1 == c2: common_prefix_len += 1
                else: break
            
            if common_prefix_len > 3:
                score += 0.5

            if score > best_score:
                best_score = score
                best_match = spo

        if best_match and best_score > 0.4:  # Threshold to avoid bad matches
            used_spos.add(best_match)
            # Create a display name based on the common prefix
            pairs.append({
                "name": os.path.commonprefix([fw.name, best_match.name]).strip("-_ "),
                "framework": fw,
                "spo": best_match
            })
        else:
            others.append(fw)

    # Add remaining unmatched SPOs to others
    for spo in spos:
        if spo not in used_spos:
            others.append(spo)

    return pairs, others

# --- Main UI ---
uploaded_files = st.file_uploader(
    "Upload multiple PDF files (Frameworks and SPOs)", 
    type=["pdf"], 
    accept_multiple_files=True
)

if uploaded_files:
    pairs, unmatched = match_pairs(uploaded_files)
    
    st.subheader(f"Found {len(pairs)} Pair(s)")
    
    # Display the pairs found
    for p in pairs:
        with st.expander(f"📁 Pair: {p['name'] or 'Unnamed Group'}", expanded=True):
            st.text(f"Framework: {p['framework'].name}")
            st.text(f"SPO:       {p['spo'].name}")

    if unmatched:
        st.warning(f"⚠️ Could not pair {len(unmatched)} file(s): {', '.join([f.name for f in unmatched])}")

    # Button to start processing
    if st.button("Run Extraction Batch"):
        if not openai_api_key or not whisperer_api_key:
            st.error("Please provide API Keys in the sidebar.")
        elif not pairs:
            st.error("No valid Framework-SPO pairs found.")
        else:
            # Create a temporary directory for the whole batch
            with tempfile.TemporaryDirectory() as temp_dir:
                excel_output_path = os.path.join(temp_dir, "SPO_Batch_Output.xlsx")
                config.EXCEL_FILE = excel_output_path
                
                # Progress bar for the whole batch
                main_progress = st.progress(0)
                status_text = st.empty()

                for idx, p in enumerate(pairs):
                    pair_name = p['name'] or f"Pair {idx+1}"
                    status_text.markdown(f"### Processing: **{pair_name}** ({idx+1}/{len(pairs)})")
                    
                    fw_file = p['framework']
                    spo_file = p['spo']
                    
                    # Save files to temp
                    fw_path = os.path.join(temp_dir, fw_file.name)
                    spo_path = os.path.join(temp_dir, spo_file.name)
                    
                    with open(fw_path, "wb") as f: f.write(fw_file.getbuffer())
                    with open(spo_path, "wb") as f: f.write(spo_file.getbuffer())

                    # --- PHASE 1: Textual Pipeline ---
                    try:
                        chunks = extract_chunks_from_two_pdfs(
                            fw_path, spo_path, 
                            chunk_size=config.CHUNK_SIZE, 
                            overlap=config.OVERLAP, 
                            folder_name=pair_name
                        )
                        
                        results = parse_with_llm_openai(
                            chunks, 
                            config.PROMPTS_FILE, 
                            openai_model=config.OPENAI_MODEL, 
                            top_k=config.TOP_K
                        )
                        
                        for r in results:
                            run_for = r.get("run_for")
                            json_result = r.get("result", {})
                            if run_for and isinstance(json_result, dict):
                                # Pass file_path explicitly!
                                write_to_excel(json_result, run_for=run_for, file_path=excel_output_path)
                                
                    except Exception as e:
                        st.error(f"❌ Text Error in {pair_name}: {e}")

                    # --- PHASE 2: Table Pipeline ---
                    try:
                        merged_tmp_path = write_temp_merged_pdf(fw_path, spo_path)
                        
                        if merged_tmp_path:
                            extracted_text = call_whisperer_and_get_text(merged_tmp_path)
                            parsed_dict = parser_for_table(extracted_text, config.PROMPTS_TABLE)
                            writer_to_excel_table(parsed_dict, excel_output_path)
                            
                            if os.path.exists(merged_tmp_path):
                                os.remove(merged_tmp_path)
                    except Exception as e:
                        st.error(f"❌ Table Error in {pair_name}: {e}")

                    # Update progress
                    main_progress.progress((idx + 1) / len(pairs))

                st.success("✅ Batch Processing Complete!")
                
                # Download Button
                if os.path.exists(excel_output_path):
                    with open(excel_output_path, "rb") as f:
                        file_data = f.read()
                    
                    st.download_button(
                        label="📥 Download Co   nsolidated Excel Report",
                        data=file_data,
                        file_name="SPO_Batch_Analysis.xlsx",
                        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
                    )