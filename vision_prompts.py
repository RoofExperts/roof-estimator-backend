"""
GPT-4o Vision prompt templates for architectural roof plan analysis.
Domain-specific extraction logic for commercial roofing estimation.
"""

import json
import re


PAGE_TYPE_PROMPT = """You are analyzing a page from an architectural drawing set for a commercial building.
Your job is to classify this page AND determine if it contains any roof-related information.

Classify this page into one of the following types:
- roof_plan: Shows the roof layout from above with drains, scuppers, slopes, penetrations, pitch pans, pipes, curbs, crickets, tapered insulation, or roofing notes
- slab_plan: Shows the building slab/foundation plan from above WITH overall building dimensions (length x width). This is often labeled "Slab Plan", "Foundation Plan", "Slab on Grade", or shows the building footprint with dimension strings.
- structural: Shows structural framing, beams, columns, joists, or decking (may include roof framing)
- elevation: Shows a side view of the building showing T.O. (top of) notes, parapet heights, collector heads, downspouts, building heights
- detail: Shows close-up construction details (flashing, curbs, edge details, roof assembly sections, coping details)
- mechanical: Shows HVAC equipment layout (may show rooftop units)
- site_plan: Shows the overall site/property layout with building footprints
- floor_plan: Shows interior room layout, doors, walls with building dimensions
- cover_sheet: Title page, project info, drawing index
- general_notes: Specifications, abbreviations, symbols legend
- unknown: Cannot determine the page type

IMPORTANT: Set is_roof_relevant = true if the page contains ANY of the following:
- Roof plan view (overhead view showing roof areas, slopes, drains, scuppers, pitch pans, pipes, curbs)
- Slab/foundation plan with building dimensions (length x width) — this gives us roof area
- Building sections showing roof assembly or slope
- Roof detail drawings (flashing, edge, curb, drain, penetration, coping details)
- Elevation views showing parapet heights, T.O. notes, collector heads, downspouts
- Mechanical plans showing rooftop equipment placement
- Any annotations about roofing materials, insulation, or membrane
- Floor plans with overall building length and width dimensions
- Site plans showing building footprint dimensions

Be VERY GENEROUS with is_roof_relevant. When in doubt, set it to TRUE.
For a commercial bid set, ANY page showing building dimensions, parapet details, or roof items is useful.

Also set has_building_dimensions = true if the page has any dimension strings (e.g., 120'-0", 85', etc.) showing building width, length, or area.

Respond with ONLY this JSON (no other text):
{
    "page_type": "slab_plan",
    "confidence": 0.85,
    "title_block_text": "S1.1 - SLAB PLAN",
    "is_roof_relevant": true,
    "has_building_dimensions": true,
    "notes": "Slab plan showing building dimensions of 120' x 85' which gives roof area"
}"""


SCALE_DETECTION_PROMPT = """You are analyzing an architectural drawing page.
Find the EXACT scale of this drawing. Getting the scale right is CRITICAL — a wrong scale
will make all measurements wrong.

LOOK CAREFULLY FOR:
1. Text stating the scale — READ EVERY CHARACTER of the fraction carefully:
   - "3/16" = 1'-0"" is DIFFERENT from "1/8" = 1'-0""
   - "3/32" = 1'-0"" is DIFFERENT from "1/16" = 1'-0""
   - Pay special attention to the NUMERATOR: is it 1, 3, or something else?
2. A graphical scale bar (a line with measurement markings like 0...8'...16'...32')
3. Title block information (usually bottom right corner)
4. Scale text near the drawing title (e.g., "ROOF PLAN  SCALE: 3/16" = 1'-0"")

COMMON ARCHITECTURAL SCALES (read fractions EXACTLY):
- 1/16" = 1'-0" → ratio 1:192 (very small buildings look large on paper)
- 3/32" = 1'-0" → ratio 1:128
- 1/8"  = 1'-0" → ratio 1:96  (most common for large commercial)
- 3/16" = 1'-0" → ratio 1:64  (common for medium commercial)
- 1/4"  = 1'-0" → ratio 1:48  (common for smaller buildings/details)
- 3/8"  = 1'-0" → ratio 1:32  (large detail views)
- 1/2"  = 1'-0" → ratio 1:24  (detail views)

CRITICAL: Read the fraction precisely. "3/16" has a 3 in the numerator.
"1/8" has a 1 in the numerator. These are VERY different scales.
If the numerator is 3, it is likely 3/16" or 3/32" or 3/8".

Respond with ONLY this JSON (no other text):
{
    "scale_found": true,
    "scale_notation": "3/16 inch = 1 foot",
    "scale_ratio": 64,
    "scale_text_as_read": "3/16\" = 1'-0\"",
    "scale_location": "title block, bottom right",
    "confidence": 0.90,
    "notes": "Scale clearly marked in title block as 3/16\" = 1'-0\""
}"""


