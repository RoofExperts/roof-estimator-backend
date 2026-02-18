import re
import os
from openai import OpenAI
import pdfplumber

# =============================
# PDF TEXT EXTRACTION
# =============================
def extract_text_from_pdf(file_path: str) -> str:
    full_text = ""

    with pdfplumber.open(file_path) as pdf:
        for page in pdf.pages:
            text = page.extract_text()
            if text:
                full_text += text + "\n"

    return full_text


# =============================
# CSI DIVISION 07 ISOLATION
# =============================
def isolate_division_7(text: str) -> str:
    """
    Extracts CSI Division 07 section from full spec text.
    """

    # Normalize text
    text_upper = text.upper()

    # Find start of Division 07
    start_match = re.search(r"DIVISION\s*07", text_upper)
    if not start_match:
        return None

    start_index = start_match.start()

    # Find next division after 07 (usually 08)
    end_match = re.search(r"DIVISION\s*0?8", text_upper[start_index:])
    
    if end_match:
        end_index = start_index + end_match.start()
        return text[start_index:end_index]
    else:
        # If no Division 08 found, return remainder
        return text[start_index:]


# =============================
# AI ANALYSIS
# =============================
def analyze_spec_text(text: str):
    """
    Sends Division 07 only to AI for structured extraction.
    """

    client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

    division_7_text = isolate_division_7(text)

    if not division_7_text:
        return {"error": "Division 07 not found in spec"}

    prompt = f"""
You are a professional commercial roofing estimator.

Analyze the following CSI Division 07 roofing specification.

Extract ONLY roofing-related information.

Return STRICT JSON in this format:

{{
  "roof_system_type": "",
  "membrane_type": "",
  "membrane_thickness": "",
  "attachment_method": "",
  "insulation_type": "",
  "insulation_layers": "",
  "cover_board": "",
  "fastening_pattern": "",
  "warranty_years": "",
  "manufacturer": "",
  "special_requirements": ""
}}

If information is not clearly specified, return null.

Specification Text:
----------------------
{division_7_text}
"""

    response = client.chat.completions.create(
        model="gpt-4o-mini",
        temperature=0,
        messages=[
            {"role": "system", "content": "You extract structured roofing data from CSI specs."},
            {"role": "user", "content": prompt}
        ]
    )

    return response.choices[0].message.content
