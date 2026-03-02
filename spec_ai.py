import os
import re
import json
import gc
import pdfplumber
from openai import OpenAI


# ==========================================================
# MEMORY-EFFICIENT: EXTRACT ONLY DIVISION 07 FROM PDF
# ==========================================================
# Process page-by-page to avoid loading entire PDF into memory.
# Stop as soon as we find Division 07 and reach Division 08.
MAX_DIVISION_CHARS = 10000  # More than enough; we truncate to 8000 for AI

def extract_division_7_from_pdf(file_path: str) -> str | None:
    """
    Extract only Division 07 text from a PDF, page by page.
    Memory-efficient: only keeps relevant pages in memory.
    """
    found_div7 = False
    div7_text = []
    collected_chars = 0

    with pdfplumber.open(file_path) as pdf:
        for page in pdf.pages:
            text = page.extract_text()
            if not text:
                continue

            text_upper = text.upper()

            if not found_div7:
                # Look for Division 07 start on this page
                match = re.search(r"DIVISION\s*0?7", text_upper)
                if match:
                    found_div7 = True
                    div7_text.append(text[match.start():])
                    collected_chars += len(text) - match.start()
            else:
                # Already inside Division 07 â check for Division 08 (end)
                end_match = re.search(r"DIVISION\s*0?8", text_upper)
                if end_match:
                    div7_text.append(text[:end_match.start()])
                    break
                else:
                    div7_text.append(text)
                    collected_chars += len(text)

            # Safety limit: stop if we've collected way more than needed
            if collected_chars > MAX_DIVISION_CHARS:
                break

            # Release page memory
            del text, text_upper
            gc.collect()

    if not div7_text:
        return None

    return "\n".join(div7_text)


# Legacy function kept for compatibility
def extract_text_from_pdf(file_path: str) -> str:
    full_text = ""
    with pdfplumber.open(file_path) as pdf:
        for page in pdf.pages:
            text = page.extract_text()
            if text:
                full_text += text + "\n"
    return full_text


# ==========================================================
# AI ANALYSIS (uses memory-efficient extraction)
# ==========================================================
def analyze_spec_text_from_pdf(file_path: str):
    """
    Memory-efficient: extracts only Division 07 page-by-page,
    then sends to OpenAI. Never loads entire PDF into memory.
    """
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        return {"error": "OPENAI_API_KEY not configured"}

    client = OpenAI(api_key=api_key)

    # Extract only Division 07 text (page-by-page, memory efficient)
    division_7_text = extract_division_7_from_pdf(file_path)

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