# ======================================================================
# PAGE-SPECIFIC EXTRACTION PROMPTS
# ======================================================================

SLAB_PLAN_EXTRACTION_PROMPT = """You are a commercial roofing estimator analyzing a SLAB PLAN or FOUNDATION PLAN page.

{scale_context}

YOUR MISSION: Extract the building dimensions to calculate roof area and parapet wall measurements.

WHAT TO LOOK FOR ON A SLAB PLAN:

1. BUILDING DIMENSIONS (length x width):
   - Look for dimension strings along the outside edges: "120'-0"", "85'-4"", "200'"
   - Look for dimension lines with arrows/ticks at both ends
   - The building may have multiple rectangular sections — measure each one
   - Calculate ROOF AREA = length × width for each section, then sum them
   - Calculate PERIMETER = sum of all outside edges

2. PARAPET WALLS:
   - Look for thick lines around the building perimeter — these are parapet walls
   - Measure the total LINEAR FEET of parapet wall (usually same as building perimeter)
   - Report as "parapet_wall" in lineal feet

3. COPING:
   - Coping goes on top of parapet walls
   - Coping linear feet = parapet wall linear feet (same measurement)
   - Report as "coping" in lineal feet

DIMENSION READING TIPS:
- Numbers with foot marks: 120'-0", 85'-4", 200'
- Numbers with dash formatting: 120-0, 85-4
- A rectangle 120' x 85' has area = 10,200 sqft and perimeter = 410 lnft
- If the building is L-shaped or irregular, break it into rectangles and add up

Report these measurement types:
- roof_area (sqft) — length × width, calculated
- parapet_wall (lnft) — total linear feet of parapet walls around building
- coping (lnft) — same as parapet wall length (coping sits on top of parapet)

If you find NOTHING useful, return:
{{"measurements": [], "overall_confidence": 0.0, "notes": "No measurements found"}}

Otherwise respond with ONLY JSON:
{{
    "measurements": [
        {{"type": "roof_area", "value": 10200, "unit": "sqft", "confidence": 0.85, "source": "Building dimensions 120' x 85'", "location": "Main building", "notes": "Calculated 120 x 85 = 10,200 sqft"}},
        {{"type": "parapet_wall", "value": 410, "unit": "lnft", "confidence": 0.80, "source": "Perimeter of building", "location": "Building perimeter", "notes": "2*(120+85) = 410 lnft"}},
        {{"type": "coping", "value": 410, "unit": "lnft", "confidence": 0.80, "source": "Top of parapet walls", "location": "Building perimeter", "notes": "Same as parapet wall length"}}
    ],
    "overall_confidence": 0.80,
    "notes": "Slab plan with clear building dimensions"
}}"""


