"""
CSI Division 07 specification reader.

Extracts roofing spec details (membrane type, mil thickness, warranty,
manufacturers, attachment method, insulation, etc.) from a project's
specification PDF.

Pipeline:
  1. Find Division 07 pages by keyword + section-number heuristics
  2. Extract text WITH layout preservation + tables as structured data
  3. Send combined content to the configured AI provider
  4. Validate response against a Pydantic schema
  5. Return a dict the frontend can consume

Provider selection: SPEC_PROVIDER env var ("anthropic" default, "openai" fallback).
"""

import os
import re
import json
import gc
from typing import Optional, List, Union

import pdfplumber
from pydantic import BaseModel, ConfigDict, Field, ValidationError


# ============================================================================
# PROVIDER CONFIGURATION
# ============================================================================
SPEC_PROVIDER = os.getenv("SPEC_PROVIDER", "anthropic").lower().strip()
SPEC_MODEL_ANTHROPIC = os.getenv("SPEC_MODEL_ANTHROPIC", "claude-sonnet-4-6")
SPEC_MODEL_OPENAI    = os.getenv("SPEC_MODEL_OPENAI",    "gpt-4o-mini")

# Lazy-init clients (avoid importing the wrong SDK when a key isn't set)
_anthropic_client = None
_openai_client    = None


def _get_anthropic_client():
    """Lazy-init the Anthropic client.

    If Track A's vision_ai.py has been merged, you may import _get_anthropic_client
    from there instead of duplicating it. The two implementations are intentionally
    interchangeable.
    """
    global _anthropic_client
    if _anthropic_client is None:
        api_key = os.getenv("ANTHROPIC_API_KEY")
        if not api_key:
            raise RuntimeError(
                "ANTHROPIC_API_KEY not set. Either set it in the environment "
                "or set SPEC_PROVIDER=openai to use the OpenAI fallback."
            )
        from anthropic import Anthropic
        _anthropic_client = Anthropic(api_key=api_key, timeout=120.0)
    return _anthropic_client


def _get_openai_client():
    """Lazy-init the OpenAI client (legacy fallback)."""
    global _openai_client
    if _openai_client is None:
        api_key = os.getenv("OPENAI_API_KEY")
        if not api_key:
            raise RuntimeError(
                "OPENAI_API_KEY not set. Either set it in the environment "
                "or set SPEC_PROVIDER=anthropic to use Claude Sonnet 4.6."
            )
        from openai import OpenAI
        _openai_client = OpenAI(api_key=api_key, timeout=120.0)
    return _openai_client


# ============================================================================
# PIPELINE CONFIGURATION
# ============================================================================
# Modern Claude has a 200K context window; Division 07 sections in real specs
# rarely exceed 80K chars. Set a generous cap that still protects against
# pathological inputs.
MAX_DIVISION_CHARS = 50000   # Page-collection cap (collect generously)
MAX_PROMPT_CHARS   = 120000  # Hard cap on what we send to the model

# Memory-bounded page collection (Path A fix following the OOM in PR #5).
# We hold up to this many (score, page_num) tuples during the page-scoring
# pass, then run heavy text/table extraction only on the top-N. This bounds
# memory regardless of how long the input PDF is. Real Division 07 in any
# spec book we've ever seen fits well inside this limit; the cap exists to
# stop pathological PDFs from OOMing the service.
MAX_KEPT_PAGES = 80


# ==========================================================
# MEMORY-EFFICIENT: EXTRACT ONLY DIVISION 07 FROM PDF
# ==========================================================
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
NON_ROOFING_DIV07_PATTERN = r"SECTION\s+0?7\s*[1289]\d\s*\d{2}\s*[\-–—]"

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


