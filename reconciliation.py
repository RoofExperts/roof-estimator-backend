"""
Reconciliation: merge vector-path and vision-path measurement candidates
into a final "primary" set, with discrepancies flagged for review.

Inputs:
  - vector_measurements: list[dict] from vector_extraction.extract_vector_measurements
  - vision_measurements: list[dict] from vision_ai's existing pipeline

Both lists use the same schema. Each measurement has:
  type, value, unit, confidence, notes, source, measurement_method, _source_page_type

Reconciliation rules per measurement_type:

  roof_area:
    - If vector has a high-confidence value (>=0.8), it wins as primary.
    - Else, vision wins.
    - Discrepancy = abs(vector - vision) / max(vector, vision) * 100
    - Flag if discrepancy > VECTOR_DISCREPANCY_THRESHOLD_PCT.

  perimeter, parapet_wall, coping, curb:
    - Same as roof_area.

  roof_drain, scupper, pitch_pan, pipe (counts):
    - Vector typically does not produce these (we don't classify equipment).
    - Vision wins. No discrepancy.

  parapet_flashing (heights):
    - Vision wins (these come from elevation drawings; vector contribution is rare).

  labeled_dimension:
    - Stored as-is for the review UI. Not reconciled with vision.

The output is:
  {
    "primary": [<measurement dicts marked source="primary" with provenance>],
    "discrepancies": [<discrepancy dicts>],
    "all_candidates": [<every input measurement with source preserved>],
  }

Each primary measurement carries `_primary_from`: "vector" or "vision" and
`_alternate_value` if both sources contributed.
"""

import os


def _threshold_pct() -> float:
    """Read the discrepancy threshold at call time so tests can override via env."""
    return float(os.getenv("VECTOR_DISCREPANCY_THRESHOLD_PCT", "15"))


# Types where vector typically wins (geometric measurements)
VECTOR_PREFERRED_TYPES = {
    "roof_area", "perimeter", "parapet_wall", "coping", "curb",
    "building_area", "building_dimensions",
}

# Types where vision typically wins (counts, elevations, schedules)
VISION_PREFERRED_TYPES = {
    "roof_drain", "scupper", "pitch_pan", "pipe",
    "parapet_flashing", "parapet_flashing_low", "parapet_flashing_mid", "parapet_flashing_high",
    "collector_head", "downspout", "rooftop_equipment",
    # Plurals (existing aliases)
    "roof_drains", "scuppers", "pitch_pans", "pipes",
    "collector_heads", "downspouts",
}


def reconcile(vector_measurements: list, vision_measurements: list) -> dict:
    """Merge vector + vision measurements; flag discrepancies."""
    # Tag source on every input
    for m in vector_measurements:
        m.setdefault("source", "vector")
    for m in vision_measurements:
        m.setdefault("source", "vision")

    all_candidates = list(vector_measurements) + list(vision_measurements)

    # Group by extraction_type
    by_type = {}
    for m in all_candidates:
        by_type.setdefault(m.get("type"), []).append(m)

    primary = []
    discrepancies = []

    for ext_type, candidates in by_type.items():
        if ext_type == "labeled_dimension":
            # Pass through unchanged — the review UI uses these directly
            primary.extend(candidates)
            continue

        vec = [c for c in candidates if c.get("source") == "vector"]
        vis = [c for c in candidates if c.get("source") == "vision"]

        if vec and vis:
            chosen, alternate, disc = _reconcile_with_both(ext_type, vec, vis)
            if disc is not None:
                discrepancies.append(disc)
            chosen["_primary_from"] = chosen["source"]
            chosen["_alternate_value"] = alternate.get("value") if alternate else None
            chosen["_alternate_source"] = alternate.get("source") if alternate else None
            primary.append(chosen)
        elif vec:
            chosen = _best(vec)
            chosen["_primary_from"] = "vector"
            chosen["_alternate_value"] = None
            primary.append(chosen)
        elif vis:
            chosen = _best(vis)
            chosen["_primary_from"] = "vision"
            chosen["_alternate_value"] = None
            primary.append(chosen)

    return {
        "primary": primary,
        "discrepancies": discrepancies,
        "all_candidates": all_candidates,
    }


def _best(candidates: list) -> dict:
    """Pick the highest-confidence candidate from a list."""
    return max(candidates, key=lambda c: c.get("confidence", 0))


def _reconcile_with_both(ext_type: str, vec: list, vis: list) -> tuple:
    """Choose between vector and vision when both sources contributed.

    Returns (chosen, alternate, discrepancy_or_none).
    """
    best_vec = _best(vec)
    best_vis = _best(vis)

    # Determine which source to prefer
    if ext_type in VECTOR_PREFERRED_TYPES:
        # Prefer vector unless its confidence is much lower
        if best_vec.get("confidence", 0) >= 0.6:
            chosen, alternate = best_vec, best_vis
        else:
            chosen, alternate = best_vis, best_vec
    elif ext_type in VISION_PREFERRED_TYPES:
        chosen, alternate = best_vis, best_vec
    else:
        # Default: highest confidence wins
        if best_vec.get("confidence", 0) >= best_vis.get("confidence", 0):
            chosen, alternate = best_vec, best_vis
        else:
            chosen, alternate = best_vis, best_vec

    # Compute discrepancy
    v1 = float(best_vec.get("value") or 0)
    v2 = float(best_vis.get("value") or 0)
    disc = None
    if v1 > 0 and v2 > 0:
        max_val = max(v1, v2)
        pct = abs(v1 - v2) / max_val * 100.0
        if pct > _threshold_pct():
            disc = {
                "extraction_type": ext_type,
                "unit": chosen.get("unit"),
                "vector_value": v1,
                "vision_value": v2,
                "discrepancy_pct": round(pct, 1),
                "primary_source": chosen.get("source"),
                "primary_value": chosen.get("value"),
                "needs_review": True,
                "notes": (
                    f"Vector and vision disagree by {pct:.1f}% on {ext_type}. "
                    f"Primary={chosen.get('source')}={chosen.get('value')}, "
                    f"alt={alternate.get('source')}={alternate.get('value')}."
                ),
            }

    return chosen, alternate, disc