ROOF_PLAN_EXTRACTION_PROMPT = """You are a commercial roofing estimator analyzing a ROOF PLAN page.

{scale_context}

YOUR MISSION: Count all roof items visible on this plan. These are critical for the roofing estimate.

WHAT TO LOOK FOR ON A ROOF PLAN:

1. ROOF DRAINS (eaches):
   - Typically shown as circles with crosshairs or X marks
   - May be labeled "RD" or "ROOF DRAIN"
   - Count every drain you can find
   - Report as "roof_drain" with unit "each"

2. SCUPPERS (eaches):
   - Openings in parapet walls for water drainage
   - Typically shown as rectangular openings in the parapet wall line
   - May be labeled "SCUPPER" or "SC"
   - Report as "scupper" with unit "each"

3. PITCH PANS (eaches):
   - Shown as small squares or rectangles around pipe penetrations
   - May be labeled "PITCH PAN" or "PP"
   - Used to seal around pipes/supports that penetrate the roof
   - Report as "pitch_pan" with unit "each"

4. PIPES (eaches):
   - Small circles on the roof plan representing pipe penetrations
   - May be labeled "PIPE PEN.", "VENT PIPE", "PLUMBING VENT"
   - Report as "pipe" with unit "each"

5. CURBS (lineal feet):
   - Rectangular shapes on the roof for HVAC units, skylights, hatches
   - Measure the PERIMETER around each curb (all 4 sides)
   - If curb is 4' x 4', perimeter = 16 lnft. If 8' x 6', perimeter = 28 lnft
   - Sum all curb perimeters together
   - Report as "curb" with unit "lnft"

COUNT CAREFULLY. Each individual drain, scupper, pitch pan, and pipe is one "each".
DO NOT calculate or report roof_area here — roof area is measured by a separate dedicated prompt.

If you find NOTHING useful, return:
{{"measurements": [], "overall_confidence": 0.0, "notes": "No measurements found"}}

Otherwise respond with ONLY JSON:
{{
    "measurements": [
        {{"type": "roof_drain", "value": 4, "unit": "each", "confidence": 0.85, "source": "Counted 4 roof drains with crosshair symbols", "location": "Roof plan", "notes": "4 drains visible"}},
        {{"type": "scupper", "value": 2, "unit": "each", "confidence": 0.80, "source": "2 scupper openings in parapet wall", "location": "East and west parapet", "notes": "Rectangular openings in parapet"}},
        {{"type": "pitch_pan", "value": 3, "unit": "each", "confidence": 0.75, "source": "3 pitch pan details around penetrations", "location": "Roof plan", "notes": "Square shapes around pipes"}},
        {{"type": "pipe", "value": 6, "unit": "each", "confidence": 0.80, "source": "6 pipe penetrations", "location": "Roof plan", "notes": "Small circles labeled as vents/pipes"}},
        {{"type": "curb", "value": 48, "unit": "lnft", "confidence": 0.75, "source": "3 curbs: 2x(4x4)=32 lnft + 1x(4x4)=16 lnft", "location": "Roof plan", "notes": "Total curb perimeter from 3 HVAC curbs"}}
    ],
    "overall_confidence": 0.80,
    "notes": "Roof plan with drains, scuppers, pitch pans, pipes, and curbs. DO NOT include roof_area here."
}}"""