# ============================================================================
# OUTPUT SCHEMA — what the model returns and what the frontend consumes
# ============================================================================
class SpecResult(BaseModel):
    """Validated roofing spec extraction.

    These field names match what the existing frontend reads from
    project.analysis_result. Do not rename them.
    """
    roof_system_type:    Optional[str] = Field(None, description='e.g. "Thermoplastic Membrane Roofing"')
    membrane_type:       Optional[str] = Field(None, description='e.g. "TPO", "EPDM", "PVC"')
    membrane_thickness:  Optional[str] = Field(None, description='e.g. "60 mil", "80 mil"')
    attachment_method:   Optional[str] = Field(None, description='e.g. "Mechanically Attached", "Fully Adhered"')
    insulation_type:     Optional[str] = Field(None, description='e.g. "Polyisocyanurate (Polyiso/ISO)"')
    insulation_layers:   Optional[str] = Field(None, description='Free-text: number of layers, R-values, thicknesses')
    cover_board:         Optional[str] = Field(None, description='Material AND thickness, e.g. "1/2 inch DensDeck"')
    fastening_pattern:   Optional[str] = Field(None, description='Free-text: spacing, pattern, fasteners-per-board')
    warranty_years:      Optional[Union[int, str]] = Field(None, description='Years; int if a single value, str if a range')
    manufacturer:        Optional[Union[List[str], str]] = Field(None, description='List of all approved manufacturers')
    special_requirements: Optional[Union[List[str], str]] = Field(None, description='FM Global, UL ratings, wind uplift, etc.')

    # Allow "manufacturer": "Carlisle" OR "manufacturer": ["Carlisle", "GAF"]
    model_config = ConfigDict(extra="ignore")


