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
# Collect pages with actual roofing spec content (not just TOC).
MAX_DIVISION_CHARS = 12000  # More than enough; we truncate to 8000 for AI

# Roofing section numbers (CSI Division 07 sections with actual specs)
ROOFING_SECTION_PATTERN = r"(?:SECTION\s+)?0?7\s*[2-9]\d\s*\d{2}"

# Keywords that indicate actual roofing spec content (not just a TOC line)
ROOFING_DETAIL_KEYWORDS = [
    "MANUFACTURER", "MEMBRANE", "TPO", "EPDM", "PVC", "ROOFING",
    "INSULATION", "FLASHING", "THICKNESS", "MIL", "WARRANTY",
    "ATTACHMENT", "FASTENER", "ADHESIVE", "COVER BOARD",
    "POLYISOCYANURATE", "POLYISO", "MECHANICALLY ATTACHED",
    "FULLY ADHERED", "CARLISLE", "FIRESTONE", "GAF", "JOHNS MANVILLE",
    "SIKA SARNAFIL", "VERSICO", "TREMCO", "SOPREMA",
    "MODIFIED BITUMEN", "BUILT-UP", "SINGLE-PLY", "SHEET METAL",
    "WATERPROOFING", "SEALANT", "COPING", "COUNTERFLASHING",
    "ROOF SYSTEM", "VAPOR RETARDER", "AIR BARRIER",
    "R-VALUE", "THERMAL", "FM GLOBAL", "UL", "ASTM",
]


def extract_division_7_from_pdf(file_path: str) -> str | None:
    """
    Extract actual Division 07 spec content from a PDF, page by page.
    Skips table-of-contents pages; collects pages with real roofing details.
    Memory-efficient: only keeps relevant pages in memory.
    """
    collected_pages = []
    collected_chars = 0
    total_pages = 0
    in_div7_zone = False
    past_toc = False

    with pdfplumber.open(file_path) as pdf:
        total_pages = len(pdf.pages)
        print(f"[spec_ai] PDF has {total_pages} pages")

        for i, page in enumerate(pdf.pages):
            text = page.extract_text()
            if not text:
                continue

            text_upper = text.upper()

            # Check if we've entered Division 08 zone (stop collecting)
            if in_div7_zone and past_toc:
                div8_match = re.search(r"DIVISION\s*0?8|SECTION\s*08\s*\d{2}\s*\d{2}", text_upper)
                if div8_match:
                    # Only stop if this page is primarily Division 08 content
                    div8_keywords = sum(1 for kw in ["DOOR", "WINDOW", "OPENING", "HARDWARE", "GLAZING"] if kw in text_upper)
                    if div8_keywords >= 1:
                        print(f"[spec_ai] Hit Division 08 zone on page {i+1}, stopping")
                        break

            # Check for Division 07 TOC or header page
            if not in_div7_zone:
                div7_header = re.search(r"DIVISION\s*0?7|THERMAL\s+AND\s+MOISTURE", text_upper)
                if div7_header:
                    in_div7_zone = True
                    print(f"[spec_ai] Entered Division 07 zone on page {i+1}")
                    # Don't collect this page yet - it's likely TOC

            # Count how many detail keywords appear on this page
            detail_hits = sum(1 for kw in ROOFING_DETAIL_KEYWORDS if kw in text_upper)

            # Check if page has a section header like "SECTION 07 52 00"
            has_section_header = bool(re.search(ROOFING_SECTION_PATTERN, text_upper))

            # Collect this page if it has real roofing spec content
            # Either: 3+ detail keywords, or a section header + 2+ keywords
            is_spec_page = (detail_hits >= 3) or (has_section_header and detail_hits >= 2)

            if is_spec_page:
                if not past_toc:
                    past_toc = True
                    print(f"[spec_ai] First real spec content on page {i+1} ({detail_hits} keywords)")

                collected_pages.append(text)
                collected_chars += len(text)
                print(f"[spec_ai] Collecting page {i+1}: {detail_hits} keywords, section_header={has_section_header}")

            # Safety limit
            if collected_chars > MAX_DIVISION_CHARS:
                print(f"[spec_ai] Hit MAX_DIVISION_CHARS limit ({collected_chars} chars)")
                break

            # Release page memory
            del text, text_upper
            gc.collect()

    if not collected_pages:
        print(f"[spec_ai] No roofing spec pages found in {total_pages} pages")
        print(f"[spec_ai] Trying keyword-only fallback...")
        return _fallback_roofing_extract(file_path)

    result = "\n".join(collected_pages)
    print(f"[spec_ai] Extracted {len(result)} chars from {len(collected_pages)} spec pages")
    print(f"[spec_ai] First 300 chars: {result[:300]}")
    return result


def _fallback_roofing_extract(file_path: str) -> str | None:
    """
    Fallback: scan every page for roofing keywords and collect matches.
    """
    roofing_keywords = [
        "ROOFING", "MEMBRANE", "TPO", "EPDM", "PVC", "FLASHING",
        "INSULATION", "COVER BOARD", "ROOF SYSTEM", "WATERPROOFING",
        "SHEET METAL", "SEALANT", "07 5", "07 6", "07 7",
        "MANUFACTURER", "THICKNESS", "WARRANTY", "FASTENER",
    ]
    collected = []
    collected_chars = 0

    with pdfplumber.open(file_path) as pdf:
        for i, page in enumerate(pdf.pages):
            text = page.extract_text()
            if not text:
                continue
            text_upper = text.upper()

            hits = sum(1 for kw in roofing_keywords if kw in text_upper)
            if hits >= 3:
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

Analyze this CSI Division 07 roofing specification text.
Extract all roofing details you can find.

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
    print(f"[spec_ai] OpenAI raw response: {raw[:500]}")

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