ROOF_PLAN_AREA_MEASUREMENT_PROMPT = """You are a commercial roofing estimator analyzing a ROOF PLAN page.
Your PRIMARY mission is to MEASURE THE BUILDING FOOTPRINT to calculate the ROOF AREA in square feet.

{scale_context}

HOW TO MEASURE THE BUILDING FOOTPRINT FROM A ROOF PLAN:

STEP 1 — DETERMINE THE SCALE:
- If the scale information above says "MANDATORY" or "SET BY THE USER", SKIP this step entirely.
  Use EXACTLY the scale provided above — it has been verified by the user.
- Otherwise, verify the scale:
  - Look at this page and READ THE SCALE TEXT yourself, character by character
  - Look in the title block (usually bottom right) for text like "SCALE: 3/16" = 1'-0""
  - Look near the drawing title for scale notation
  - Look for a graphical scale bar (a line marked with distances like 0...8'...16'...32')
  - IMPORTANT: Read the fraction EXACTLY. "3/16"" is NOT the same as "1/8""
    - 3/16" = 1'-0" means 1 foot real = 3/16 inch on paper (ratio 1:64)
    - 1/8" = 1'-0" means 1 foot real = 1/8 inch on paper (ratio 1:96)
    - Getting this wrong makes the area off by 2.25x!
- REPORT the scale you are using in your response

STEP 2 — IDENTIFY THE BUILDING OUTLINE:
- The building outline is the OUTERMOST boundary of the ROOF AREA ONLY
- It is typically the thickest line forming a closed shape (rectangle, L-shape, T-shape, etc.)
- Parapet walls form this outline
- IGNORE interior lines (slope arrows, drain locations, cricket lines)
- ONLY include areas that are ROOFED — do NOT include covered walkways, canopies, overhangs,
  or adjacent structures unless they are clearly part of the main roof system
- If there are multiple separate buildings or sections, only measure the MAIN BUILDING ROOF

STEP 3 — READ AND REPORT ALL DIMENSIONS:
*** CRITICAL: You MUST list EVERY dimension you read from the plan. ***

Method A — If dimension lines are labeled on the plan (PREFERRED):
  - Read EACH dimension string EXACTLY as written: "96'-0"", "80'-0"", etc.
  - List EVERY dimension you read in your response
  - Use these directly — do NOT apply scale conversion to labeled dimensions
  - Labeled dimensions are ALREADY in real-world feet — they need NO conversion
  - DOUBLE-CHECK: Read each number character by character. "96" is not "106". "80" is not "60".

Method B — If NO dimensions are labeled, use the scale visually:
  - Look at the graphical scale bar length
  - Mentally (or visually) lay the scale bar along each edge of the building
  - Count how many scale-bar-lengths fit along the building width and length
  - Multiply by the scale bar value to get feet
  - Example: scale bar = 32 feet, building is ~4.5 scale bars wide = 144 feet

Method C — Calculate from scale ratio (USE THE SCALE PROVIDED ABOVE):
  - If the building appears to span roughly X inches on the drawing
  - Use the scale ratio provided in the SCALE INFORMATION section above
  - Formula: real feet = X inches on paper × (scale_ratio / 12)
  - Example for 3/16" = 1'-0" (ratio 1:64): X inches × (64/12) = X × 5.33 feet
  - Example for 1/8" = 1'-0" (ratio 1:96): X inches × (96/12) = X × 8 feet
  - ALWAYS use the scale provided above — do NOT guess or pick a different scale

STEP 4 — CALCULATE AREA:
- For a simple rectangle: Area = Length × Width
- For L-shaped buildings: Break into 2+ rectangles, calculate each, sum them
- For T-shaped or irregular: Break into rectangles, sum areas
- Also calculate PERIMETER = sum of all exterior edges
- VERIFY YOUR MATH: After calculating, double-check by re-reading the dimensions

STEP 5 — MEASURE PARAPET WALL AND COPING:
- Parapet wall linear feet = building perimeter (all exterior edges)
- Coping linear feet = same as parapet wall (coping sits on top)

IMPORTANT RULES:
- ALWAYS show your math: "96' × 80' = 7,680 sqft"
- If the building has multiple sections, list each: "Section A: 96×80=7,680"
- ALWAYS list every dimension you read in "dimensions_read" field
- If dimensions are NOT labeled, state that you measured using the scale and give your confidence
- Round dimensions to nearest half-foot
- If you cannot determine the area with reasonable confidence, say so — do NOT guess or use a default number
- Do NOT add sections that are not part of the roof (walkways, grade-level areas, patios)

Respond with ONLY JSON:
{{
    "measurements": [
        {{"type": "roof_area", "value": 7680, "unit": "sqft", "confidence": 0.85, "source": "Measured from roof plan: 96' x 80' = 7,680 sqft", "location": "Main building footprint", "notes": "Dimensions read from labeled dimension lines on roof plan", "measurement_method": "dimension_lines"}},
        {{"type": "parapet_wall", "value": 352, "unit": "lnft", "confidence": 0.80, "source": "Building perimeter: 2*(96+80) = 352 lnft", "location": "Building perimeter", "notes": "Perimeter of building footprint"}},
        {{"type": "coping", "value": 352, "unit": "lnft", "confidence": 0.80, "source": "Top of parapet walls", "location": "Building perimeter", "notes": "Same as parapet wall length"}}
    ],
    "overall_confidence": 0.80,
    "building_shape": "rectangle",
    "dimensions_labeled": true,
    "dimensions_read": ["96'-0\" (north edge)", "80'-0\" (east edge)"],
    "measurement_method": "dimension_lines",
    "scale_used": "3/16 inch = 1 foot (1:64)",
    "scale_text_on_drawing": "3/16\" = 1'-0\"",
    "notes": "Building dimensions clearly labeled on roof plan. Read 96' x 80'. Area = 96 x 80 = 7,680 sqft."
}}

If dimensions were NOT labeled and you measured using the scale:
{{
    "measurements": [
        {{"type": "roof_area", "value": 5183, "unit": "sqft", "confidence": 0.70, "source": "Scale-measured from roof plan using 3/16\"=1'-0\" scale: ~72' x ~72' = 5,183 sqft", "location": "Main building footprint", "notes": "Measured by comparing building outline to scale bar.", "measurement_method": "scale_measurement"}},
        {{"type": "parapet_wall", "value": 288, "unit": "lnft", "confidence": 0.65, "source": "Building perimeter: 2*(72+72) = 288 lnft", "location": "Building perimeter", "notes": "Estimated from scale measurement"}},
        {{"type": "coping", "value": 288, "unit": "lnft", "confidence": 0.65, "source": "Top of parapet walls", "location": "Building perimeter", "notes": "Same as parapet wall length"}}
    ],
    "overall_confidence": 0.70,
    "building_shape": "rectangle",
    "dimensions_labeled": false,
    "dimensions_read": [],
    "measurement_method": "scale_measurement",
    "scale_used": "3/16 inch = 1 foot (1:64)",
    "scale_text_on_drawing": "3/16\" = 1'-0\"",
    "notes": "No dimensions labeled on plan. Measured building outline against graphical scale bar."
}}"""