def extract_division_7_from_pdf(file_path: str) -> Optional[dict]:
    """
    Extract actual Division 07 spec content from a PDF, page by page.

    Returns a dict:
      {
        "text":   "...layout-preserved text from kept pages...",
        "tables": [
          {"page": 47, "rows": [["Manufacturer", "Mil", "Warranty"], ...]},
          ...
        ],
        "page_count_total":     <int>,
        "page_count_collected": <int>,
      }
    or None if no Division 07 pages were found (caller handles fallback).

    Implementation note (memory-bounded design):
      Pass 1 scans every page using cheap extract_text() only, scores
      candidates, and keeps at most MAX_KEPT_PAGES (score, page_idx) tuples.

      Pass 2 re-opens the PDF and calls expensive extract_text(layout=True)
      and extract_tables() ONLY on the kept pages. This bounds peak memory
      regardless of input PDF length.
    """
    # ------------------------------------------------------------------
    # PASS 1: cheap scan — score every page, track top MAX_KEPT_PAGES
    # ------------------------------------------------------------------
    candidates = []  # list of (score, page_index_0based) — bounded
    total_pages = 0

    with pdfplumber.open(file_path) as pdf:
        total_pages = len(pdf.pages)
        print(f"[spec_ai] PDF has {total_pages} pages")

        for i, page in enumerate(pdf.pages):
            text = page.extract_text()
            if not text:
                continue

            text_upper = text.upper()

            # ===== identical gating logic to PR #5 (do not change rules) =====

            # Skip TOC pages
            is_toc_page = "TABLE OF CONTENTS" in text_upper
            section_number_count = len(re.findall(r"\b\d{6}\b", text))
            if not is_toc_page and section_number_count >= 8:
                is_toc_page = True
            if is_toc_page:
                print(f"[spec_ai] Skipping TOC page {i+1} (section_numbers={section_number_count})")
                del text, text_upper
                gc.collect()
                continue

            # Non-roofing primary section header — skip unless 3+ roofing keywords
            non_roofing_header = re.search(
                r"SECTION\s+(0[0-689]|[1-9]\d)\s*\d{4}\s*[\-–—]",
                text_upper
            )
            if non_roofing_header:
                roofing_signal = [kw for kw in ROOFING_SUPPORT_KEYWORDS if kw in text_upper]
                if len(roofing_signal) < 3:
                    print(f"[spec_ai] Skipping page {i+1}: primary section is non-roofing ({non_roofing_header.group().strip()})")
                    del text, text_upper
                    gc.collect()
                    continue
                else:
                    print(f"[spec_ai] Page {i+1} has non-roofing header but {len(roofing_signal)} roofing keywords - keeping")

            # Non-roofing Division 07 subsection (EIFS, waterproofing, sealants)
            non_roofing_div07 = re.search(NON_ROOFING_DIV07_PATTERN, text_upper)
            if non_roofing_div07:
                print(f"[spec_ai] Skipping page {i+1}: non-roofing Div07 subsection ({non_roofing_div07.group().strip()})")
                del text, text_upper
                gc.collect()
                continue

            # EIFS / wall system negative keywords
            eifs_hits = [kw for kw in EIFS_NEGATIVE_KEYWORDS if kw in text_upper]
            if len(eifs_hits) >= 2:
                print(f"[spec_ai] Skipping page {i+1}: EIFS/wall system content ({eifs_hits})")
                del text, text_upper
                gc.collect()
                continue

            has_div07_header = bool(re.search(
                r"SECTION\s+0?7\s*[3-7]\d\s*\d{2}\s*[\-–—]",
                text_upper
            ))
            specific_hits = [kw for kw in ROOFING_SPECIFIC_KEYWORDS if kw in text_upper]
            support_hits = [kw for kw in ROOFING_SUPPORT_KEYWORDS if kw in text_upper]

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
                # Score (same formula as PR #5)
                MEMBRANE_BOOST = ["TPO", "EPDM", "PVC", "SINGLE-PLY", "ROOFING MEMBRANE",
                                  "FULLY ADHERED", "MECHANICALLY ATTACHED", "COVER BOARD",
                                  "POLYISOCYANURATE", "POLYISO", "ROOF SYSTEM", "MIL",
                                  "ROOF INSULATION", "TAPERED INSULATION"]
                membrane_hits = sum(1 for kw in MEMBRANE_BOOST if kw in text_upper)
                page_score = len(specific_hits) + membrane_hits * 2 + (5 if has_div07_header else 0)

                # Keep at most MAX_KEPT_PAGES candidates, evicting the
                # lowest-scoring one when full.
                if len(candidates) < MAX_KEPT_PAGES:
                    candidates.append((page_score, i))
                else:
                    # Find the lowest-scoring candidate and replace it if our
                    # new page scores higher
                    min_idx = 0
                    for idx, (s, _) in enumerate(candidates):
                        if s < candidates[min_idx][0]:
                            min_idx = idx
                    if page_score > candidates[min_idx][0]:
                        evicted_score, evicted_page = candidates[min_idx]
                        candidates[min_idx] = (page_score, i)
                        print(f"[spec_ai] Page {i+1} score={page_score} evicted page {evicted_page+1} score={evicted_score}")

                print(f"[spec_ai] Candidate page {i+1}: specific={specific_hits}, "
                      f"support_count={len(support_hits)}, div07_header={has_div07_header}, "
                      f"score={page_score}")
            else:
                if len(specific_hits) > 0 or len(support_hits) >= 3:
                    print(f"[spec_ai] Skipping page {i+1}: "
                          f"specific={specific_hits}, support_count={len(support_hits)}, "
                          f"div07={has_div07_header}")

            del text, text_upper
            gc.collect()

    if not candidates:
        print(f"[spec_ai] No roofing spec pages found in {total_pages} pages")
        print(f"[spec_ai] Trying fallback with relaxed criteria...")
        return _fallback_roofing_extract(file_path)

    # Sort highest score first
    candidates.sort(key=lambda x: x[0], reverse=True)

    # ------------------------------------------------------------------
    # PASS 2: heavy extraction — only on the kept pages
    # ------------------------------------------------------------------
    print(f"[spec_ai] Pass 2: extracting layout text + tables from {len(candidates)} pages")

    text_parts = []
    all_tables = []
    page_numbers_collected = []

    with pdfplumber.open(file_path) as pdf:
        for score, page_idx in candidates:
            page = pdf.pages[page_idx]
            page_num = page_idx + 1

            try:
                layout_text = page.extract_text(layout=True) or page.extract_text() or ""
            except Exception as e:
                print(f"[spec_ai] Layout extraction failed page {page_num}, falling back: {e}")
                try:
                    layout_text = page.extract_text() or ""
                except Exception:
                    layout_text = ""

            try:
                raw_tables = page.extract_tables() or []
            except Exception as e:
                print(f"[spec_ai] Table extraction failed page {page_num}: {e}")
                raw_tables = []

            page_tables = []
            for tbl in raw_tables:
                if not tbl or len(tbl) < 2:
                    continue
                if not any(any((cell or "").strip() for cell in row) for row in tbl):
                    continue
                page_tables.append(tbl)

            if layout_text:
                text_parts.append(f"--- PAGE {page_num} ---\n{layout_text}")
            for tbl in page_tables:
                all_tables.append({"page": page_num, "rows": tbl})
            page_numbers_collected.append(page_num)

            print(f"[spec_ai]   Pass2 page {page_num} score={score} "
                  f"text={len(layout_text)} tables={len(page_tables)}")

            # Free per-page memory aggressively
            del layout_text, raw_tables, page_tables
            gc.collect()

    result_text = "\n\n".join(text_parts)

    # Diagnostics (kept from PR #5)
    top10 = page_numbers_collected[:10]
    print(f"[spec_ai] DIAG: total_pages_in_pdf={total_pages}")
    print(f"[spec_ai] DIAG: pages_collected={len(page_numbers_collected)}")
    print(f"[spec_ai] DIAG: top10_pages_by_score={top10}")
    print(f"[spec_ai] DIAG: assembled_text_first_200={result_text[:200]!r}")

    print(f"[spec_ai] Extracted {len(result_text)} chars from {len(page_numbers_collected)} pages "
          f"({len(all_tables)} tables)")
    print(f"[spec_ai] First 300 chars: {result_text[:300]}")

    return {
        "text": result_text,
        "tables": all_tables,
        "page_count_total": total_pages,
        "page_count_collected": len(page_numbers_collected),
    }


