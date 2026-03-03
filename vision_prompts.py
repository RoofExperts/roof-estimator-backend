"""
GPT-4o Vision prompt templates for architectural roof plan analysis.
"""

import json
import re


PAGE_TYPE_PROMPT = """You are analyzing a page from an architectural drawing set for a commercial building.
Your job is to classify this page AND determine if it contains any roof-related information.

Classify this page into one of the following types:
- roof_plan: Shows the roof layout from above with dimensions, slopes, drains, penetrations, crickets, tapered insulation, or roofing notes
- structural: Shows structural framing, beams, columns, joists, or decking (may include roof framing)
- foundation: Shows the building foundation/slab plan
- elevation: Shows a side view of the building (may show roof edge, parapet, or slope)
- detail: Shows close-up construction details (flashing, curbs, edge details, roof assembly sections)
- mechanical: Shows HVAC equipment layout (may show rooftop units)
- site_plan: Shows the overall site/property layout with building footprints
- floor_plan: Shows interior room layout, doors, walls with building dimensions
- cover_sheet: Title page, project info, drawing index
- general_notes: Specifications, abbreviations, symbols legend
- unknown: Cannot determine the page type

IMPORTANT: Set is_roof_relevant = true if the page contains ANY of the following:
- Roof plan view (overhead view showing roof areas, slopes, drains, crickets)
- Roof framing plan (joists, beams, decking layout at roof level)
- Building sections showing roof assembly or slope
- Roof detail drawings (flashing, edge, curb, drain, penetration details)
- Elevation views showing roof line, parapet, slope, or roofing materials
- Mechanical plans showing rooftop equipment placement
- Any annotations about roofing materials, insulation, or membrane
- Sheet numbers containing A5, A6, S3, S4, or similar roof-level sheets
- Title block text mentioning "roof", "roofing", "top of", "parapet"

ALSO set is_roof_relevant = true if:
- The page shows a BUILDING FOOTPRINT from above with dimensions (this IS useful for roof area)
- The page is a FLOOR PLAN showing overall building width/length dimensions
- The page shows building outline dimensions from any angle
- The page has a SITE PLAN that shows building footprint dimensions or square footage
- The page mentions any roofing specification, even in notes text

Be VERY GENEROUS with is_roof_relevant. When in doubt, set it to TRUE.
For a commercial bid set, ANY page showing building dimensions is useful for roof estimation.

Also set has_building_dimensions = true if the page has any dimension strings (e.g., 120'-0", 85', etc.) showing building width, length, or area.

Respond with ONLY this JSON (no other text):
{
    "page_type": "floor_plan",
    "confidence": 0.85,
    "title_block_text": "A1.1 - FLOOR PLAN",
    "is_roof_relevant": true,
    "has_building_dimensions": true,
    "notes": "Floor plan showing building dimensions of 120' x 85' which can be used for roof area"
}"""


SCALE_DETECTION_PROMPT = """You are analyzing an architectural drawing page.
Find the scale of this drawing.

Look for:
1. A graphical scale bar (a line with measurement markings)
2. Text stating the scale (e.g., 1/8" = 1'-0", SCALE: 1/4" = 1', 1:100)
3. Title block information that includes scale
4. Multiple scales if different areas have different scales
5. ANY text that mentions feet, inches, or scale ratios

Common architectural scales:
- 1/8" = 1'-0" (1:96) - most common for roof plans
- 3/16" = 1'-0" (1:64)
- 1/4" = 1'-0" (1:48) - common for larger detail
- 1/16" = 1'-0" (1:192) - used for large buildings
- 3/32" = 1'-0" (1:128) - sometimes used for commercial

Respond with ONLY this JSON (no other text):
{
    "scale_found": true,
    "scale_notation": "1/8 inch = 1 foot",
    "scale_ratio": 96,
    "scale_location": "title block, bottom right",
    "confidence": 0.90,
    "notes": "Scale clearly marked in title block"
}"""


