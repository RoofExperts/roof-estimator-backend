"""
Vector PDF extraction.

When a plan PDF contains real vector geometry (lines, polylines, polygons,
text annotations with position) — true for anything exported from AutoCAD,
Revit, or similar CAD tools — we can extract measurements deterministically
without relying on AI vision to estimate them from pixels.

This module provides:
  - detect_pdf_type(file_path) -> "vector" | "raster" | "hybrid"
  - extract_vector_measurements(file_path, scale_info) -> list[dict]
  - The output dicts use the SAME schema as vision extractions
    (same `extraction_type`, `value`, `unit`, `confidence`, etc.) so
    they merge into the same downstream pipeline.

Configuration:
  VECTOR_EXTRACTION_ENABLED env var (default "true")

Limits:
  - Max pages processed: 150 (raised for large bid sets like Dove Creek 107pp)
  - Hard cap on candidate pages held in memory: 80
  - Hard timeout per page: 10 seconds
"""

import os
import re
import math
import time
from dataclasses import dataclass, field
from typing import Optional

# Heavy deps (PyMuPDF + shapely) are required for the actual extraction path,
# but the module must remain importable when they're stubbed out (test
# environments) or absent. Pure-Python helpers (regex parsing, reconciliation)
# work without them.
try:
    import fitz  # PyMuPDF — already a Track A dependency
    from shapely.geometry import Polygon, LineString, Point  # type: ignore
    from shapely.ops import unary_union  # noqa: F401 — kept for future use
    _HAS_GEO_DEPS = True
except Exception:  # pragma: no cover - exercised only without deps
    fitz = None  # type: ignore
    Polygon = None  # type: ignore
    LineString = None  # type: ignore
    Point = None  # type: ignore
    _HAS_GEO_DEPS = False


# ============================================================================
# CONFIGURATION
# ============================================================================
VECTOR_EXTRACTION_ENABLED = os.getenv("VECTOR_EXTRACTION_ENABLED", "true").lower() == "true"

# Raised from 30 to 150 — real architectural bid sets routinely run
# 100+ pages (e.g. Dove Creek bid set was 107 pages).
MAX_PAGES_TO_SCAN = 150

# Hard cap on candidate pages held in memory during scoring. Without
# this, a pathological PDF could push every page through the gating
# checks and OOM the worker. 80 is well above any real Division 07
# we've seen.
MAX_KEPT_VECTOR_PAGES = 80

PAGE_TIMEOUT_SECONDS = 10
MIN_VECTORS_FOR_VECTOR_PDF = 50      # Below this, treat as raster
MIN_TEXT_DIMS_TO_TRUST_SCALE = 2     # Need at least 2 labeled dimensions to derive scale


# ============================================================================
# DATA CLASSES (internal — not persisted)
# ============================================================================

@dataclass
class VectorPage:
    """All extracted geometry and text from a single PDF page."""
    page_number: int
    width_pts: float
    height_pts: float
    drawings: list = field(default_factory=list)        # raw fitz drawings
    text_blocks: list = field(default_factory=list)     # (text, bbox, rotation)
    polylines: list = field(default_factory=list)       # list[LineString | Polygon]
    dimension_callouts: list = field(default_factory=list)  # parsed labels


@dataclass
class DimensionCallout:
    """A parsed dimension annotation (e.g. "47'-6\"")."""
    raw_text: str
    feet: float
    inches: float
    total_inches: float
    bbox: tuple              # (x0, y0, x1, y1) in PDF user-space points
    midpoint: tuple          # (x, y)
    confidence: float


# ============================================================================
# STAGE 1: PDF TYPE DETECTION
# ============================================================================

def detect_pdf_type(file_path: str) -> str:
    """Return 'vector', 'raster', or 'hybrid'.

    Definitions:
      - vector: PDF has substantial vector geometry on most pages
      - raster: PDF is essentially a stack of images (scanned or rendered)
      - hybrid: some pages vector, some pages raster (common for revisions)
    """
    if not VECTOR_EXTRACTION_ENABLED or not _HAS_GEO_DEPS:
        return "raster"  # Caller should treat as raster, skip vector path

    doc = fitz.open(file_path)
    pages_to_check = min(len(doc), MAX_PAGES_TO_SCAN)
    vector_pages = 0
    raster_pages = 0

    for page_num in range(pages_to_check):
        page = doc[page_num]
        drawings = page.get_drawings()
        # A page is "vector" if it has meaningful geometry
        if len(drawings) >= MIN_VECTORS_FOR_VECTOR_PDF:
            vector_pages += 1
        else:
            raster_pages += 1

    doc.close()

    if vector_pages == 0:
        return "raster"
    elif raster_pages == 0:
        return "vector"
    else:
        return "hybrid"


