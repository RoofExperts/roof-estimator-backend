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

# NON-ROOFING Division 07 subsections to SKIP:
#   07 1X XX = Dampproofing, Waterproofing
#   07 2X XX = EIFS, Thermal Insulation (building walls), Air/Vapor Barriers
#   07 8X XX = Fireproofing, Firestopping
#   07 9X XX = Joint Sealants
# ACTUAL ROOFING lives in 07 3X-7X:
#   07 3X = Shingles/Shakes/Tiles
#   07 4X = Roof/Wall Panels (metal)
#   07 5X = Membrane Roofing (TPO, EPDM, PVC, BUR, Mod Bit)
#   07 6X = Flashing/Sheet Metal
#   07 7X = Roof Specialties/Accessories
NON_ROOFING_DIV07_PATTERN = r"SECTION\s+0?7\s*[1289]\d\s*\d{2}\s*-"

# EIFS / non-roofing negative keywords - if a page mentions these, skip it
EIFS_NEGATIVE_KEYWORDS = [
    "EIFS", "EXTERIOR INSULATION AND FINISH",
    "DRYVIT", "STO ", "PAREX", "FINESTONE",
    "STUCCO", "BASE COAT", "FINISH COAT",
    "WALL INSULATION", "WALL SYSTEM",
    "DAMPPROOFING", "FIRESTOPPING", "FIREPROOFING",
    "JOINT SEALANT",
]

# TIER 1: Roofing-SPECIFIC keywords (these rarely appear outside roofing sections)
ROOFING_SPECIFIC_KEYWORDS = [
    "TPO", "EPDM", "PVC ROOFING", "SINGLE-PLY",
    "MODIFIED BITUMEN", "BUILT-UP ROOFING", "ROOF SYSTEM",
    "ROOFING MEMBRANE", "THERMOSET",
    "MECHANICALLY ATTACHED", "FULLY ADHERED",
    "CARLISLE", "FIRESTONE", "GAF", "JOHNS MANVILLE",
    "SIKA SARNAFIL", "VERSICO", "TREMCO", "SOPREMA",
    "COVER BOARD", "POLYISOCYANURATE", "POLYISO",
    "ROOF INSULATION", "TAPERED INSULATION",
    "COPING", "COUNTERFLASHING", "ROOF DECK",
    "FLASHING AND SHEET METAL", "METAL ROOFING",
    "07 52", "07 54", "07 55", "07 61", "07 62", "07 72",
]

# TIER 2: Supporting keywords (common in roofing BUT also in other divisions)
ROOFING_SUPPORT_KEYWORDS = [
    "ROOFING", "FLASHING", "INSULATION", "THICKNESS",
    "MIL", "WARRANTY", "FASTENER", "ADHESIVE",
    "SEALANT", "VAPOR RETARDER",
    "R-VALUE", "FM GLOBAL",
    "MANUFACTURER", "ATTACHMENT", "MEMBRANE",
]


