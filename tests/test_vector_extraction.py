"""
Smoke tests for vector extraction logic.

Tests don't require real PDFs — they exercise the pure Python parsing
and reconciliation logic with synthetic inputs.
"""
import os
import sys
import pytest


def _reload_modules():
    for mod in ("vector_extraction", "reconciliation"):
        if mod in sys.modules:
            del sys.modules[mod]


def test_dimension_parsing_feet_inches():
    _reload_modules()
    from vector_extraction import parse_dimension_text
    d = parse_dimension_text("47'-6\"")
    assert d is not None
    assert d.feet == 47.0
    assert d.inches == 6.0
    assert d.total_inches == 47 * 12 + 6


def test_dimension_parsing_with_fraction():
    _reload_modules()
    from vector_extraction import parse_dimension_text
    d = parse_dimension_text("12'-3 1/2\"")
    assert d is not None
    assert d.feet == 12.0
    assert d.inches == pytest.approx(3.5)


def test_dimension_parsing_bare_feet():
    _reload_modules()
    from vector_extraction import parse_dimension_text
    d = parse_dimension_text("47 FT")
    assert d is not None
    assert d.feet == 47.0


def test_dimension_parsing_rejects_non_dimension():
    _reload_modules()
    from vector_extraction import parse_dimension_text
    assert parse_dimension_text("ROOF PLAN") is None
    assert parse_dimension_text("") is None
    assert parse_dimension_text("This is just some text that is way too long to be a dimension") is None


def test_reconciliation_vector_wins_for_roof_area(monkeypatch):
    monkeypatch.setenv("VECTOR_DISCREPANCY_THRESHOLD_PCT", "15")
    _reload_modules()
    from reconciliation import reconcile
    vector_meas = [{"type": "roof_area", "value": 50000, "unit": "sqft", "confidence": 0.85}]
    vision_meas = [{"type": "roof_area", "value": 47000, "unit": "sqft", "confidence": 0.7}]
    result = reconcile(vector_meas, vision_meas)
    primary = result["primary"][0]
    assert primary["_primary_from"] == "vector"
    assert primary["value"] == 50000
    # 50000 vs 47000 = 6% diff, below threshold of 15%
    assert len(result["discrepancies"]) == 0


def test_reconciliation_flags_large_discrepancy(monkeypatch):
    monkeypatch.setenv("VECTOR_DISCREPANCY_THRESHOLD_PCT", "15")
    _reload_modules()
    from reconciliation import reconcile
    vector_meas = [{"type": "roof_area", "value": 50000, "unit": "sqft", "confidence": 0.85}]
    vision_meas = [{"type": "roof_area", "value": 30000, "unit": "sqft", "confidence": 0.7}]
    result = reconcile(vector_meas, vision_meas)
    # 50000 vs 30000 = 40% diff, well above 15%
    assert len(result["discrepancies"]) == 1
    d = result["discrepancies"][0]
    assert d["extraction_type"] == "roof_area"
    assert d["discrepancy_pct"] > 15


def test_reconciliation_vision_wins_for_drain_count():
    _reload_modules()
    from reconciliation import reconcile
    # Vector typically doesn't produce drain counts; test that vision wins
    vector_meas = []
    vision_meas = [{"type": "roof_drain", "value": 12, "unit": "each", "confidence": 0.8}]
    result = reconcile(vector_meas, vision_meas)
    primary = result["primary"][0]
    assert primary["_primary_from"] == "vision"
    assert primary["value"] == 12


def test_reconciliation_passes_through_labeled_dimensions():
    _reload_modules()
    from reconciliation import reconcile
    vector_meas = [
        {"type": "labeled_dimension", "value": 47.5, "unit": "lnft", "confidence": 0.9, "notes": "47'-6\""},
    ]
    result = reconcile(vector_meas, [])
    types = [m["type"] for m in result["primary"]]
    assert "labeled_dimension" in types


def test_vector_disabled_returns_empty(monkeypatch, tmp_path):
    monkeypatch.setenv("VECTOR_EXTRACTION_ENABLED", "false")
    _reload_modules()
    from vector_extraction import extract_vector_measurements
    fake_pdf = tmp_path / "fake.pdf"
    # Just need a real path; the function should short-circuit before opening
    fake_pdf.write_bytes(b"%PDF-1.4\n%fake\n")
    result = extract_vector_measurements(str(fake_pdf), {})
    assert result["pdf_type"] == "raster"
    assert result["measurements"] == []