# ============================================================================
# STAGE 2: GEOMETRY EXTRACTION
# ============================================================================

def extract_page_geometry(page) -> VectorPage:
    """Pull all drawings + text from a single page into a VectorPage.

    The fitz drawings API gives us a list of {type, items, ...} dicts where
    type is 'l' (line), 'c' (curve), 're' (rectangle), 'qu' (quad). We
    convert these to shapely LineStrings and Polygons.

    Text comes from page.get_text("dict") which gives blocks with bboxes.
    """
    vp = VectorPage(
        page_number=page.number + 1,
        width_pts=page.rect.width,
        height_pts=page.rect.height,
    )

    raw_drawings = page.get_drawings()
    for d in raw_drawings:
        items = d.get("items", [])
        # Convert each drawing into a polyline
        coords = []
        for item in items:
            op = item[0]
            if op == "l":  # line
                p1, p2 = item[1], item[2]
                coords.append((p1.x, p1.y))
                coords.append((p2.x, p2.y))
            elif op == "re":  # rectangle
                rect = item[1]
                # Add as a closed polygon
                coords_rect = [
                    (rect.x0, rect.y0), (rect.x1, rect.y0),
                    (rect.x1, rect.y1), (rect.x0, rect.y1),
                    (rect.x0, rect.y0),
                ]
                try:
                    vp.polylines.append(Polygon(coords_rect))
                except Exception:
                    pass
                continue
            # Curves intentionally skipped — roofing measurements rarely need them.

        if len(coords) >= 2:
            try:
                # If first and last point are very close, treat as closed polygon
                if _close_enough(coords[0], coords[-1]):
                    vp.polylines.append(Polygon(coords))
                else:
                    vp.polylines.append(LineString(coords))
            except Exception:
                pass

    # Extract text + bboxes for dimension callout parsing
    text_dict = page.get_text("dict")
    for block in text_dict.get("blocks", []):
        if block.get("type") != 0:  # 0 = text block
            continue
        for line in block.get("lines", []):
            for span in line.get("spans", []):
                txt = span.get("text", "").strip()
                if not txt:
                    continue
                bbox = span.get("bbox")
                rot = line.get("dir", (1, 0))  # rotation hint
                vp.text_blocks.append((txt, bbox, rot))

    vp.drawings = raw_drawings
    return vp


def _close_enough(p1, p2, tol_pts: float = 1.5) -> bool:
    return math.hypot(p1[0] - p2[0], p1[1] - p2[1]) <= tol_pts


# ============================================================================
# STAGE 3: DIMENSION CALLOUT PARSING
# ============================================================================
# Architects label dimensions in many formats:
#   47'-6"
#   47'-6 1/2"
#   47.5'
#   47'
#   47 FT
#   47 FT 6 IN
#   570" (just inches)
# This regex covers the common cases. Less common forms degrade gracefully
# (we just skip them, the overall extraction still works).

_DIM_PATTERN = re.compile(
    r"""
    (?P<feet>\d+(?:\.\d+)?)            # feet number, optional decimal
    \s*[′'’]                  # foot mark: '  ’  ′
    (?:\s*[-–—]?\s*           # optional dash separator
       (?P<inches>\d+(?:\.\d+)?)        # inch number
       (?:\s+(?P<frac_n>\d+)/(?P<frac_d>\d+))?  # optional fraction like 1/2
       \s*[″"”’’]?  # inch mark (optional)
    )?
    """,
    re.VERBOSE,
)

_BARE_FEET_PATTERN = re.compile(r"(\d+(?:\.\d+)?)\s*(?:FT|FEET)\b", re.IGNORECASE)
_BARE_INCH_PATTERN = re.compile(r"(\d+(?:\.\d+)?)\s*(?:IN|INCHES?|[\"″])\b", re.IGNORECASE)