def _fallback_roofing_extract(file_path: str) -> Optional[dict]:
    """Fallback when no Division 07 sections were found.

    Last-resort: collect any page that mentions roofing-specific keywords,
    even without a section header. Same memory-bounded design as the main
    extractor.

    Returns the same dict shape as extract_division_7_from_pdf.
    """
    fallback_keywords = [
        "ROOF MEMBRANE", "ROOFING MEMBRANE", "TPO ROOFING", "EPDM ROOFING",
        "PVC ROOFING", "SINGLE-PLY ROOFING", "ROOF SYSTEM",
        "ROOF INSULATION", "TAPERED INSULATION",
    ]
    candidates = []  # list of (score, page_idx)
    total_pages = 0

    with pdfplumber.open(file_path) as pdf:
        total_pages = len(pdf.pages)
        print(f"[spec_ai] (fallback) PDF has {total_pages} pages")

        for i, page in enumerate(pdf.pages):
            text = page.extract_text()
            if not text:
                continue
            text_upper = text.upper()

            hits = [kw for kw in fallback_keywords if kw in text_upper]
            if len(hits) >= 1:
                page_score = len(hits)
                if len(candidates) < MAX_KEPT_PAGES:
                    candidates.append((page_score, i))
                else:
                    min_idx = 0
                    for idx, (s, _) in enumerate(candidates):
                        if s < candidates[min_idx][0]:
                            min_idx = idx
                    if page_score > candidates[min_idx][0]:
                        candidates[min_idx] = (page_score, i)
                print(f"[spec_ai] (fallback) Candidate page {i+1}: hits={hits}, score={page_score}")

            del text, text_upper
            gc.collect()

    if not candidates:
        print("[spec_ai] (fallback) No pages with roofing keywords found")
        return None

    candidates.sort(key=lambda x: x[0], reverse=True)
    print(f"[spec_ai] (fallback) Pass 2: extracting from {len(candidates)} pages")

    text_parts = []
    all_tables = []
    pages_done = 0

    with pdfplumber.open(file_path) as pdf:
        for score, page_idx in candidates:
            page = pdf.pages[page_idx]
            page_num = page_idx + 1
            try:
                layout_text = page.extract_text(layout=True) or page.extract_text() or ""
            except Exception as e:
                print(f"[spec_ai] (fallback) layout extract failed page {page_num}: {e}")
                layout_text = page.extract_text() or ""

            try:
                raw_tables = page.extract_tables() or []
            except Exception:
                raw_tables = []

            page_tables = []
            for tbl in raw_tables:
                if not tbl or len(tbl) < 2:
                    continue
                if not any(any((cell or "").strip() for cell in row) for row in tbl):
                    continue
                page_tables.append(tbl)

            if layout_text:
                text_parts.append(f"--- PAGE {page_num} ---\n{layout_text}")
            for tbl in page_tables:
                all_tables.append({"page": page_num, "rows": tbl})
            pages_done += 1

            del layout_text, raw_tables, page_tables
            gc.collect()

    result_text = "\n\n".join(text_parts)
    print(f"[spec_ai] (fallback) DIAG: total_pages_in_pdf={total_pages} pages_collected={pages_done}")
    print(f"[spec_ai] (fallback) Extracted {len(result_text)} chars from {pages_done} pages")

    return {
        "text": result_text,
        "tables": all_tables,
        "page_count_total": total_pages,
        "page_count_collected": pages_done,
    }


