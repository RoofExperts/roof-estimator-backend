import os
import re
import json
import pdfplumber
from openai import OpenAI


# ==========================================================
# PDF TEXT EXTRACTION
# ==========================================================
def extract_text_from_pdf(file_path: str) -> str:
    full_text = ""

    with pdfplumber.open(file_path) as pdf:
        for page in pdf.pages:
            text = page.extract_text()
            if text:
                full_text += text + "\n"

    return full_text


# ==========================================================
# ISOLATE CSI DIVISION 07
# ==========================================================
def isolate_division_7(text: str) -> str | None:
    text_upper = text.upper()

    start_match = re.search(r"DIVISION\s*0?7", text_upper)
    if not start_match:
        return None

    start_index = start_match.start()

    # Find next division (usually 08)
    end_match = re.search(r"DIVISION\s*0?8", text_upper[start_index:])

    if end_match:
        end_index = start_index + end_match.start()
        return text[start_index:end_index]
    else:
        return text[start_index:]


# ==========================================================
# AI ANALYSIS
# ==========================================================
def analyze_spec_text(text: str):

    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        return {"error": "OPENAI_API_KEY not configured"}

    client = OpenAI(api_key=api_key)

    division_7_text = isolate_division_7(text)

    if not division_7_text:
        return {"error": "Division 07 not found in spec"}

    # Prevent timeout / memory spikes
    MAX_CHARS = 8000
    division_7_text = division_7_text[:MAX_CHARS]

    prompt = f"""
You are a professional commercial roofing estimator.

Analyze this CSI Division 07 roofing specification.

Return STRICT VALID JSON ONLY.
Do not use markdown.
Do not use backticks.
Do not explain anything.

Format exactly like this:

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

If a value is not specified, return null.

Specification Text:
----------------------
{division_7_text}
"""

    response = client.chat.completions.create(
        model="gpt-4o-mini",
        temperature=0,
        max_tokens=600,
        messages=[
            {"role": "system", "content": "You extract structured roofing data from CSI specs."},
            {"role": "user", "content": prompt}
        ]
    )

    raw = response.choices[0].message.content.strip()

    # Remove accidental markdown formatting
    raw = re.sub(r"```json", "", raw)
    raw = re.sub(r"```", "", raw).strip()

    try:
        parsed = json.loads(raw)
        return parsed
    except Exception:
        return {
            "error": "AI returned invalid JSON",
            "raw_response": raw
        }