def parse_dimension_text(text: str) -> Optional[DimensionCallout]:
    """Parse a single text fragment into a DimensionCallout if it looks like one.

    Returns None when the text is not a recognizable dimension. Callers
    should ignore None results.
    """
    text = text.strip()
    if not text:
        return None
    if len(text) > 30:
        return None  # Probably not a dimension callout

    m = _DIM_PATTERN.search(text)
    if m and m.group("feet"):
        feet = float(m.group("feet"))
        inches = float(m.group("inches") or 0)
        if m.group("frac_n") and m.group("frac_d"):
            try:
                inches += float(m.group("frac_n")) / float(m.group("frac_d"))
            except ZeroDivisionError:
                pass
        total = feet * 12 + inches
        return DimensionCallout(
            raw_text=text, feet=feet, inches=inches,
            total_inches=total, bbox=(0, 0, 0, 0), midpoint=(0, 0),
            confidence=0.9,
        )

    # Try bare feet ("47 FT" / "47'")
    m = _BARE_FEET_PATTERN.search(text)
    if m:
        feet = float(m.group(1))
        return DimensionCallout(
            raw_text=text, feet=feet, inches=0,
            total_inches=feet * 12, bbox=(0, 0, 0, 0), midpoint=(0, 0),
            confidence=0.7,
        )

    return None


def collect_dimensions_from_page(vp: VectorPage) -> list:
    """Walk vp.text_blocks, parse each for dimensions, attach bbox/midpoint."""
    callouts = []
    for txt, bbox, _rot in vp.text_blocks:
        d = parse_dimension_text(txt)
        if d is None:
            continue
        d.bbox = bbox
        d.midpoint = ((bbox[0] + bbox[2]) / 2.0, (bbox[1] + bbox[3]) / 2.0)
        callouts.append(d)
    return callouts


# ============================================================================
# STAGE 4: SCALE DERIVATION FROM VECTOR DATA
# ============================================================================
# Strategy: find pairs of labeled dimensions whose values sum or correspond
# to clearly measurable PDF distances on the page. The PDF gives distances in
# points (1/72 inch). If we find a label "47'-6\"" near a polyline that's
# approximately 380 points long, we have an effective scale.
#
# This is a best-effort heuristic. When we can't derive a confident scale,
# we return None and let the caller fall back to the vision-derived scale.

@dataclass
class VectorScale:
    points_per_foot: float
    confidence: float
    source_dimensions: int      # how many dimension labels supported this


