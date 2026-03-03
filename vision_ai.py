"""
Core AI Vision analysis engine for reading architectural roof plans.
Converts PDF pages to images, sends to GPT-4o vision, extracts measurements,
and auto-creates RoofCondition records.
"""

import os
import io
import json
import base64
import fitz  # PyMuPDF
from PIL import Image
from openai import OpenAI
from sqlalchemy.orm import Session

from database import SessionLocal
from vision_models import RoofPlanFile, PlanPageAnalysis, VisionExtraction
from conditions_models import RoofCondition
from vision_prompts import (
    PAGE_TYPE_PROMPT,
    SCALE_DETECTION_PROMPT,
    build_measurement_prompt_with_scale,
    build_bidset_prompt_with_scale,
    parse_vision_response,
    validate_extraction,
)

client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

MAX_PAGES = 20
IMAGE_DPI = 150
MAX_IMAGE_SIZE_MB = 4.0
VISION_MODEL = "gpt-4o"
MAX_EXTRACTION_PAGES = 8  # Analyze up to 8 pages for measurements


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


def call_vision_api(image_base64: str, prompt: str) -> str:
    """Send an image to GPT-4o vision and return the response text."""
    response = client.chat.completions.create(
        model=VISION_MODEL,
        messages=[{
            "role": "user",
            "content": [
                {"type": "text", "text": prompt},
                {"type": "image_url", "image_url": {
                    "url": f"data:image/jpeg;base64,{image_base64}",
                    "detail": "high",
                }},
            ],
        }],
        max_tokens=2000,
        temperature=0.1,
    )
    return response.choices[0].message.content


def classify_page(image_base64: str) -> dict:
    """Use GPT-4o to classify what type of architectural page this is."""
    return parse_vision_response(call_vision_api(image_base64, PAGE_TYPE_PROMPT))


def detect_scale(image_base64: str) -> dict:
    """Use GPT-4o to find and parse the drawing scale."""
    return parse_vision_response(call_vision_api(image_base64, SCALE_DETECTION_PROMPT))


def extract_measurements(image_base64: str, scale_info: dict) -> dict:
    """Use GPT-4o to extract all roof measurements from the plan page."""
    prompt = build_measurement_prompt_with_scale(scale_info)
    return parse_vision_response(call_vision_api(image_base64, prompt))


def extract_measurements_aggressive(image_base64: str, scale_info: dict) -> dict:
    """Use GPT-4o with aggressive bid set prompt for any page type."""
    prompt = build_bidset_prompt_with_scale(scale_info)
    return parse_vision_response(call_vision_api(image_base64, prompt))