MEASUREMENT_EXTRACTION_PROMPT = """You are a commercial roofing estimator analyzing an architectural drawing page.
Extract ALL measurable roof information you can find on this page.

{scale_context}

IMPORTANT: This page may or may not be a dedicated roof plan. Extract whatever roofing-related measurements you can find, including:

1. ROOF AREA (sqft): Total roof surface area from dimensions. If you see building dimensions from above, calculate the area.
2. PERIMETER (lnft): Total building perimeter at roof level
3. PENETRATIONS: Count all roof penetrations (pipes, vents, HVAC curbs, exhaust fans) - NOT drains
4. FLASHING/EDGE DETAILS (lnft): Total linear feet needing flashing (coping, gravel stop, drip edge)
5. ROOF SLOPE: Slope angle or pitch (look for slope arrows, cricket slopes, tapered insulation diagrams)
6. DRAINS: Count roof drains (circles with crosshairs, leaders) and scuppers
7. OTHER: Expansion joints, area dividers, skylights, equipment screens, hatches, walkway pads

TIPS FOR COMMERCIAL PLANS:
- Building outlines shown from above usually indicate roof area - measure them
- Look for dimension strings along the building edges
- HVAC units shown on roof are penetrations requiring curbs
- Parapet walls around edges indicate perimeter needing coping/flashing
- Even if this is not labeled as a roof plan, extract any dimensions you can see
- If you see a building footprint with dimensions, calculate the roof area from those

If you find NO measurable information on this page at all, return:
{"measurements": [], "overall_confidence": 0.0, "drawing_quality": "not_applicable", "notes": "No roofing measurements found on this page"}

Otherwise, respond with ONLY this JSON (no other text):
{
    "measurements": [
        {
            "type": "roof_area",
            "value": 12500,
            "unit": "sqft",
            "confidence": 0.90,
            "source": "Calculated from 125' x 100' main section",
            "location": "Main roof area",
            "notes": "Single rectangular section clearly dimensioned"
        }
    ],
    "overall_confidence": 0.85,
    "drawing_quality": "good",
    "notes": "Clear roof plan with most dimensions labeled."
}"""


# More aggressive prompt for bid sets without a dedicated roof plan page
BID_SET_EXTRACTION_PROMPT = """You are a commercial roofing estimator. This architectural drawing may NOT be a roof plan, but you need to extract ANY information useful for roofing estimation.

{scale_context}

YOUR MISSION: Find building dimensions, equipment counts, or any other measurements that help estimate roofing work. Be AGGRESSIVE in looking for data.

LOOK FOR THESE THINGS ON ANY PAGE TYPE:

FLOOR PLANS / SITE PLANS:
- Building overall dimensions (length x width) → calculate roof area as length × width
- Building footprint outline → estimate area from the shape
- Multiple wings or sections → add up each section
- Dimension strings along walls (e.g., "120'-0"", "85'-4"")
- Area callouts (e.g., "12,500 SF", "BLDG AREA: 8,000 SF")
- Room dimensions that span the whole building width/length

ELEVATION VIEWS:
- Building width from side views
- Parapet wall height (useful for flashing length)
- Roof slope or pitch indicators
- Number of stories (affects access costs)

DETAIL PAGES:
- Roof assembly details (membrane type, insulation thickness)
- Flashing details (type of edge metal, coping size)
- Drain details (drain size, type)
- Curb/penetration details

MECHANICAL / EQUIPMENT PLANS:
- Count of rooftop HVAC units
- Equipment sizes for curb calculations
- Ductwork penetrations through roof

GENERAL NOTES / SPECIFICATIONS:
- Roofing specification references (Section 07 52 00, etc.)
- Material specifications (TPO, EPDM, modified bitumen)
- Insulation R-value or thickness
- Slope requirements mentioned in text
- Warranty requirements

DIMENSION READING TIPS:
- Look for numbers with foot marks: 120'-0", 85'-4", 200'
- Look for numbers with dash formatting: 120-0, 85-4
- Look for dimension lines with arrows at both ends
- A rectangle that is 120' x 85' has area = 10,200 sqft and perimeter = 410 lnft
- If you see partial dimensions, still report them with lower confidence

Report ANY of these measurement types you can find:
- roof_area (sqft) - from building footprint or dimensions
- perimeter (lnft) - sum of all outside edges
- penetration (each) - count of roof penetrations, HVAC units, pipes, vents
- flashing (lnft) - coping, edge metal, curb flashing
- slope (in_per_ft) - roof slope
- drain (each) - roof drains, scuppers
- parapet_height (inches) - height of parapet walls
- insulation (inches) - insulation thickness
- equipment (each) - rooftop equipment count

If you find dimensions that give building area, ALWAYS calculate and report roof_area AND perimeter.

If you find NOTHING useful at all, return:
{"measurements": [], "overall_confidence": 0.0, "notes": "No useful measurements found"}

Otherwise respond with ONLY JSON:
{
    "measurements": [
        {"type": "roof_area", "value": 10200, "unit": "sqft", "confidence": 0.75, "source": "Building dimensions 120' x 85' from floor plan", "location": "Main building", "notes": "Calculated from building footprint dimensions"},
        {"type": "perimeter", "value": 410, "unit": "lnft", "confidence": 0.75, "source": "Building perimeter from dimensions", "location": "Building edges", "notes": "2*(120+85) = 410 lnft"}
    ],
    "overall_confidence": 0.75,
    "notes": "Extracted building dimensions from floor plan to estimate roof area"
}"""