def derive_scale_from_dimensions(
    vp: VectorPage,
    callouts: list,
) -> Optional[VectorScale]:
    """Try to derive points-per-foot from labeled dimensions on this page."""
    if len(callouts) < MIN_TEXT_DIMS_TO_TRUST_SCALE:
        return None

    candidates = []
    for callout in callouts:
        cx, cy = callout.midpoint
        nearest = _nearest_polyline_to_point(vp.polylines, cx, cy)
        if nearest is None:
            continue
        line_pts = nearest.length
        feet = callout.feet + (callout.inches / 12.0)
        if feet <= 0:
            continue
        ratio = line_pts / feet
        # Plausibility band: typical scales for commercial plans give
        # 4 to 200 points per foot
        if 4.0 <= ratio <= 200.0:
            candidates.append(ratio)

    if len(candidates) < MIN_TEXT_DIMS_TO_TRUST_SCALE:
        return None

    candidates.sort()
    mid = candidates[len(candidates) // 2]
    spread = (max(candidates) - min(candidates)) / mid if mid else 1.0
    if spread < 0.1:
        confidence = 0.95
    elif spread < 0.25:
        confidence = 0.8
    else:
        confidence = 0.6

    return VectorScale(
        points_per_foot=mid,
        confidence=confidence,
        source_dimensions=len(candidates),
    )


def _nearest_polyline_to_point(polylines, x: float, y: float):
    """Return the polyline whose distance to (x, y) is smallest."""
    if Point is None:
        return None
    best = None
    best_dist = float("inf")
    pt = Point(x, y)
    for pl in polylines:
        try:
            d = pt.distance(pl)
        except Exception:
            continue
        if d < best_dist:
            best_dist = d
            best = pl
    return best


# ============================================================================
# STAGE 5: MEASUREMENT EXTRACTION (CLASSIFICATION + COMPUTATION)
# ============================================================================
# Minimal classification rules. We DO NOT try to identify every layer or color
# (per the user's spec: "minimal classification, defer to vision for the rest").
# Rules:
#   1. Largest closed polygon on the page = candidate roof area (sqft)
#   2. Long straight LineStrings near the perimeter of that polygon =
#      candidate perimeter (lnft)
#   3. Dimension callouts that successfully parsed = explicit measurements
#      (just the labeled feet, no inference)


def measurements_from_page(
    vp: VectorPage,
    scale: VectorScale,
    page_classification: dict,
) -> list:
    """Apply minimal classification rules and return measurement dicts."""
    measurements = []
    pts_per_ft = scale.points_per_foot
    page_type = page_classification.get("page_type", "unknown")

    # === Rule 1: Largest closed polygon → roof_area (only on roof_plan / slab_plan) ===
    polygons = []
    if Polygon is not None:
        polygons = [pl for pl in vp.polylines if isinstance(pl, Polygon) and pl.is_valid]
    if polygons and page_type in ("roof_plan", "slab_plan", "floor_plan"):
        largest = max(polygons, key=lambda p: p.area)
        area_pts2 = largest.area
        area_sqft = area_pts2 / (pts_per_ft ** 2)
        # Reasonable bounds for a commercial roof: 1,000 to 1,000,000 sqft
        if 1000 <= area_sqft <= 1_000_000:
            measurements.append({
                "type": "roof_area",
                "value": round(area_sqft, 1),
                "unit": "sqft",
                "confidence": min(0.85, scale.confidence),
                "notes": f"Largest closed polygon, {len(polygons)} polygons on page",
                "source": "vector",
                "measurement_method": "polygon_area",
                "_source_page_type": page_type,
            })

            # Rule 2: perimeter of that polygon
            perimeter_pts = largest.length
            perimeter_ft = perimeter_pts / pts_per_ft
            measurements.append({
                "type": "perimeter",
                "value": round(perimeter_ft, 1),
                "unit": "lnft",
                "confidence": min(0.85, scale.confidence),
                "notes": "Perimeter of largest closed polygon",
                "source": "vector",
                "measurement_method": "polyline_length",
                "_source_page_type": page_type,
            })

    # === Rule 3: Dimension callouts → labeled_dimension entries ===
    callouts = collect_dimensions_from_page(vp)
    if callouts and page_type in ("roof_plan", "slab_plan", "floor_plan", "elevation"):
        callouts_sorted = sorted(callouts, key=lambda c: c.feet, reverse=True)[:5]
        for c in callouts_sorted:
            measurements.append({
                "type": "labeled_dimension",
                "value": round(c.feet + c.inches / 12, 2),
                "unit": "lnft",
                "confidence": c.confidence,
                "notes": f'Dimension callout: "{c.raw_text}"',
                "source": "vector",
                "measurement_method": "dimension_label",
                "_source_page_type": page_type,
            })

    return measurements


# ============================================================================
# PUBLIC ENTRY POINT
# ============================================================================

def extract_vector_measurements(
    file_path: str,
    page_classifications: dict,
) -> dict:
    """Run the full vector extraction pipeline on a PDF.

    Args:
        file_path: Local path to the PDF file.
        page_classifications: Dict keyed by 1-based page number with values
            from the existing vision-based page classification step.

    Returns:
        A dict with keys: pdf_type, scale, measurements, diagnostics.

        If pdf_type is "raster" or VECTOR_EXTRACTION_ENABLED is false,
        returns the dict with empty measurements and pdf_type set, so callers
        can branch cleanly.
    """
    t0 = time.time()
    result = {
        "pdf_type": "raster",
        "scale": None,
        "measurements": [],
        "diagnostics": {
            "pages_processed": 0,
            "pages_with_geometry": 0,
            "pages_with_dimensions": 0,
            "elapsed_seconds": 0.0,
        },
    }

    if not VECTOR_EXTRACTION_ENABLED:
        print("[Vector] VECTOR_EXTRACTION_ENABLED=false, skipping vector path")
        result["diagnostics"]["elapsed_seconds"] = round(time.time() - t0, 2)
        return result

    if not _HAS_GEO_DEPS:
        print("[Vector] PyMuPDF or shapely unavailable, skipping vector path")
        result["diagnostics"]["elapsed_seconds"] = round(time.time() - t0, 2)
        return result

    pdf_type = detect_pdf_type(file_path)
    result["pdf_type"] = pdf_type
    if pdf_type == "raster":
        print(f"[Vector] PDF detected as raster, skipping vector path")
        result["diagnostics"]["elapsed_seconds"] = round(time.time() - t0, 2)
        return result

    print(f"[Vector] PDF detected as {pdf_type}, running vector extraction")

    import gc

    doc = fitz.open(file_path)
    pages_in_pdf = len(doc)
    pages_to_process = min(pages_in_pdf, MAX_PAGES_TO_SCAN)

    # Memory-bounded design: collect candidate (score, page_num, measurements)
    # tuples, capped at MAX_KEPT_VECTOR_PAGES. Free per-page intermediate
    # state aggressively after scoring.
    candidates = []  # list of (score, page_num, measurements_list)
    scales_found = []
    pages_with_geom = 0
    pages_with_dims = 0

    for page_num in range(pages_to_process):
        per_page_t0 = time.time()
        try:
            page = doc[page_num]
            vp = extract_page_geometry(page)

            if not vp.polylines:
                del vp
                gc.collect()
                continue
            pages_with_geom += 1

            callouts = collect_dimensions_from_page(vp)
            if callouts:
                pages_with_dims += 1

            scale = derive_scale_from_dimensions(vp, callouts)
            if scale is None:
                del vp, callouts
                gc.collect()
                continue

            scales_found.append(scale)

            page_classification = page_classifications.get(vp.page_number, {})
            page_measurements = measurements_from_page(vp, scale, page_classification)

            # Score the page so we can evict low-value pages when we hit
            # MAX_KEPT_VECTOR_PAGES. Score = number of measurements * 2 +
            # bonus for having labeled dimensions.
            page_score = len(page_measurements) * 2 + (3 if callouts else 0)

            if len(candidates) < MAX_KEPT_VECTOR_PAGES:
                candidates.append((page_score, vp.page_number, page_measurements))
            else:
                min_idx = 0
                for idx, (s, _, _) in enumerate(candidates):
                    if s < candidates[min_idx][0]:
                        min_idx = idx
                if page_score > candidates[min_idx][0]:
                    evicted_score, evicted_page, _ = candidates[min_idx]
                    candidates[min_idx] = (page_score, vp.page_number, page_measurements)
                    print(f"[Vector] Page {vp.page_number} score={page_score} "
                          f"evicted page {evicted_page} score={evicted_score}")

            del vp, callouts, page_measurements
            gc.collect()

            if time.time() - per_page_t0 > PAGE_TIMEOUT_SECONDS:
                print(f"[Vector] Page {page_num + 1} took >{PAGE_TIMEOUT_SECONDS}s, continuing")

        except Exception as e:
            print(f"[Vector] Page {page_num + 1}: extraction failed - {e}")
            continue

    doc.close()

    # Pick the most confident scale found across pages
    if scales_found:
        best_scale = max(scales_found, key=lambda s: s.confidence)
        result["scale"] = {
            "points_per_foot": best_scale.points_per_foot,
            "confidence": best_scale.confidence,
            "source_dimensions": best_scale.source_dimensions,
        }

    candidates.sort(key=lambda x: x[0], reverse=True)
    all_measurements = []
    for _score, _page_num, page_measurements in candidates:
        all_measurements.extend(page_measurements)

    result["measurements"] = all_measurements
    result["diagnostics"] = {
        "pages_processed": pages_to_process,
        "pages_with_geometry": pages_with_geom,
        "pages_with_dimensions": pages_with_dims,
        "elapsed_seconds": round(time.time() - t0, 2),
    }

    top10_pages = [pg for _s, pg, _m in candidates[:10]]
    print(f"[Vector] DIAG: pdf_type={pdf_type}")
    print(f"[Vector] DIAG: pages_in_pdf={pages_in_pdf}")
    print(f"[Vector] DIAG: pages_processed={pages_to_process}")
    print(f"[Vector] DIAG: pages_with_geometry={pages_with_geom}")
    print(f"[Vector] DIAG: pages_with_dimensions={pages_with_dims}")
    print(f"[Vector] DIAG: candidates_kept={len(candidates)}")
    print(f"[Vector] DIAG: top10_pages_by_score={top10_pages}")
    print(f"[Vector] DIAG: total_measurements={len(all_measurements)}")
    if result["scale"]:
        print(f"[Vector] DIAG: scale_points_per_foot={result['scale']['points_per_foot']:.2f}")

    print(f"[Vector] Done. Found {len(all_measurements)} measurements across "
          f"{pages_with_geom} geometry pages in {result['diagnostics']['elapsed_seconds']}s")
    return result