# ==========================================================
# AI ANALYSIS (uses memory-efficient extraction)
# ==========================================================
def analyze_spec_text_from_pdf(file_path: str) -> dict:
    """
    Memory-efficient: extracts only Division 07 page-by-page, then sends
    layout-preserved text + tables to the configured AI provider.
    """
    # Pre-flight: verify the configured provider has an API key
    if SPEC_PROVIDER == "anthropic":
        api_key = os.getenv("ANTHROPIC_API_KEY")
        key_name = "ANTHROPIC_API_KEY"
        provider_label = f"Claude {SPEC_MODEL_ANTHROPIC}"
    elif SPEC_PROVIDER == "openai":
        api_key = os.getenv("OPENAI_API_KEY")
        key_name = "OPENAI_API_KEY"
        provider_label = f"OpenAI {SPEC_MODEL_OPENAI}"
    else:
        return {"error": f"Unknown SPEC_PROVIDER='{SPEC_PROVIDER}'. Expected 'anthropic' or 'openai'."}

    if not api_key:
        return {"error": f"{key_name} not configured (SPEC_PROVIDER={SPEC_PROVIDER})"}

    print(f"[spec_ai] Using {provider_label}")

    # Extract Division 07 content (text + tables)
    extracted = extract_division_7_from_pdf(file_path)
    if not extracted:
        return {"error": "Division 07 not found in spec"}

    spec_text   = extracted["text"]
    spec_tables = extracted.get("tables", [])

    # Cap the total payload so we don't blow the context window or burn tokens
    if len(spec_text) > MAX_PROMPT_CHARS:
        print(f"[spec_ai] Truncating text from {len(spec_text)} to {MAX_PROMPT_CHARS} chars")
        spec_text = spec_text[:MAX_PROMPT_CHARS]

    # Format tables as a separate, clearly labeled section
    table_block = _format_tables_for_prompt(spec_tables) if spec_tables else "(no tables extracted)"

    user_prompt = _build_spec_prompt(spec_text, table_block)

    # Route to the configured provider
    try:
        if SPEC_PROVIDER == "anthropic":
            raw = _call_anthropic_spec(user_prompt)
        else:
            raw = _call_openai_spec(user_prompt)
    except Exception as e:
        print(f"[spec_ai] Provider call failed: {e}")
        return {"error": f"AI call failed: {e}"}

    print(f"[spec_ai] Raw response (first 500 chars): {raw[:500]}")

    # Strip any accidental markdown code fences
    cleaned = re.sub(r"```json", "", raw)
    cleaned = re.sub(r"```", "", cleaned).strip()

    # Parse + validate against schema
    try:
        parsed_obj = json.loads(cleaned)
    except json.JSONDecodeError:
        # Last-ditch: try to find a JSON object inside the text
        match = re.search(r"\{[\s\S]*\}", cleaned)
        if match:
            try:
                parsed_obj = json.loads(match.group())
            except json.JSONDecodeError:
                return {"error": "AI returned invalid JSON", "raw_response": raw[:1000]}
        else:
            return {"error": "AI returned invalid JSON", "raw_response": raw[:1000]}

    try:
        validated = SpecResult(**parsed_obj)
    except ValidationError as e:
        print(f"[spec_ai] Pydantic validation failed: {e}")
        # Return the raw parsed object anyway — the frontend tolerates extra/missing fields
        # but log the validation error so we can tighten prompts later
        return parsed_obj

    return validated.model_dump(exclude_none=False)


def _format_tables_for_prompt(tables: list) -> str:
    """Render extracted tables as a readable block for the prompt."""
    blocks = []
    for entry in tables:
        page_num = entry["page"]
        rows = entry["rows"]
        if not rows:
            continue
        # Render as pipe-delimited rows (compact, model-friendly)
        rendered_rows = []
        for row in rows:
            cells = [(cell or "").strip().replace("\n", " ") for cell in row]
            rendered_rows.append(" | ".join(cells))
        blocks.append(f"[Table from page {page_num}]\n" + "\n".join(rendered_rows))
    return "\n\n".join(blocks)


