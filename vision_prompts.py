"""
GPT-4o Vision prompt templates for architectural roof plan analysis.
"""
import json
import re


PAGE_TYPE_PROMPT = """You are analyzing a page from an architectural drawing set for a commercial building.

Classify this page into one of the following types:
- roof_plan: Shows the roof layout from above with dimensions, slopes, drains, penetrations
- structural: Shows structural framing, beams, columns (may include roof framing)
- foundation: Shows the building foundation/slab plan
- elevation: Shows a side view of the building
- detail: Shows close-up construction details (flashing, curbs, etc.)
- mechanical: Shows HVAC equipment layout
- site_plan: Shows the overall site/property layout
- unknown: Cannot determine the page type

Look for title block text, drawing content, dimension lines, and sheet number references.

Respond with ONLY this JSON (no other text):
{
    "page_type": "roof_plan",
    "confidence": 0.95,
    "title_block_text": "A5.1 - ROOF PLAN",
    "is_roof_relevant": true,
    "notes": "Clear roof plan with dimensions and drain locations marked"
}"""


SCALE_DETECTION_PROMPT = """You are analyzing an architectural roof plan drawing. Find the scale of this drawing.

Look for:
1. A graphical scale bar (a line with measurement markings)
2. Text stating the scale (e.g., 1/8" = 1'-0", SCALE: 1/4" = 1', 1:100)
3. Title block information that includes scale

Common architectural scales:
- 1/8" = 1'-0" (1:96) - most common for roof plans
- 3/16" = 1'-0" (1:64)
- 1/4" = 1'-0" (1:48) - common for larger detail
- 1/16" = 1'-0" (1:192) - used for large buildings

Respond with ONLY this JSON (no other text):
{
    "scale_found": true,
    "scale_notation": "1/8 inch = 1 foot",
    "scale_ratio": 96,
    "scale_location": "title block, bottom right",
    "confidence": 0.90,
    "notes": "Scale clearly marked in title block"
}"""


MEASUREMENT_EXTRACTION_PROMPT = """You are a commercial roofing estimator analyzing an architectural roof plan drawing.

Extract ALL measurable roof information from this drawing. Use the dimensions shown on the plan.

{scale_context}

Extract these measurements:

1. ROOF AREA (sqft): Total roof surface area from dimensions
2. PERIMETER (lnft): Total building perimeter at roof level
3. PENETRATIONS: Count all roof penetrations (pipes, vents, HVAC curbs) - NOT drains
4. FLASHING/EDGE DETAILS (lnft): Total linear feet needing flashing
5. ROOF SLOPE: Slope angle or pitch (look for slope arrows)
6. DRAINS: Count roof drains (circles with crosshairs) and scuppers
7. OTHER: Expansion joints, area dividers, skylights, equipment screens

Respond with ONLY this JSON (no other text):
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
        },
        {
            "type": "perimeter",
            "value": 450,
            "unit": "lnft",
            "confidence": 0.85,
            "source": "Sum of all exterior edges from dimensions",
            "location": "Building perimeter",
            "notes": "125+100+125+100 = 450 lnft"
        },
        {
            "type": "penetration",
            "value": 3,
            "unit": "each",
            "confidence": 0.80,
            "source": "Pipe and vent symbols on drawing",
            "location": "Various locations",
            "notes": "2 pipe penetrations, 1 exhaust fan curb"
        },
        {
            "type": "flashing",
            "value": 500,
            "unit": "lnft",
            "confidence": 0.75,
            "source": "Perimeter coping + curb flashings",
            "location": "All edges plus HVAC curbs",
            "notes": "450 lnft perimeter + ~50 lnft curb flashing"
        },
        {
            "type": "slope",
            "value": 0.25,
            "unit": "in_per_ft",
            "confidence": 0.85,
            "source": "Slope arrow notation 1/4:12",
            "location": "Sloping toward drains",
            "notes": "1/4 inch per foot slope to drains"
        },
        {
            "type": "drain",
            "value": 4,
            "unit": "each",
            "confidence": 0.90,
            "source": "Drain symbols (circle with crosshairs)",
            "location": "4 internal drains evenly spaced",
            "notes": "Standard 4-inch internal roof drains"
        }
    ],
    "overall_confidence": 0.85,
    "drawing_quality": "good",
    "notes": "Clear roof plan with most dimensions labeled."
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
            "If no dimensions are labeled, set confidence to 0.3 or lower."
        )

    return MEASUREMENT_EXTRACTION_PROMPT.replace("{scale_context}", scale_context)


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