ELEVATION_EXTRACTION_PROMPT = """You are a commercial roofing estimator analyzing an ELEVATION VIEW page.

{scale_context}

YOUR MISSION: Extract parapet heights, collector heads, and downspout measurements from this elevation.

WHAT TO LOOK FOR ON ELEVATIONS:

1. PARAPET FLASHING HEIGHT:
   - Look for "T.O. STEEL DECK" or "T.O. CANOPY" or "T.O. ROOF DECK" note — this is the TOP of the steel deck (baseline)
   - Look for "T.O. LOW PARAPET", "T.O. MID PARAPET", "T.O. HIGH PARAPET" or just "T.O. PARAPET"
   - PARAPET FLASHING HEIGHT = T.O. Parapet elevation MINUS T.O. Steel Deck elevation
   - Example: T.O. Parapet = 25'-4", T.O. Steel Deck = 22'-0", so flashing height = 3'-4" = 40 inches
   - There may be multiple parapet heights (low, mid, high) — report each one separately
   - Report as "parapet_flashing_low", "parapet_flashing_mid", "parapet_flashing_high" or just "parapet_flashing" if only one height
   - Unit is INCHES

2. COLLECTOR HEADS (eaches):
   - Box-like elements at the top of downspouts where the roof gutter connects
   - Usually shown at parapet level or just below
   - May be labeled "COLLECTOR HEAD" or "C.H."
   - Count each one
   - Report as "collector_head" with unit "each"

3. DOWNSPOUTS (lineal feet):
   - Vertical lines running down the building face from collector heads to grade
   - Measure from the collector head down to the ground/grade level
   - ROUND to nearest 10 feet
   - Example: collector head at 24' elevation, grade at 0' → downspout = 24 lnft → round to 20 lnft
   - Report TOTAL lineal feet of all downspouts (sum them up)
   - Report as "downspout" with unit "lnft"

ELEVATION READING TIPS:
- Elevation marks look like: EL. 25'-4", +25.33', T.O. 22'-0"
- The difference between two elevation marks gives you a height
- Grade/ground level is usually 0'-0" or 100'-0" (benchmark)
- Count downspouts on ALL elevations shown

If you find NOTHING useful, return:
{{"measurements": [], "overall_confidence": 0.0, "notes": "No measurements found"}}

Otherwise respond with ONLY JSON:
{{
    "measurements": [
        {{"type": "parapet_flashing", "value": 40, "unit": "inches", "confidence": 0.85, "source": "T.O. Parapet 25'-4\" minus T.O. Steel Deck 22'-0\" = 3'-4\" = 40 inches", "location": "Main parapet", "notes": "Single parapet height"}},
        {{"type": "collector_head", "value": 3, "unit": "each", "confidence": 0.80, "source": "3 collector heads visible on elevation", "location": "South elevation", "notes": "Box shapes at top of downspouts"}},
        {{"type": "downspout", "value": 80, "unit": "lnft", "confidence": 0.75, "source": "3 downspouts x ~25' each = 75 lnft, rounded to 80", "location": "South elevation", "notes": "Vertical lines from collector heads to grade, rounded to 10'"}}
    ],
    "overall_confidence": 0.80,
    "notes": "Elevation showing parapet heights, collector heads, and downspouts"
}}"""