# ==========================================================
# RESPONSE PARSING
# ==========================================================

def parse_vision_response(response_text: str) -> dict:
    """Parse GPT-4o vision response into structured data."""
    if not response_text:
        return {"error": "Empty response"}

    text = response_text.strip()
    # Remove markdown code block wrapper if present
    if text.startswith("```"):
        text = re.sub(r'^```\w*\n?', '', text)
        text = re.sub(r'\n?```$', '', text)
        text = text.strip()

    try:
        return json.loads(text)
    except json.JSONDecodeError:
        json_match = re.search(r'\{[\s\S]*\}', text)
        if json_match:
            try:
                return json.loads(json_match.group())
            except json.JSONDecodeError:
                pass
        return {"error": "Failed to parse JSON", "raw_response": response_text[:500]}


def build_measurement_prompt_with_scale(scale_info: dict) -> str:
    """Build measurement extraction prompt with scale context."""
    if scale_info and scale_info.get("scale_found"):
        scale_context = (
            f"IMPORTANT SCALE INFORMATION:\n"
            f"The drawing scale is: {scale_info.get('scale_notation', 'unknown')}\n"
            f"Scale ratio: 1:{scale_info.get('scale_ratio', 'unknown')}\n"
            f"Use this scale to convert any measurements you derive from the drawing dimensions.\n"
            f"If dimensions are already labeled in feet/inches on the plan, use those directly."
        )
    else:
        scale_context = (
            "NOTE: No scale was detected for this drawing.\n"
            "Use ONLY dimensions that are explicitly labeled on the plan.\n"
            "Do NOT estimate measurements from the image size.\n"
            "If no dimensions are labeled, set confidence to 0.3 or lower.\n"
            "However, you CAN still count items (drains, penetrations, etc.) regardless of scale."
        )
    return MEASUREMENT_EXTRACTION_PROMPT.replace("{scale_context}", scale_context)


def build_bidset_prompt_with_scale(scale_info: dict) -> str:
    """Build the aggressive bid set extraction prompt with scale context."""
    if scale_info and scale_info.get("scale_found"):
        scale_context = (
            f"SCALE: {scale_info.get('scale_notation', 'unknown')} "
            f"(ratio 1:{scale_info.get('scale_ratio', 'unknown')})\n"
            f"Use this to convert drawn dimensions to real dimensions."
        )
    else:
        scale_context = (
            "No scale detected. Use ONLY labeled dimensions (numbers on the drawing).\n"
            "You CAN still count items and read labeled dimensions regardless of scale."
        )
    return BID_SET_EXTRACTION_PROMPT.replace("{scale_context}", scale_context)


# ==========================================================
# SANITY CHECKS
# ==========================================================

SANITY_LIMITS = {
    "roof_area": {"min": 100, "max": 1000000, "unit": "sqft"},
    "perimeter": {"min": 40, "max": 50000, "unit": "lnft"},
    "penetration": {"min": 0, "max": 200, "unit": "each"},
    "flashing": {"min": 0, "max": 100000, "unit": "lnft"},
    "slope": {"min": 0, "max": 45, "unit": "deg"},
    "drain": {"min": 0, "max": 100, "unit": "each"},
    "parapet_height": {"min": 0, "max": 120, "unit": "inches"},
    "insulation": {"min": 0, "max": 24, "unit": "inches"},
    "equipment": {"min": 0, "max": 100, "unit": "each"},
}


def validate_extraction(extraction_type: str, value: float) -> tuple:
    """Validate an extraction against sanity limits.
    Returns (is_valid, adjusted_confidence_multiplier, warning_message)."""
    limits = SANITY_LIMITS.get(extraction_type)
    if not limits:
        return True, 1.0, None

    if value < limits["min"]:
        return False, 0.3, f"{extraction_type} value {value} below minimum {limits['min']} {limits['unit']}"
    if value > limits["max"]:
        return False, 0.3, f"{extraction_type} value {value} above maximum {limits['max']} {limits['unit']}"
    return True, 1.0, None