EXTRACTION_TO_CONDITION = {
    "roof_area": {"condition_type": "field", "unit": "sqft"},
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


def select_pages_for_extraction(page_images: list, roof_pages: list, page_classifications: dict) -> list:
    """Select the best pages to try extracting measurements from.

    Strategy:
    1. Use roof-relevant pages first (up to MAX_EXTRACTION_PAGES)
    2. Also include pages that have building dimensions (floor plans, site plans)
    3. If still not enough, use smart fallback across the document
    """
    selected = []
    selected_nums = set()

    # First: roof-relevant pages
    for p in roof_pages:
        if len(selected) >= MAX_EXTRACTION_PAGES:
            break
        selected.append(p)
        selected_nums.add(p["page_number"])

    # Second: pages with building dimensions (from classification)
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

    # Third: floor_plan and site_plan pages (likely to have building footprint)
    for p in page_images:
        if len(selected) >= MAX_EXTRACTION_PAGES:
            break
        if p["page_number"] in selected_nums:
            continue
        cls = page_classifications.get(p["page_number"], {})
        page_type = cls.get("page_type", "")
        if page_type in ("floor_plan", "site_plan", "elevation", "mechanical"):
            selected.append(p)
            selected_nums.add(p["page_number"])

    # Fourth: if we still have very few, add remaining non-cover pages
    if len(selected) < 3:
        for p in page_images:
            if len(selected) >= MAX_EXTRACTION_PAGES:
                break
            if p["page_number"] in selected_nums:
                continue
            cls = page_classifications.get(p["page_number"], {})
            page_type = cls.get("page_type", "")
            if page_type not in ("cover_sheet",):
                selected.append(p)
                selected_nums.add(p["page_number"])

    return selected


def run_plan_analysis(project_id: int, plan_file_id: int, file_path: str, db: Session) -> dict:
    """Full analysis pipeline for a roof plan PDF."""
    plan_file = db.query(RoofPlanFile).filter(RoofPlanFile.id == plan_file_id).first()
    if not plan_file:
        return {"status": "error", "message": "Plan file not found"}

    try:
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

        # Step 2: Classify each page
        print(f"[Vision] Classifying {len(page_images)} pages...")
        roof_pages = []
        page_classifications = {}  # Store full classification by page number

        for page_data in page_images:
            page_num = page_data["page_number"]
            print(f"[Vision] Classifying page {page_num}...")
            classification = classify_page(page_data["image_base64"])

            page_type = classification.get("page_type", "unknown")
            is_relevant = classification.get("is_roof_relevant", False)
            has_dims = classification.get("has_building_dimensions", False)

            # Force roof_plan and structural pages as relevant
            if page_type in ("roof_plan", "structural"):
                is_relevant = True

            # Also consider elevation, detail, mechanical, floor_plan as potentially relevant
            if page_type in ("elevation", "detail", "mechanical", "floor_plan") and not is_relevant:
                notes = classification.get("notes", "").lower()
                title = classification.get("title_block_text", "").lower()
                if any(kw in notes + " " + title for kw in [
                    "roof", "parapet", "flashing", "drain", "slope", "curb",
                    "coping", "membrane", "dimension", "footprint", "building"
                ]):
                    is_relevant = True
                    print(f"[Vision]   -> Upgraded page {page_num} to roof-relevant based on content keywords")

            # Floor plans with dimensions are always useful for commercial roofing
            if page_type == "floor_plan" and has_dims:
                is_relevant = True
                print(f"[Vision]   -> Floor plan with dimensions - marking as roof-relevant")

            # Site plans with dimensions can show building footprint
            if page_type == "site_plan" and has_dims:
                is_relevant = True
                print(f"[Vision]   -> Site plan with dimensions - marking as roof-relevant")

            # Store classification for page selection
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

        # Determine if this is a bid set without a dedicated roof plan
        has_dedicated_roof_plan = any(
            page_classifications[p["page_number"]].get("page_type") == "roof_plan"
            for p in roof_pages
        ) if roof_pages else False

        is_bid_set_mode = not has_dedicated_roof_plan
        if is_bid_set_mode:
            print("[Vision] ** BID SET MODE ** No dedicated roof plan found - using aggressive extraction")

        # Step 2b: Select pages for extraction (uses smarter selection now)
        pages_to_extract = select_pages_for_extraction(page_images, roof_pages, page_classifications)
        extract_page_nums = [p["page_number"] for p in pages_to_extract]
        print(f"[Vision] Pages selected for extraction: {extract_page_nums}")

        # Step 3: Detect scale (try multiple pages)
        print("[Vision] Detecting scale...")
        scale_info = {"scale_found": False}
        # Try all extraction pages for scale, not just first 3
        for page_data in pages_to_extract:
            scale_info = detect_scale(page_data["image_base64"])
            if scale_info.get("scale_found"):
                plan_file.detected_scale = scale_info.get("scale_notation")
                plan_file.scale_confidence = scale_info.get("confidence", 0.0)
                print(f"[Vision]   Scale found on page {page_data['page_number']}: {scale_info.get('scale_notation')}")
                db.commit()
                break
            else:
                print(f"[Vision]   No scale found on page {page_data['page_number']}, trying next...")

        # Step 4: Extract measurements from selected pages
        all_measurements = []
        pages_with_extractions = []

        for page_data in pages_to_extract:
            page_num = page_data["page_number"]
            print(f"[Vision] Extracting measurements from page {page_num}...")

            # Use aggressive prompt for bid set mode, standard for normal mode
            if is_bid_set_mode:
                measurements_result = extract_measurements_aggressive(page_data["image_base64"], scale_info)
            else:
                measurements_result = extract_measurements(page_data["image_base64"], scale_info)

            if "error" in measurements_result:
                print(f"[Vision]   Page {page_num}: extraction error - {measurements_result.get('error')}")
                continue

            page_measurements = measurements_result.get("measurements", [])
            if page_measurements:
                print(f"[Vision]   Page {page_num}: found {len(page_measurements)} measurements")
                for m in page_measurements:
                    m["_page_number"] = page_num
                all_measurements.extend(page_measurements)
                pages_with_extractions.append(page_num)
            else:
                print(f"[Vision]   Page {page_num}: no measurements found")

        # If still no measurements, try ALL remaining pages with aggressive prompt
        if not all_measurements:
            tried_pages = {p["page_number"] for p in pages_to_extract}
            remaining = [p for p in page_images if p["page_number"] not in tried_pages]
            if remaining:
                print(f"[Vision] No measurements yet - trying {len(remaining)} remaining pages with aggressive extraction...")
                for page_data in remaining:
                    page_num = page_data["page_number"]
                    cls = page_classifications.get(page_num, {})
                    # Skip cover sheets in extended search
                    if cls.get("page_type") == "cover_sheet":
                        continue
                    print(f"[Vision] Extracting from page {page_num} (extended search)...")
                    measurements_result = extract_measurements_aggressive(page_data["image_base64"], scale_info)
                    if "error" not in measurements_result:
                        page_measurements = measurements_result.get("measurements", [])
                        if page_measurements:
                            print(f"[Vision]   Page {page_num}: found {len(page_measurements)} measurements!")
                            for m in page_measurements:
                                m["_page_number"] = page_num
                            all_measurements.extend(page_measurements)
                            pages_with_extractions.append(page_num)
                            # Don't break - keep searching for more data

        print(f"[Vision] Total raw measurements found: {len(all_measurements)} from pages {pages_with_extractions}")

        # Step 5: Store extractions (deduplicate by type, keep highest confidence)
        best_by_type = {}
        for m in all_measurements:
            ext_type = m.get("type", "custom")
            confidence = m.get("confidence", 0.5)
            value = m.get("value", 0)

            # Skip zero-value measurements
            if value == 0:
                continue

            if ext_type not in best_by_type or confidence > best_by_type[ext_type].get("confidence", 0):
                best_by_type[ext_type] = m

        extraction_count = 0
        overall_confidence = 0.0
        for ext_type, m in best_by_type.items():
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
                notes=m.get("notes", ""),
            )
            db.add(extraction)
            extraction_count += 1
            overall_confidence += confidence

        db.commit()

        if extraction_count > 0:
            overall_confidence = overall_confidence / extraction_count

        # Step 6: Auto-create conditions
        print("[Vision] Auto-creating conditions...")
        created_condition_ids = auto_create_conditions(project_id, plan_file_id, db)

        plan_file.upload_status = "completed"
        db.commit()

        result = {
            "status": "success",
            "plan_file_id": plan_file_id,
            "pages_analyzed": len(page_images),
            "roof_pages_found": len(roof_pages),
            "bid_set_mode": is_bid_set_mode,
            "pages_extracted_from": pages_with_extractions,
            "scale_detected": scale_info.get("scale_found", False),
            "scale": scale_info.get("scale_notation"),
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
    """Background task wrapper. Creates its own DB session."""
    db = SessionLocal()
    try:
        run_plan_analysis(project_id, plan_file_id, file_path, db)
    finally:
        db.close()
