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

# Patterns that indicate start of Division 07 / roofing section
DIV7_START_PATTERNS = [
    r"DIVISION\s*0?7",           # "DIVISION 07" or "DIVISION 7"
    r"SECTION\s*07",             # "SECTION 07"
    r"\b07\s*[0-9]{2}\s*[0-9]{2}",  # CSI section numbers like "07 52 00"
    r"THERMAL\s+AND\s+MOISTURE", # Division 07 title
]

# Patterns that indicate we've passed Division 07
DIV7_END_PATTERNS = [
    r"DIVISION\s*0?8",
    r"SECTION\s*08",
    r"\b08\s*[0-9]{2}\s*[0-9]{2}",
    r"OPENINGS",                 # Division 08 title
]


def extract_division_7_from_pdf(file_path: str) -> str | None:
    """
    Extract only Division 07 text from a PDF, page by page.
    Memory-efficient: only keeps relevant pages in memory.
    """
    found_div7 = False
    div7_text = []
    collected_chars = 0
    total_pages = 0

    with pdfplumber.open(file_path) as pdf:
        total_pages = len(pdf.pages)
        print(f"[spec_ai] PDF has {total_pages} pages")

        for i, page in enumerate(pdf.pages):
            text = page.extract_text()
            if not text:
                continue

            text_upper = text.upper()

            if not found_div7:
                # Try each start pattern
                for pattern in DIV7_START_PATTERNS:
                    match = re.search(pattern, text_upper)
                    if match:
                        found_div7 = True
                        print(f"[spec_ai] Found Division 07 on page {i+1} via pattern: {pattern}")
                        print(f"[spec_ai] Match text: {text_upper[match.start():match.start()+60]}")
                        div7_text.append(text[match.start():])
                        collected_chars += len(text) - match.start()
                        break
            else:
                # Already inside Division 07 - check for end
                end_found = False
                for pattern in DIV7_END_PATTERNS:
                    end_match = re.search(pattern, text_upper)
                    if end_match:
                        div7_text.append(text[:end_match.start()])
                        print(f"[spec_ai] Found Division 08 boundary on page {i+1}")
                        end_found = True
                        break
                if end_found:
                    break
                else:
                    div7_text.append(text)
                    collected_chars += len(text)

            # Safety limit: stop if we've collected way more than needed
            if collected_chars > MAX_DIVISION_CHARS:
                print(f"[spec_ai] Hit MAX_DIVISION_CHARS limit ({collected_chars} chars)")
                break

            # Release page memory
            del text, text_upper
            gc.collect()

    if not div7_text:
        # Fallback: log first few pages to help debug
        print(f"[spec_ai] Division 07 NOT FOUND in {total_pages} pages")
        print(f"[spec_ai] Attempting fallback: scanning for any roofing keywords...")
        return _fallback_roofing_extract(file_path)

    result = "\n".join(div7_text)
    print(f"[spec_ai] Extracted {len(result)} chars of Division 07 text")
    print(f"[spec_ai] First 200 chars: {result[:200]}")
    return result


def _fallback_roofing_extract(file_path: str) -> str | None:
    """
    Fallback: if we can't find Division 07 header, look for pages
    containing roofing keywords and collect those.
    """
    roofing_keywords = [
        "ROOFING", "MEMBRANE", "TPO", "EPDM", "PVC", "FLASHING",
        "INSULATION", "COVER BOARD", "ROOF SYSTEM", "WATERPROOFING",
        "SHEET METAL", "SEALANT", "07 5", "07 6", "07 7",
    ]
    collected = []
    collected_chars = 0

    with pdfplumber.open(file_path) as pdf:
        for i, page in enumerate(pdf.pages):
            text = page.extract_text()
            if not text:
                continue
            text_upper = text.upper()

            # Check if this page has roofing-related content
            hits = sum(1 for kw in roofing_keywords if kw in text_upper)
            if hits >= 2:  # At least 2 keyword matches
                print(f"[spec_ai] Fallback: page {i+1} has {hits} roofing keywords")
                collected.append(text)
                collected_chars += len(text)

            if collected_chars > MAX_DIVISION_CHARS:
                break

            del text, text_upper
            gc.collect()

    if not collected:
        print("[spec_ai] Fallback: NO roofing content found anywhere in PDF")
        return None

    result = "\n".join(collected)
    print(f"[spec_ai] Fallback collected {len(result)} chars from {len(collected)} pages")
    return result


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

    print(f"[spec_ai] Sending {len(division_7_text)} chars to OpenAI")

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
    print(f"[spec_ai] OpenAI raw response: {raw[:300]}")

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