def _build_spec_prompt(spec_text: str, table_block: str) -> str:
    """Build the user prompt sent to the AI provider."""
    return f"""You are a professional commercial roofing estimator analyzing a CSI Division 07 specification.

Extract roofing details into the JSON fields below. Follow these instructions for each field:

- roof_system_type: The roofing system category (e.g., "Thermoplastic Membrane Roofing", "Modified Bitumen", "Built-Up Roofing", "Metal Roofing")
- membrane_type: The specific membrane material (e.g., "TPO", "EPDM", "PVC", "KEE", "Modified Bitumen SBS/APP")
- membrane_thickness: The mil thickness (e.g., "60 mil", "80 mil", "45 mil", "115 mil"). Look for "minimum XX mil", "XX-mil", or "nominal thickness". This is critical — search every line.
- attachment_method: How the membrane is attached (e.g., "Mechanically Attached", "Fully Adhered", "Ballasted", "Induction Welded", "Rhinobond")
- insulation_type: The specific insulation material (e.g., "Polyisocyanurate (Polyiso/ISO)", "EPS", "XPS"). Do NOT confuse wall/EIFS insulation with roof insulation.
- insulation_layers: Number of layers, R-values, and thicknesses. e.g. "Two layers: 2.5\" base + 2.0\" top, total R-25"
- cover_board: Material AND thickness (e.g., "1/2 inch DensDeck", "5/8 inch HD gypsum"). Include both — never just "sheathing".
- fastening_pattern: Screw spacing, fasteners per board, rows of fasteners — anything specifying attachment pattern.
- warranty_years: Years as a number when possible (e.g., 20, 25, 30). If a range is specified, use a string like "20-30".
- manufacturer: A list of ALL approved manufacturers mentioned. Include every named brand that's listed as acceptable.
- special_requirements: FM Global ratings, UL classifications, wind uplift requirements, drain coordination, testing requirements.

CRITICAL OUTPUT RULES:
1. Return ONE JSON object only. No markdown, no code fences, no prose before or after.
2. If a value is not stated in the spec, use null. Do NOT guess or infer.
3. The TABLES section often contains the manufacturer / product / mil / warranty grid. Read it carefully and include every approved manufacturer.
4. If the spec lists multiple acceptable systems (e.g., a 60-mil and an 80-mil option), report what's specified as the basis-of-design or the most-commonly-listed value, and add a note in special_requirements.

=== SPECIFICATION TEXT (layout-preserved) ===
{spec_text}

=== EXTRACTED TABLES ===
{table_block}

Return only the JSON object."""


def _call_anthropic_spec(user_prompt: str) -> str:
    """Send the prompt to Claude Sonnet 4.6 (or whatever SPEC_MODEL_ANTHROPIC is)."""
    client = _get_anthropic_client()
    system_prompt = (
        "You are an expert at extracting detailed roofing specifications from "
        "CSI Division 07 documents. You never miss membrane thickness (mil), "
        "warranty years, manufacturer names, or insulation types. You read every "
        "line carefully, especially tables. You return ONLY a single JSON object "
        "with no surrounding prose."
    )
    response = client.messages.create(
        model=SPEC_MODEL_ANTHROPIC,
        max_tokens=2000,
        temperature=0.0,
        system=system_prompt,
        messages=[{"role": "user", "content": user_prompt}],
    )
    parts = []
    for block in response.content:
        if getattr(block, "type", None) == "text":
            parts.append(block.text)
    return "".join(parts)


def _call_openai_spec(user_prompt: str) -> str:
    """Send the prompt to GPT-4o-mini (or whatever SPEC_MODEL_OPENAI is). Legacy fallback."""
    client = _get_openai_client()
    response = client.chat.completions.create(
        model=SPEC_MODEL_OPENAI,
        temperature=0.0,
        max_tokens=2000,
        messages=[
            {"role": "system", "content": (
                "You are an expert at extracting detailed roofing specifications "
                "from CSI Division 07 documents. You never miss membrane thickness (mil), "
                "warranty years, manufacturer names, or insulation types. You read every "
                "line carefully, especially tables. You return ONLY a single JSON object "
                "with no surrounding prose."
            )},
            {"role": "user", "content": user_prompt},
        ],
    )
    return response.choices[0].message.content.strip()