# Generic fallback for other page types
GENERAL_EXTRACTION_PROMPT = """You are a commercial roofing estimator analyzing an architectural drawing page.
This may be a detail, mechanical, structural, or other page type.

{scale_context}

Extract ANY information useful for roofing estimation:

LOOK FOR:
- Building dimensions (length x width) → calculate roof area (sqft)
- Roof drains — eaches count (circles with crosshairs)
- Scuppers — eaches count (openings in parapet walls)
- Pitch pans — eaches count (squares around pipe penetrations)
- Pipes — eaches count (small circles, vent pipes)
- Curbs — lineal feet around each curb (measure perimeter of each curb, sum all)
- Parapet flashing height — T.O. Parapet minus T.O. Steel Deck, in inches
- Coping — lineal feet of parapet wall
- Parapet wall — lineal feet
- Collector heads — eaches count
- Downspouts — lineal feet from collector head to grade, rounded to nearest 10'
- Rooftop equipment count
- Roof assembly details (membrane type, insulation thickness)

If you find NOTHING useful, return:
{{"measurements": [], "overall_confidence": 0.0, "notes": "No useful measurements found"}}

Otherwise respond with ONLY JSON:
{{
    "measurements": [
        {{"type": "TYPE_HERE", "value": 0, "unit": "UNIT_HERE", "confidence": 0.75, "source": "Description of where you found this", "location": "Location on drawing", "notes": "Additional context"}}
    ],
    "overall_confidence": 0.75,
    "notes": "Description of what was found"
}}"""


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


