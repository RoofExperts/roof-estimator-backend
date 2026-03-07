"""
Core AI Vision analysis engine for reading architectural roof plans.
Converts PDF pages to images, sends to GPT-4o vision, extracts measurements,
and auto-creates RoofCondition records.

Page-type-aware extraction:
  - Slab Plan â roof area (LÃW), parapet wall (lnft), coping (lnft)
  - Roof Plan â roof drains (ea), scuppers (ea), pitch pans (ea), pipes (ea), curbs (lnft)
  - Elevations â parapet flashing height (in), collector heads (ea), downspouts (lnft)
"""

import os
import io
import json
import base64
import asyncio
import fitz  # PyMuPDF
from PIL import Image
from openai import AsyncOpenAI
from sqlalchemy.orm import Session

from database import SessionLocal
from vision_models import RoofPlanFile, PlanPageAnalysis, VisionExtraction
from conditions_models import RoofCondition
from vision_prompts import (
    PAGE_TYPE_PROMPT,
    SCALE_DETECTION_PROMPT,
    build_prompt_for_page_type,
    parse_vision_response,
    validate_extraction,
)

async_client = AsyncOpenAI(
    api_key=os.getenv("OPENAI_API_KEY"),
    timeout=120.0,
)

MAX_PAGES = 20
IMAGE_DPI = 120  # Lowered from 150 to reduce image size and API latency
MAX_IMAGE_SIZE_MB = 3.0  # Lowered from 4MB to speed up API calls
VISION_MODEL = "gpt-4o"
MAX_EXTRACTION_PAGES = 10  # Analyze up to 10 pages for measurements


def convert_pdf_to_images(file_path: str, max_pages: int = MAX_PAGES) -> list:
    """Convert PDF pages to base64-encoded images for GPT-4o vision."""
    doc = fitz.open(file_path)
    page_count = min(len(doc), max_pages)
    images = []

    for page_num in range(page_count):
        page = doc[page_num]
        zoom = IMAGE_DPI / 72
        mat = fitz.Matrix(zoom, zoom)
        pix = page.get_pixmap(matrix=mat)
        img = Image.frombytes("RGB", [pix.width, pix.height], pix.samples)
        img_base64 = compress_image_to_base64(img)
        images.append({
            "page_number": page_num + 1,
            "image_base64": img_base64,
            "width": pix.width,
            "height": pix.height,
        })
    doc.close()
    return images