def extract_division_7_from_pdf(file_path: str) -> str | None:
    """
    Extract actual Division 07 spec content from a PDF, page by page.
    Skips table-of-contents pages; collects pages with real roofing details.
    Uses two-tier keyword system: roofing-specific + support keywords.
    Memory-efficient: only keeps relevant pages in memory.
    """
    collected_pages = []
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

            # Skip table-of-contents pages
            is_toc_page = "TABLE OF CONTENTS" in text_upper
            # Also detect TOC by counting 6-digit section numbers (042000, 072113, etc.)
            section_number_count = len(re.findall(r"\b\d{6}\b", text))
            if not is_toc_page and section_number_count >= 8:
                is_toc_page = True
            if is_toc_page:
                print(f"[spec_ai] Skipping TOC page {i+1} (section_numbers={section_number_count})")
                del text, text_upper
                gc.collect()
                continue

            # Skip pages whose PRIMARY section is NOT Division 07
            # Full section headers have a dash: "SECTION 061000 - ROUGH CARPENTRY"
            # Cross-references are just: "Section 07 52 00" (no dash)
            # If we find a non-Div07 section HEADER (with dash), skip the page
            non_roofing_header = re.search(
                r"SECTION\s+0?([0-689]|1[0-9]|[2-9]\d)\s*\d{2,4}\s*-",
                text_upper
            )
            if non_roofing_header:
                print(f"[spec_ai] Skipping page {i+1}: primary section is non-roofing ({non_roofing_header.group().strip()})")
                del text, text_upper
                gc.collect()
                continue

            # Skip non-roofing DIVISION 07 subsections (EIFS, waterproofing, fireproofing, sealants)
            # These are 07 1X, 07 2X, 07 8X, 07 9X - NOT roofing
            non_roofing_div07 = re.search(NON_ROOFING_DIV07_PATTERN, text_upper)
            if non_roofing_div07:
                print(f"[spec_ai] Skipping page {i+1}: non-roofing Div07 subsection ({non_roofing_div07.group().strip()})")
                del text, text_upper
                gc.collect()
                continue

            # Skip pages with EIFS / wall system negative keywords
            eifs_hits = [kw for kw in EIFS_NEGATIVE_KEYWORDS if kw in text_upper]
            if len(eifs_hits) >= 2:
                print(f"[spec_ai] Skipping page {i+1}: EIFS/wall system content ({eifs_hits})")
                del text, text_upper
                gc.collect()
                continue

            # Check if page has an actual ROOFING Division 07 section header (with dash)
            # Only 07 3X-7X are roofing sections
            has_div07_header = bool(re.search(
                r"SECTION\s+0?7\s*[3-7]\d\s*\d{2}\s*-",
                text_upper
            ))

            # Count TIER 1 (roofing-specific) keyword hits
            specific_hits = [kw for kw in ROOFING_SPECIFIC_KEYWORDS if kw in text_upper]
            # Count TIER 2 (support) keyword hits
            support_hits = [kw for kw in ROOFING_SUPPORT_KEYWORDS if kw in text_upper]

            # Page must have at least 1 roofing-SPECIFIC keyword to be collected
            # Then we look at total signal strength:
            #   - Div 07 section header + 1 specific = collect
            #   - 2+ specific keywords = collect
            #   - 1 specific + 2 support = collect
            has_specific = len(specific_hits) >= 1
            is_spec_page = False

            if has_specific:
                if has_div07_header:
                    is_spec_page = True
                elif len(specific_hits) >= 2:
                    is_spec_page = True
                elif len(specific_hits) >= 1 and len(support_hits) >= 2:
                    is_spec_page = True

            if is_spec_page:
                collected_pages.append(text)
                collected_chars += len(text)
                print(f"[spec_ai] Collecting page {i+1}: specific={specific_hits}, support_count={len(support_hits)}, div07_header={has_div07_header}")
                print(f"[spec_ai]   First 200 chars: {text[:200]}")
            else:
                # Log pages that were close but didn't qualify
                if len(specific_hits) > 0 or len(support_hits) >= 3:
                    print(f"[spec_ai] Skipping page {i+1}: specific={specific_hits}, support_count={len(support_hits)}, div07={has_div07_header}")

            # Safety limit
            if collected_chars > MAX_DIVISION_CHARS:
                print(f"[spec_ai] Hit MAX_DIVISION_CHARS limit ({collected_chars} chars)")
                break

            # Release page memory
            del text, text_upper
            gc.collect()

    if not collected_pages:
        print(f"[spec_ai] No roofing spec pages found in {total_pages} pages")
        print(f"[spec_ai] Trying fallback with relaxed criteria...")
        return _fallback_roofing_extract(file_path)

    result = "\n".join(collected_pages)
    print(f"[spec_ai] Extracted {len(result)} chars from {len(collected_pages)} spec pages")
    print(f"[spec_ai] First 300 chars: {result[:300]}")
    return result


def _fallback_roofing_extract(file_path: str) -> str | None:
    """
    Fallback: scan every page for roofing-specific keywords and collect matches.
    More relaxed than primary but still requires roofing-specific terms.
    """
    fallback_keywords = [
        "ROOFING", "MEMBRANE", "TPO", "EPDM", "PVC",
        "SINGLE-PLY", "ROOF SYSTEM", "FLASHING",
        "COVER BOARD", "ROOF DECK", "COPING",
        "07 52", "07 54", "07 55", "07 61", "07 62",
    ]
    collected = []
    collected_chars = 0

    with pdfplumber.open(file_path) as pdf:
        for i, page in enumerate(pdf.pages):
            text = page.extract_text()
            if not text:
                continue
            text_upper = text.upper()

            hits = [kw for kw in fallback_keywords if kw in text_upper]
            if len(hits) >= 2:
                print(f"[spec_ai] Fallback: page {i+1} matched {hits}")
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
    print(f"[spec_ai] Fallback first 300 chars: {result[:300]}")
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