def build_prompt_for_page_type(page_type: str, scale_info: dict) -> str:
    """Build the appropriate extraction prompt based on page type."""
    if scale_info and scale_info.get("scale_found"):
        scale_notation = scale_info.get('scale_notation', 'unknown')
        scale_ratio = scale_info.get('scale_ratio', 'unknown')
        is_manual = scale_info.get('is_manual', False)

        if is_manual:
            # User manually set the scale — be VERY authoritative, do NOT let GPT override
            scale_context = (
                f"*** MANDATORY SCALE — SET BY THE USER (DO NOT OVERRIDE) ***\n"
                f"The drawing scale is: {scale_notation}\n"
                f"Scale ratio: 1:{scale_ratio}\n"
                f"This scale was manually verified and set by the user. It is CORRECT.\n"
                f"DO NOT attempt to read or verify the scale from the drawing.\n"
                f"DO NOT override this scale with anything you see on the drawing.\n"
                f"You MUST use this exact scale for ALL measurements.\n"
                f"If dimensions are already labeled in feet/inches on the plan, use those directly.\n"
                f"If you need to measure using the scale: 1 inch on paper = {scale_ratio} inches real = {float(scale_ratio)/12:.2f} feet real."
            )
        else:
            scale_context = (
                f"IMPORTANT SCALE INFORMATION:\n"
                f"The drawing scale is: {scale_notation}\n"
                f"Scale ratio: 1:{scale_ratio}\n"
                f"Use this scale to convert any measurements you derive from the drawing dimensions.\n"
                f"If dimensions are already labeled in feet/inches on the plan, use those directly."
            )
    else:
        scale_context = (
            "NOTE: No scale was detected for this drawing.\n"
            "Use ONLY dimensions that are explicitly labeled on the plan.\n"
            "Do NOT estimate measurements from the image size.\n"
            "If no dimensions are labeled, set confidence to 0.3 or lower.\n"
            "However, you CAN still count items (drains, pipes, etc.) regardless of scale."
        )

    # Select prompt based on page type
    if page_type in ("slab_plan", "foundation"):
        prompt_template = SLAB_PLAN_EXTRACTION_PROMPT
    elif page_type == "roof_plan_area":
        # Special mode: measure building footprint from roof plan using scale
        prompt_template = ROOF_PLAN_AREA_MEASUREMENT_PROMPT
    elif page_type == "roof_plan":
        prompt_template = ROOF_PLAN_EXTRACTION_PROMPT
    elif page_type == "elevation":
        prompt_template = ELEVATION_EXTRACTION_PROMPT
    elif page_type == "floor_plan":
        # Floor plans can have building dimensions like slab plans
        prompt_template = SLAB_PLAN_EXTRACTION_PROMPT
    else:
        prompt_template = GENERAL_EXTRACTION_PROMPT

    return prompt_template.replace("{scale_context}", scale_context)


# Keep legacy functions for backward compatibility
def build_measurement_prompt_with_scale(scale_info: dict) -> str:
    """Build measurement extraction prompt with scale context (legacy)."""
    return build_prompt_for_page_type("roof_plan", scale_info)


def build_bidset_prompt_with_scale(scale_info: dict) -> str:
    """Build aggressive bid set prompt with scale context (legacy)."""
    return build_prompt_for_page_type("general", scale_info)


# ==========================================================
# SANITY CHECKS
# ==========================================================

SANITY_LIMITS = {
    "roof_area": {"min": 100, "max": 1000000, "unit": "sqft"},
    "parapet_wall": {"min": 10, "max": 50000, "unit": "lnft"},
    "coping": {"min": 10, "max": 50000, "unit": "lnft"},
    "roof_drain": {"min": 0, "max": 200, "unit": "each"},
    "scupper": {"min": 0, "max": 200, "unit": "each"},
    "pitch_pan": {"min": 0, "max": 200, "unit": "each"},
    "pipe": {"min": 0, "max": 200, "unit": "each"},
    "curb": {"min": 0, "max": 5000, "unit": "lnft"},
    "parapet_flashing": {"min": 1, "max": 120, "unit": "inches"},
    "parapet_flashing_low": {"min": 1, "max": 120, "unit": "inches"},
    "parapet_flashing_mid": {"min": 1, "max": 120, "unit": "inches"},
    "parapet_flashing_high": {"min": 1, "max": 120, "unit": "inches"},
    "collector_head": {"min": 0, "max": 100, "unit": "each"},
    "downspout": {"min": 0, "max": 5000, "unit": "lnft"},
    # Legacy types still supported
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