def compress_image_to_base64(img, max_size_mb: float = MAX_IMAGE_SIZE_MB) -> str:
    """Compress image to JPEG and return base64 string."""
    quality = 85
    while quality >= 20:
        buffer = io.BytesIO()
        img.save(buffer, format="JPEG", quality=quality)
        size_mb = buffer.tell() / (1024 * 1024)
        if size_mb <= max_size_mb:
            return base64.b64encode(buffer.getvalue()).decode("utf-8")
        quality -= 10

    img = img.resize((img.width // 2, img.height // 2), Image.LANCZOS)
    buffer = io.BytesIO()
    img.save(buffer, format="JPEG", quality=60)
    return base64.b64encode(buffer.getvalue()).decode("utf-8")


CALL_TIMEOUT_SECONDS = 30  # Hard timeout per GPT-4o API call (reduced from 90)


async def _async_vision_call(image_base64: str, prompt: str, detail: str) -> str:
    """Internal: make the actual OpenAI API call using async client."""
    response = await async_client.chat.completions.create(
        model=VISION_MODEL,
        messages=[{
            "role": "user",
            "content": [
                {"type": "text", "text": prompt},
                {"type": "image_url", "image_url": {
                    "url": f"data:image/jpeg;base64,{image_base64}",
                    "detail": detail,
                }},
            ],
        }],
        max_tokens=2000,
        temperature=0.1,
    )
    return response.choices[0].message.content


def call_vision_api(image_base64: str, prompt: str, detail: str = "high") -> str:
    """Send an image to GPT-4o vision and return the response text.

    Uses asyncio with wait_for() for a HARD timeout that actually cancels
    the HTTP request. Previous approaches (threading, concurrent.futures)
    failed because Python threads cannot be interrupted - they just get
    abandoned while still holding connections. asyncio.wait_for() cancels
    the coroutine which closes the underlying HTTP connection.

    Args:
        detail: "high" for measurement extraction (needs precision),
                "low" for page classification (just needs to see layout).
    """
    async def _run_with_timeout():
        return await asyncio.wait_for(
            _async_vision_call(image_base64, prompt, detail),
            timeout=CALL_TIMEOUT_SECONDS,
        )

    # Create a new event loop for each call (we're in a sync context)
    loop = asyncio.new_event_loop()
    try:
        result = loop.run_until_complete(_run_with_timeout())
        return result
    except asyncio.TimeoutError:
        print(f"[Vision] HARD TIMEOUT: GPT-4o async call exceeded {CALL_TIMEOUT_SECONDS}s (detail={detail})")
        raise TimeoutError(f"GPT-4o API call timed out after {CALL_TIMEOUT_SECONDS}s")
    finally:
        loop.close()


def classify_page(image_base64: str) -> dict:
    """Use GPT-4o to classify what type of architectural page this is.
    Uses detail='low' since classification only needs to see the general layout,
    not read fine measurements. This is ~3-5x faster than 'high' detail.
    """
    return parse_vision_response(call_vision_api(image_base64, PAGE_TYPE_PROMPT, detail="low"))


def detect_scale(image_base64: str) -> dict:
    """Use GPT-4o to find and parse the drawing scale.
    Uses detail='high' because scale notation (especially fractions like
    3/16" vs 1/8") requires pixel-level precision to read correctly.
    Misreading the scale cascades into area errors (e.g., 1/8" vs 3/16"
    gives a 2.25x area difference).
    """
    return parse_vision_response(call_vision_api(image_base64, SCALE_DETECTION_PROMPT, detail="high"))


def extract_measurements_for_page(image_base64: str, page_type: str, scale_info: dict) -> dict:
    """Use GPT-4o to extract measurements using the appropriate page-type prompt."""
    prompt = build_prompt_for_page_type(page_type, scale_info)
    return parse_vision_response(call_vision_api(image_base64, prompt))


def measure_roof_plan_area(image_base64: str, scale_info: dict) -> dict:
    """Dedicated roof plan area measurement using scale.
    Sends the roof plan through a specialized prompt that focuses on
    measuring the building footprint using the detected scale.
    Uses detail='high' for maximum precision on measurements.
    """
    prompt = build_prompt_for_page_type("roof_plan_area", scale_info)
    return parse_vision_response(call_vision_api(image_base64, prompt, detail="high"))


def pixel_based_area_estimate(image_base64: str, scale_info: dict, image_width: int, image_height: int) -> dict:
    """Estimate building area using image pixel analysis.

    Uses the known DPI and scale ratio to calculate a pixels-per-foot ratio,
    then asks GPT-4o to estimate the building outline as a fraction of the
    total image. This provides an independent validation of the area measurement.

    How it works:
    - At IMAGE_DPI (120), 1 inch on paper = 120 pixels
    - If scale is 1/8" = 1'-0" (ratio 96), then 1 real foot = 1/8" on paper = 15 pixels
    - So pixels_per_foot = IMAGE_DPI / scale_ratio_denominator
    - If GPT-4o says the building spans ~600 pixels wide, that's 600/15 = 40 feet

    Returns dict with estimated area and confidence, or None if can't compute.
    """
    if not scale_info or not scale_info.get("scale_found"):
        return None

    scale_ratio = scale_info.get("scale_ratio")
    if not scale_ratio or scale_ratio <= 0:
        return None

    # Calculate pixels per real-world foot
    # scale_ratio is the denominator: 1:96 means 1 inch on paper = 96 inches real
    # So 1 foot real = 12/scale_ratio inches on paper = 12/scale_ratio * DPI pixels
    pixels_per_foot = (12.0 / scale_ratio) * IMAGE_DPI

    # Total image coverage in feet
    image_width_ft = image_width / pixels_per_foot
    image_height_ft = image_height / pixels_per_foot
    total_image_area_sqft = image_width_ft * image_height_ft

    print(f"[Vision] Pixel analysis: {pixels_per_foot:.1f} px/ft, "
          f"image covers {image_width_ft:.0f}' x {image_height_ft:.0f}' = {total_image_area_sqft:.0f} sqft")

    return {
        "pixels_per_foot": pixels_per_foot,
        "image_width_ft": image_width_ft,
        "image_height_ft": image_height_ft,
        "total_image_area_sqft": total_image_area_sqft,
    }


def cross_check_roof_area(measurements: list) -> list:
    """Cross-check roof area measurements from different sources.

    When roof_area is found from multiple pages/methods (roof plan measurement
    vs floor plan dimensions), compare them and keep the best one.

    Priority:
    1. Roof plan with scale measurement (highest detail, most accurate for roofing)
    2. Floor plan / slab plan with labeled dimensions (good confirmation)
    3. Any other source

    If discrepancy > 15%, flag it in notes but still keep the primary value.
    """
    roof_area_entries = [m for m in measurements if m.get("type") == "roof_area" and m.get("value", 0) > 0]

    if len(roof_area_entries) <= 1:
        return measurements  # Nothing to cross-check

    # Categorize by source
    roof_plan_areas = []
    floor_plan_areas = []
    other_areas = []

    for entry in roof_area_entries:
        source = (entry.get("notes", "") + " " + entry.get("source", "")).lower()
        method = entry.get("measurement_method", "")
        page_type = entry.get("_source_page_type", "")

        if page_type == "roof_plan" or "roof plan" in source or method in ("scale_measurement", "dimension_lines"):
            roof_plan_areas.append(entry)
        elif page_type in ("floor_plan", "slab_plan") or "floor" in source or "slab" in source or "building dimensions" in source:
            floor_plan_areas.append(entry)
        else:
            other_areas.append(entry)

    print(f"[Vision] Cross-check: {len(roof_plan_areas)} roof plan areas, "
          f"{len(floor_plan_areas)} floor/slab plan areas, {len(other_areas)} other")

    # Pick the primary (prefer roof plan measurement)
    if roof_plan_areas:
        # Among roof plan measurements, prefer highest confidence
        primary = max(roof_plan_areas, key=lambda x: x.get("confidence", 0))
        primary_source = "roof_plan"
    elif floor_plan_areas:
        primary = max(floor_plan_areas, key=lambda x: x.get("confidence", 0))
        primary_source = "floor_plan"
    else:
        primary = max(other_areas, key=lambda x: x.get("confidence", 0))
        primary_source = "other"

    primary_value = primary.get("value", 0)

    # Cross-check against other sources
    all_other = [e for e in roof_area_entries if e is not primary]
    for other in all_other:
        other_value = other.get("value", 0)
        if other_value > 0 and primary_value > 0:
            discrepancy_pct = abs(primary_value - other_value) / primary_value * 100
            other_source_type = other.get("_source_page_type", "unknown")

            if discrepancy_pct <= 5:
                match_label = "EXCELLENT MATCH"
            elif discrepancy_pct <= 15:
                match_label = "GOOD MATCH"
            elif discrepancy_pct <= 30:
                match_label = "MODERATE DISCREPANCY"
            else:
                match_label = "LARGE DISCREPANCY"

            print(f"[Vision] Cross-check: primary={primary_value:.0f} sqft ({primary_source}) vs "
                  f"{other_value:.0f} sqft ({other_source_type}) — {discrepancy_pct:.1f}% difference ({match_label})")

            # Add cross-check note to primary
            existing_notes = primary.get("notes", "")
            cross_note = f"Cross-checked against {other_source_type}: {other_value:.0f} sqft ({discrepancy_pct:.1f}% diff, {match_label})"
            primary["notes"] = f"{existing_notes}; {cross_note}" if existing_notes else cross_note

            # Smart override logic:
            # Floor/slab plans with labeled dimensions are very reliable since
            # they read explicit numbers (e.g., "72'-0" x 72'-0"") rather than
            # measuring by scale. If there's a significant discrepancy, prefer
            # the floor plan dimensions.
            other_is_dimension_source = other_source_type in ("floor_plan", "slab_plan")
            primary_is_scale_based = primary.get("measurement_method") == "scale_measurement"

            if discrepancy_pct > 20 and other_is_dimension_source:
                # Floor plan with labeled dimensions vs roof plan scale measurement:
                # Floor plan dimensions are more reliable (reading numbers vs measuring)
                print(f"[Vision] OVERRIDE: {discrepancy_pct:.0f}% discrepancy — using {other_source_type} "
                      f"dimensions ({other_value:.0f} sqft) over roof plan scale measurement ({primary_value:.0f} sqft)")
                primary["value"] = other_value
                primary["confidence"] = max(other.get("confidence", 0), primary.get("confidence", 0))
                primary["notes"] += f"; OVERRIDDEN: used {other_source_type} labeled dimensions (more reliable than scale measurement)"
                primary_value = other_value  # Update for subsequent comparisons
            elif discrepancy_pct > 30 and other.get("confidence", 0) > primary.get("confidence", 0) + 0.10:
                print(f"[Vision] OVERRIDE: Large discrepancy and {other_source_type} has higher confidence. "
                      f"Using {other_value:.0f} sqft.")
                primary["value"] = other_value
                primary["confidence"] = other.get("confidence", 0)
                primary["notes"] += f"; OVERRIDDEN: used {other_source_type} value due to higher confidence"
                primary_value = other_value
            elif discrepancy_pct <= 15 and other_is_dimension_source:
                # Close match between roof plan and floor plan — great!
                # Boost confidence since two sources agree
                primary["confidence"] = min(0.95, primary.get("confidence", 0) + 0.10)
                primary["notes"] += f"; CONFIRMED by {other_source_type} dimensions (within {discrepancy_pct:.0f}%)"
                print(f"[Vision] CONFIRMED: Roof plan and {other_source_type} agree within {discrepancy_pct:.0f}% — boosting confidence")

    # Remove duplicate roof_area entries, keep only the primary
    non_area = [m for m in measurements if m.get("type") != "roof_area"]
    non_area.append(primary)
    return non_area


# ======================================================================
# Extraction type â RoofCondition mapping
# ======================================================================

EXTRACTION_TO_CONDITION = {
    # From slab plan
    "roof_area": {"condition_type": "field", "unit": "sqft"},
    "parapet_wall": {"condition_type": "edge_detail", "unit": "lnft"},
    "coping": {"condition_type": "edge_detail", "unit": "lnft"},

    # From roof plan
    "roof_drain": {"condition_type": "custom", "unit": "each"},
    "scupper": {"condition_type": "custom", "unit": "each"},
    "pitch_pan": {"condition_type": "custom", "unit": "each"},
    "pipe": {"condition_type": "penetration", "unit": "each"},
    "curb": {"condition_type": "penetration", "unit": "lnft"},

    # From elevations
    "parapet_flashing": {"condition_type": "edge_detail", "unit": "inches"},
    "parapet_flashing_low": {"condition_type": "edge_detail", "unit": "inches"},
    "parapet_flashing_mid": {"condition_type": "edge_detail", "unit": "inches"},
    "parapet_flashing_high": {"condition_type": "edge_detail", "unit": "inches"},
    "collector_head": {"condition_type": "custom", "unit": "each"},
    "downspout": {"condition_type": "custom", "unit": "lnft"},

    # GPT-4o name variations (aliases)
    "building_area": {"condition_type": "field", "unit": "sqft"},
    "building_dimensions": {"condition_type": "field", "unit": "sqft"},
    "roof_drains": {"condition_type": "custom", "unit": "each"},
    "scuppers": {"condition_type": "custom", "unit": "each"},
    "pitch_pans": {"condition_type": "custom", "unit": "each"},
    "pipes": {"condition_type": "penetration", "unit": "each"},
    "curbs": {"condition_type": "penetration", "unit": "lnft"},
    "parapet_flashing_height": {"condition_type": "edge_detail", "unit": "inches"},
    "collector_heads": {"condition_type": "custom", "unit": "each"},
    "downspouts": {"condition_type": "custom", "unit": "lnft"},
    "rooftop_equipment": {"condition_type": "penetration", "unit": "each"},
    "rooftop_equipment_count": {"condition_type": "penetration", "unit": "each"},

    # Legacy types (still supported from older extractions)
    "perimeter": {"condition_type": "perimeter", "unit": "lnft"},
    "penetration": {"condition_type": "penetration", "unit": "each"},
    "flashing": {"condition_type": "edge_detail", "unit": "lnft"},
    "drain": {"condition_type": "custom", "unit": "each"},
    "equipment": {"condition_type": "penetration", "unit": "each"},
    "parapet_height": {"condition_type": "custom", "unit": "inches"},
    "insulation": {"condition_type": "custom", "unit": "inches"},
    "slope": None,
}


def auto_create_conditions(project_id: int, plan_file_id: int, db: Session) -> list:
    """Create RoofCondition records from VisionExtraction records."""
    extractions = db.query(VisionExtraction).filter(
        VisionExtraction.plan_file_id == plan_file_id
    ).all()

    created_conditions = []
    for ext in extractions:
        mapping = EXTRACTION_TO_CONDITION.get(ext.extraction_type)
        if not mapping:
            continue

        description = f"[AI Vision] {ext.extraction_type}"
        if ext.location_on_plan:
            description += f" - {ext.location_on_plan}"
        if ext.confidence_score:
            description += f" (confidence: {ext.confidence_score:.0%})"

        condition = RoofCondition(
            project_id=project_id,
            condition_type=mapping["condition_type"],
            description=description,
            measurement_value=ext.measurement_value,
            measurement_unit=mapping["unit"],
            wind_zone=1,
        )
        db.add(condition)
        db.flush()
        ext.condition_id = condition.id
        created_conditions.append(condition.id)

    db.commit()
    return created_conditions


# ======================================================================
# Page selection: which pages to send for extraction
# ======================================================================

# Page types that are useful for extraction, in priority order
EXTRACTABLE_PAGE_TYPES = [
    "slab_plan",    # Building dimensions -> roof area, parapet wall, coping
    "roof_plan",    # Drains, scuppers, pitch pans, pipes, curbs + area measurement
    "elevation",    # Parapet flashing, collector heads, downspouts
    "floor_plan",   # May have building dimensions like slab plan
    # "detail" EXCLUDED - roof detail pages are reference only, not measured
    "structural",   # May have roof framing dimensions
    "mechanical",   # May have equipment info
    "site_plan",    # May show building footprint
]

# Page types that should be skipped for measurement extraction (reference only)
REFERENCE_ONLY_PAGE_TYPES = {"detail"}


def select_pages_for_extraction(page_images: list, roof_pages: list, page_classifications: dict) -> list:
    """Select the best pages to try extracting measurements from.

    Strategy:
    1. Prioritize slab plans, roof plans, and elevations (the big 3)
    2. Then include pages flagged roof-relevant
    3. Then pages with building dimensions
    4. Fill remaining slots with other extractable page types
    """
    selected = []
    selected_nums = set()

    # Priority 1: The Big 3 page types (slab plan, roof plan, elevation)
    priority_types = ["slab_plan", "roof_plan", "elevation"]
    for p in page_images:
        if len(selected) >= MAX_EXTRACTION_PAGES:
            break
        cls = page_classifications.get(p["page_number"], {})
        if cls.get("page_type") in priority_types:
            selected.append(p)
            selected_nums.add(p["page_number"])
            print(f"[Vision]   Priority page: {p['page_number']} ({cls.get('page_type')})")

    # Priority 2: Other roof-relevant pages
    for p in roof_pages:
        if len(selected) >= MAX_EXTRACTION_PAGES:
            break
        if p["page_number"] not in selected_nums:
            selected.append(p)
            selected_nums.add(p["page_number"])

    # Priority 3: Pages with building dimensions
    for p in page_images:
        if len(selected) >= MAX_EXTRACTION_PAGES:
            break
        if p["page_number"] in selected_nums:
            continue
        cls = page_classifications.get(p["page_number"], {})
        if cls.get("has_building_dimensions"):
            selected.append(p)
            selected_nums.add(p["page_number"])
            print(f"[Vision]   Added page {p['page_number']} (has building dimensions)")

    # Priority 4: Other extractable page types
    for p in page_images:
        if len(selected) >= MAX_EXTRACTION_PAGES:
            break
        if p["page_number"] in selected_nums:
            continue
        cls = page_classifications.get(p["page_number"], {})
        page_type = cls.get("page_type", "")
        if page_type in EXTRACTABLE_PAGE_TYPES:
            selected.append(p)
            selected_nums.add(p["page_number"])

    return selected


# ======================================================================
# Main analysis pipeline
# ======================================================================

def run_plan_analysis(project_id: int, plan_file_id: int, file_path: str, db: Session) -> dict:
    """Full analysis pipeline for a roof plan PDF."""
    plan_file = db.query(RoofPlanFile).filter(RoofPlanFile.id == plan_file_id).first()
    if not plan_file:
        return {"status": "error", "message": "Plan file not found"}

    try:
        # Pre-flight check: verify OpenAI API key is configured
        api_key = os.getenv("OPENAI_API_KEY")
        if not api_key:
            plan_file.upload_status = "failed"
            plan_file.error_message = "OpenAI API key not configured. Set OPENAI_API_KEY environment variable."
            db.commit()
            print("[Vision] ERROR: OPENAI_API_KEY not set")
            return {"status": "error", "message": "OpenAI API key not configured"}

        plan_file.upload_status = "processing"
        db.commit()

        # Step 1: Convert PDF to images
        print(f"[Vision] Converting PDF to images: {file_path}")
        page_images = convert_pdf_to_images(file_path)
        plan_file.page_count = len(page_images)
        db.commit()

        if not page_images:
            plan_file.upload_status = "failed"
            plan_file.error_message = "No pages found in PDF"
            db.commit()
            return {"status": "error", "message": "No pages found in PDF"}

        # Step 2: Classify each page (using detail="low" for speed)
        print(f"[Vision] Classifying {len(page_images)} pages...")
        roof_pages = []
        page_classifications = {}

        for idx, page_data in enumerate(page_images):
            # Heartbeat: update timestamp every 5 pages so stuck detector knows we're alive
            if idx > 0 and idx % 5 == 0:
                plan_file.error_message = f"Classifying pages... ({idx}/{len(page_images)})"
                db.commit()
                print(f"[Vision] Heartbeat: classified {idx}/{len(page_images)} pages")
            page_num = page_data["page_number"]
            print(f"[Vision] Classifying page {page_num}...")
            try:
                classification = classify_page(page_data["image_base64"])
            except Exception as cls_err:
                print(f"[Vision]   Page {page_num}: classification failed - {cls_err}")
                classification = {"page_type": "unknown", "is_roof_relevant": False}

            page_type = classification.get("page_type", "unknown")
            is_relevant = classification.get("is_roof_relevant", False)
            has_dims = classification.get("has_building_dimensions", False)

            # Force key page types as relevant
            if page_type in ("roof_plan", "slab_plan", "structural", "elevation"):
                is_relevant = True

            # Upgrade pages that mention roofing keywords
            if page_type in ("detail", "mechanical", "floor_plan", "site_plan") and not is_relevant:
                notes = classification.get("notes", "").lower()
                title = classification.get("title_block_text", "").lower()
                if any(kw in notes + " " + title for kw in [
                    "roof", "parapet", "flashing", "drain", "slope", "curb",
                    "coping", "membrane", "dimension", "footprint", "building",
                    "scupper", "downspout", "collector"
                ]):
                    is_relevant = True
                    print(f"[Vision]   -> Upgraded page {page_num} to roof-relevant based on content keywords")

            # Floor plans with dimensions are useful for roof area
            if page_type == "floor_plan" and has_dims:
                is_relevant = True
                print(f"[Vision]   -> Floor plan with dimensions - marking as roof-relevant")

            # Site plans with dimensions can show building footprint
            if page_type == "site_plan" and has_dims:
                is_relevant = True

            # Store classification
            page_classifications[page_num] = {
                "page_type": page_type,
                "is_roof_relevant": is_relevant,
                "has_building_dimensions": has_dims,
            }

            page_analysis = PlanPageAnalysis(
                plan_file_id=plan_file_id,
                page_number=page_num,
                page_type=page_type,
                is_roof_relevant=is_relevant,
                analysis_json=json.dumps(classification),
                processing_status="completed",
            )
            db.add(page_analysis)

            if is_relevant:
                roof_pages.append(page_data)
                print(f"[Vision]   -> Page {page_num}: {page_type} (ROOF RELEVANT)")
            else:
                print(f"[Vision]   -> Page {page_num}: {page_type}")

        db.commit()

        # Log page type summary
        type_counts = {}
        for pc in page_classifications.values():
            pt = pc["page_type"]
            type_counts[pt] = type_counts.get(pt, 0) + 1
        print(f"[Vision] Page type summary: {type_counts}")

        # Step 2b: Select pages for extraction
        pages_to_extract = select_pages_for_extraction(page_images, roof_pages, page_classifications)
        extract_page_nums = [p["page_number"] for p in pages_to_extract]
        print(f"[Vision] Pages selected for extraction: {extract_page_nums}")

        # Steps 3+4 merged: Detect scale PER-PAGE and extract measurements.
        # Different sheets in a commercial plan set can have different scales
        # (e.g., roof plan at 1/16"=1', detail at 3/8"=1').
        all_measurements = []
        pages_with_extractions = []
        file_scale_info = {"scale_found": False}  # Best/first scale for file-level display
        page_scales = {}  # page_num -> scale_info for per-page tracking

        # Check for manual scale override (user-set scale takes priority)
        manual_scale_info = None
        if plan_file.manual_scale and plan_file.manual_scale_ratio:
            manual_scale_info = {
                "scale_found": True,
                "scale_notation": plan_file.manual_scale,
                "scale_ratio": plan_file.manual_scale_ratio,
                "confidence": 1.0,
                "is_manual": True,
                "notes": "Manual scale set by user (overrides AI detection)",
            }
            file_scale_info = manual_scale_info
            plan_file.detected_scale = f"{plan_file.manual_scale} (manual)"
            plan_file.scale_confidence = 1.0
            db.commit()
            print(f"[Vision] Using MANUAL scale override: {plan_file.manual_scale} (ratio 1:{plan_file.manual_scale_ratio})")

        for ext_idx, page_data in enumerate(pages_to_extract):
            page_num = page_data["page_number"]
            page_type = page_classifications.get(page_num, {}).get("page_type", "unknown")
            print(f"[Vision] Processing page {page_num} (type: {page_type})...")

            # Heartbeat: keep updated_at fresh so stuck detector doesn't kill us
            plan_file.error_message = f"Extracting measurements... (page {ext_idx + 1}/{len(pages_to_extract)})"
            db.commit()

            # Detect scale for THIS specific page
            # Skip AI detection if manual scale is set (user override takes priority)
            if manual_scale_info:
                page_scale = manual_scale_info
                print(f"[Vision]   Page {page_num}: using manual scale override")
            else:
                try:
                    page_scale = detect_scale(page_data["image_base64"])
                except Exception as scale_err:
                    print(f"[Vision]   Page {page_num}: scale detection failed - {scale_err}")
                    page_scale = {"scale_found": False}

            if page_scale.get("scale_found"):
                page_scales[page_num] = page_scale
                print(f"[Vision]   Page {page_num}: scale = {page_scale.get('scale_notation')} "
                      f"(ratio 1:{page_scale.get('scale_ratio')}, "
                      f"raw_text: {page_scale.get('scale_text_as_read', 'n/a')}, "
                      f"confidence: {page_scale.get('confidence', 0):.0%})")
                # Update file-level scale with the first (or highest-confidence) found
                if not file_scale_info.get("scale_found") or \
                   page_scale.get("confidence", 0) > file_scale_info.get("confidence", 0):
                    file_scale_info = page_scale
                    plan_file.detected_scale = page_scale.get("scale_notation")
                    plan_file.scale_confidence = page_scale.get("confidence", 0.0)
                    db.commit()
            else:
                print(f"[Vision]   Page {page_num}: no scale found, using fallback")

            # Use page-specific scale if found, otherwise fall back to best file-level scale
            scale_for_extraction = page_scale if page_scale.get("scale_found") else file_scale_info

            # Extract measurements using page-type-specific prompt
            try:
                measurements_result = extract_measurements_for_page(
                    page_data["image_base64"], page_type, scale_for_extraction
                )
            except Exception as page_err:
                print(f"[Vision]   Page {page_num}: extraction failed - {page_err}")
                measurements_result = {"measurements": []}

            if "error" in measurements_result:
                print(f"[Vision]   Page {page_num}: extraction error - {measurements_result.get('error')}")
                measurements_result = {"measurements": []}

            page_measurements = measurements_result.get("measurements", [])

            # === ROOF PLAN AREA MEASUREMENT (new dual extraction) ===
            # For roof plan pages, ALSO run the dedicated area measurement prompt.
            # This measures the building footprint using the scale — the primary
            # method for getting accurate square footage.
            if page_type == "roof_plan":
                print(f"[Vision]   Page {page_num}: Running dedicated roof plan AREA measurement...")
                try:
                    area_result = measure_roof_plan_area(
                        page_data["image_base64"], scale_for_extraction
                    )
                    if area_result and "error" not in area_result:
                        area_measurements = area_result.get("measurements", [])
                        method = area_result.get("measurement_method", "unknown")
                        dims_labeled = area_result.get("dimensions_labeled", False)
                        building_shape = area_result.get("building_shape", "unknown")
                        scale_used = area_result.get("scale_used", "unknown")
                        scale_text = area_result.get("scale_text_on_drawing", "unknown")
                        print(f"[Vision]   Page {page_num}: Area measurement found {len(area_measurements)} items "
                              f"(method: {method}, dims_labeled: {dims_labeled}, shape: {building_shape}, "
                              f"scale_used: {scale_used}, scale_on_drawing: {scale_text})")
                        for am in area_measurements:
                            am["_source_page_type"] = "roof_plan"
                            am["measurement_method"] = method
                        page_measurements.extend(area_measurements)

                        # Pixel-based validation
                        pixel_info = pixel_based_area_estimate(
                            page_data["image_base64"],
                            scale_for_extraction,
                            page_data.get("width", 0),
                            page_data.get("height", 0),
                        )
                        if pixel_info:
                            # The total image area gives an upper bound for the building
                            total_img_area = pixel_info.get("total_image_area_sqft", 0)
                            roof_area_vals = [m["value"] for m in area_measurements if m.get("type") == "roof_area" and m.get("value", 0) > 0]
                            if roof_area_vals:
                                measured_area = roof_area_vals[0]
                                # Building should be less than 80% of image area
                                # (the drawing includes borders, title block, etc.)
                                if total_img_area > 0 and measured_area > total_img_area * 0.85:
                                    print(f"[Vision]   WARNING: Measured area {measured_area:.0f} sqft exceeds "
                                          f"85% of drawable image area {total_img_area:.0f} sqft — measurement may be inflated")
                                elif total_img_area > 0 and measured_area < total_img_area * 0.02:
                                    print(f"[Vision]   WARNING: Measured area {measured_area:.0f} sqft is less than "
                                          f"2% of drawable image area {total_img_area:.0f} sqft — measurement may be too small")
                                else:
                                    ratio = measured_area / total_img_area * 100 if total_img_area > 0 else 0
                                    print(f"[Vision]   Pixel validation: building covers ~{ratio:.0f}% of drawable area (reasonable)")
                    else:
                        print(f"[Vision]   Page {page_num}: Area measurement returned error or empty")
                except Exception as area_err:
                    print(f"[Vision]   Page {page_num}: Area measurement failed - {area_err}")

            # Tag floor plan / slab plan measurements for cross-check
            if page_type in ("floor_plan", "slab_plan"):
                for m in page_measurements:
                    m["_source_page_type"] = page_type

            if page_measurements:
                print(f"[Vision]   Page {page_num}: found {len(page_measurements)} total measurements")
                page_scale_label = scale_for_extraction.get("scale_notation", "unknown")
                for m in page_measurements:
                    m["_page_number"] = page_num
                    m["_page_scale"] = page_scale_label
                    print(f"[Vision]     - {m.get('type')}: {m.get('value')} {m.get('unit')} (scale: {page_scale_label})")
                all_measurements.extend(page_measurements)
                pages_with_extractions.append(page_num)
            else:
                print(f"[Vision]   Page {page_num}: no measurements found")

        # Extended search: if we got very few extractions, try remaining pages
        if len(all_measurements) < 3:
            tried_pages = {p["page_number"] for p in pages_to_extract}
            remaining = [p for p in page_images if p["page_number"] not in tried_pages]
            if remaining:
                print(f"[Vision] Few extractions so far - trying {len(remaining)} remaining pages...")
                plan_file.error_message = f"Extended search... ({len(remaining)} extra pages)"
                db.commit()
                for page_data in remaining:
                    page_num = page_data["page_number"]
                    cls = page_classifications.get(page_num, {})
                    if cls.get("page_type") == "cover_sheet":
                        continue
                    page_type = cls.get("page_type", "unknown")
                    print(f"[Vision] Extended search: page {page_num} (type: {page_type})...")
                    # Detect per-page scale for extended search pages too
                    try:
                        page_scale = detect_scale(page_data["image_base64"])
                    except Exception:
                        page_scale = {"scale_found": False}
                    scale_for_ext = page_scale if page_scale.get("scale_found") else file_scale_info
                    try:
                        measurements_result = extract_measurements_for_page(
                            page_data["image_base64"], page_type, scale_for_ext
                        )
                    except Exception as ext_err:
                        print(f"[Vision]   Extended search page {page_num}: API call failed - {ext_err}")
                        continue
                    if "error" not in measurements_result:
                        page_measurements = measurements_result.get("measurements", [])
                        if page_measurements:
                            print(f"[Vision]   Page {page_num}: found {len(page_measurements)} measurements!")
                            for m in page_measurements:
                                m["_page_number"] = page_num
                                print(f"[Vision]     - {m.get('type')}: {m.get('value')} {m.get('unit')}")
                            all_measurements.extend(page_measurements)
                            pages_with_extractions.append(page_num)

        print(f"[Vision] Total raw measurements found: {len(all_measurements)} from pages {pages_with_extractions}")

        # Heartbeat: we made it past the extraction loop
        plan_file.error_message = f"Saving {len(all_measurements)} measurements..."
        db.commit()

        # Cross-check roof area measurements from different sources
        # (roof plan scale measurement vs floor plan dimensions)
        all_measurements = cross_check_roof_area(all_measurements)

        print(f"[Vision] Extraction loop complete. Deduplicating...")

        # Step 5: Deduplicate and store extractions
        # For "eaches" items: sum across pages (e.g., drains on multiple elevations)
        # For area/length items: keep highest confidence
        SUMMABLE_TYPES = {"roof_drain", "scupper", "pitch_pan", "pipe", "collector_head"}
        KEEP_ALL_TYPES = {"parapet_flashing", "parapet_flashing_low", "parapet_flashing_mid", "parapet_flashing_high"}

        best_by_type = {}
        sums_by_type = {}

        for m in all_measurements:
            ext_type = m.get("type", "custom")
            confidence = m.get("confidence", 0.5)
            value = m.get("value", 0)

            # Skip zero-value measurements
            if value == 0:
                continue

            if ext_type in SUMMABLE_TYPES:
                # For countable items found on DIFFERENT pages, keep the max count per page
                # (same items may appear on the same page, so don't double-count within a page)
                # But if found on different pages (e.g., drains on roof plan + detail),
                # take the higher count since they likely show the same drains
                if ext_type not in best_by_type or confidence > best_by_type[ext_type].get("confidence", 0):
                    best_by_type[ext_type] = m
            elif ext_type in KEEP_ALL_TYPES:
                # Parapet flashing heights: keep each distinct height
                key = f"{ext_type}_{value}"
                if key not in best_by_type:
                    best_by_type[key] = m
            else:
                # For area/length measurements: keep highest confidence
                if ext_type not in best_by_type or confidence > best_by_type[ext_type].get("confidence", 0):
                    best_by_type[ext_type] = m

        # Round downspouts to nearest 10 lnft
        if "downspout" in best_by_type:
            ds = best_by_type["downspout"]
            raw_val = ds.get("value", 0)
            rounded = round(raw_val / 10) * 10
            if rounded == 0 and raw_val > 0:
                rounded = 10
            ds["value"] = rounded
            print(f"[Vision] Downspout rounded: {raw_val} -> {rounded} lnft")

        extraction_count = 0
        overall_confidence = 0.0
        for key, m in best_by_type.items():
            ext_type = m.get("type", "custom")
            value = m.get("value", 0)
            unit = m.get("unit", "each")

            is_valid, conf_multiplier, warning = validate_extraction(ext_type, value)
            confidence = m.get("confidence", 0.5) * conf_multiplier

            if not is_valid:
                print(f"[Vision] Warning: {warning}")

            extraction = VisionExtraction(
                plan_file_id=plan_file_id,
                page_number=m.get("_page_number", 1),
                extraction_type=ext_type,
                measurement_value=value,
                measurement_unit=unit,
                confidence_score=confidence,
                source_description=m.get("source", ""),
                location_on_plan=m.get("location", ""),
                notes=f"scale: {m.get('_page_scale', 'unknown')}" + (f"; {m.get('notes')}" if m.get("notes") else ""),
            )
            db.add(extraction)
            extraction_count += 1
            overall_confidence += confidence

        db.commit()

        if extraction_count > 0:
            overall_confidence = overall_confidence / extraction_count

        # Step 6: Auto-create conditions
        plan_file.error_message = f"Creating conditions from {extraction_count} extractions..."
        db.commit()
        print("[Vision] Auto-creating conditions...")
        created_condition_ids = auto_create_conditions(project_id, plan_file_id, db)

        plan_file.upload_status = "completed"
        plan_file.error_message = None  # Clear any progress messages
        db.commit()

        result = {
            "status": "success",
            "plan_file_id": plan_file_id,
            "pages_analyzed": len(page_images),
            "roof_pages_found": len(roof_pages),
            "pages_extracted_from": pages_with_extractions,
            "scale_detected": file_scale_info.get("scale_found", False),
            "scale": file_scale_info.get("scale_notation"),
            "page_scales": {str(k): v.get("scale_notation") for k, v in page_scales.items()},
            "extractions_count": extraction_count,
            "conditions_created": len(created_condition_ids),
            "condition_ids": created_condition_ids,
            "overall_confidence": overall_confidence,
        }
        print(f"[Vision] Analysis complete: {result}")
        return result

    except Exception as e:
        plan_file.upload_status = "failed"
        plan_file.error_message = str(e)[:500]
        db.commit()
        print(f"[Vision] Analysis failed: {e}")
        return {"status": "error", "message": str(e)[:500]}


def run_plan_analysis_background(project_id: int, plan_file_id: int, file_path: str):
    """Background task wrapper. Creates its own DB session.

    Ensures plan_file status is ALWAYS updated, even if the analysis crashes
    with an unexpected error (OOM, missing env vars, import errors, etc.)
    """
    db = SessionLocal()
    try:
        run_plan_analysis(project_id, plan_file_id, file_path, db)
    except Exception as e:
        # Catch-all: if run_plan_analysis itself raises (shouldn't happen
        # since it has its own try/except, but this is a safety net)
        print(f"[Vision] Background task crashed for plan_file {plan_file_id}: {e}")
        try:
            plan_file = db.query(RoofPlanFile).filter(RoofPlanFile.id == plan_file_id).first()
            if plan_file and plan_file.upload_status not in ("completed", "failed"):
                plan_file.upload_status = "failed"
                plan_file.error_message = f"Background task crashed: {str(e)[:400]}"
                db.commit()
        except Exception as inner_e:
            print(f"[Vision] Failed to update status after crash: {inner_e}")
    finally:
        try:
            db.close()
        except Exception:
            pass
        # Clean up temp file
        try:
            import os
            if file_path and os.path.exists(file_path):
                os.unlink(file_path)
                parent = os.path.dirname(file_path)
                if parent and os.path.isdir(parent):
                    os.rmdir(parent)
        except Exception:
            pass
