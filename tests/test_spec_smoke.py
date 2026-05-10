"""
Smoke tests for the spec reader provider switch.

Does NOT call real APIs. Verifies:
  1. Provider selection from env vars
  2. Lazy client init fails gracefully when keys are missing
  3. Pydantic schema accepts expected shapes (single str, list of str, etc.)
  4. Markdown code fence stripping works

Run with: python -m pytest tests/test_spec_smoke.py -v
"""
import os
import sys
import pytest


def _reload_spec_ai():
    if "spec_ai" in sys.modules:
        del sys.modules["spec_ai"]
    import spec_ai
    return spec_ai


def test_default_provider_is_anthropic(monkeypatch):
    monkeypatch.delenv("SPEC_PROVIDER", raising=False)
    sa = _reload_spec_ai()
    assert sa.SPEC_PROVIDER == "anthropic"


def test_provider_switch_to_openai(monkeypatch):
    monkeypatch.setenv("SPEC_PROVIDER", "openai")
    sa = _reload_spec_ai()
    assert sa.SPEC_PROVIDER == "openai"


def test_default_anthropic_model_is_sonnet_46(monkeypatch):
    monkeypatch.delenv("SPEC_MODEL_ANTHROPIC", raising=False)
    sa = _reload_spec_ai()
    assert sa.SPEC_MODEL_ANTHROPIC == "claude-sonnet-4-6"


def test_anthropic_missing_key_raises(monkeypatch):
    monkeypatch.setenv("SPEC_PROVIDER", "anthropic")
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    sa = _reload_spec_ai()
    with pytest.raises(RuntimeError, match="ANTHROPIC_API_KEY"):
        sa._get_anthropic_client()


def test_openai_missing_key_raises(monkeypatch):
    monkeypatch.setenv("SPEC_PROVIDER", "openai")
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    sa = _reload_spec_ai()
    with pytest.raises(RuntimeError, match="OPENAI_API_KEY"):
        sa._get_openai_client()


def test_unknown_provider_returns_error(monkeypatch, tmp_path):
    """Unknown provider should return an error dict, not crash."""
    monkeypatch.setenv("SPEC_PROVIDER", "bogus")
    sa = _reload_spec_ai()
    # Pass a non-existent path; we just want to check the provider validation
    # short-circuits before extraction.
    fake_pdf = tmp_path / "fake.pdf"
    fake_pdf.write_bytes(b"%PDF-1.4\n%fake\n")
    result = sa.analyze_spec_text_from_pdf(str(fake_pdf))
    assert "error" in result
    assert "Unknown SPEC_PROVIDER" in result["error"]


def test_pydantic_schema_accepts_str_manufacturer():
    sa = _reload_spec_ai()
    obj = sa.SpecResult(membrane_type="TPO", manufacturer="Carlisle")
    assert obj.manufacturer == "Carlisle"


def test_pydantic_schema_accepts_list_manufacturer():
    sa = _reload_spec_ai()
    obj = sa.SpecResult(membrane_type="TPO", manufacturer=["Carlisle", "GAF", "Firestone"])
    assert isinstance(obj.manufacturer, list)
    assert "Carlisle" in obj.manufacturer


def test_pydantic_schema_accepts_int_warranty():
    sa = _reload_spec_ai()
    obj = sa.SpecResult(warranty_years=20)
    assert obj.warranty_years == 20


def test_pydantic_schema_accepts_str_warranty_range():
    sa = _reload_spec_ai()
    obj = sa.SpecResult(warranty_years="20-30")
    assert obj.warranty_years == "20-30"


def test_pydantic_schema_all_fields_optional():
    sa = _reload_spec_ai()
    obj = sa.SpecResult()  # No fields set
    # Should not raise; all fields default to None
    assert obj.membrane_type is None
    assert obj.warranty_years is None


# --------------------------------------------------------------------------
# Page-collector regression tests (fix-spec-page-collection)
# --------------------------------------------------------------------------
class _FakePage:
    """Minimal stand-in for a pdfplumber Page used by spec_ai's collector."""
    def __init__(self, text):
        self._text = text

    def extract_text(self, layout=False):
        return self._text

    def extract_tables(self):
        return []


class _FakePDF:
    def __init__(self, pages):
        self.pages = pages

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False


def _patch_pdfplumber(monkeypatch, pages):
    """Make pdfplumber.open() return a fake PDF wrapping the given pages."""
    import pdfplumber

    def _fake_open(_path):
        return _FakePDF(pages)

    monkeypatch.setattr(pdfplumber, "open", _fake_open, raising=False)


def test_non_roofing_division_page_is_not_collected(monkeypatch):
    """A page from Division 09 (Painting) packed with generic support
    keywords (INSULATION, SEALANT, FASTENER, MEMBRANE, ADHESIVE,
    MANUFACTURER) but ZERO roofing-specific keywords must NOT be
    collected as Division 07 content.

    Regression for the bug where the support-only fallback let
    non-roofing pages slip through when other trades happened to
    mention the same generic words.
    """
    div09_text = (
        "SECTION 099113 - INTERIOR PAINTING\n"
        "PART 1 - GENERAL\n"
        "1.1 SUMMARY\n"
        "A. Section includes painting of interior gypsum board surfaces\n"
        "   throughout the project. Coordinate with adjacent trades.\n"
        "1.2 SUBMITTALS\n"
        "A. Provide product data for paint, primer, and FASTENER schedule.\n"
        "B. Submit ADHESIVE compatibility report from the MANUFACTURER.\n"
        "C. Identify INSULATION clearances where painting overlaps\n"
        "   mechanical penetrations.\n"
        "1.3 QUALITY ASSURANCE\n"
        "A. Apply primer per the MANUFACTURER's printed instructions.\n"
        "PART 2 - PRODUCTS\n"
        "2.1 MATERIALS\n"
        "A. Paint base shall be compatible with existing SEALANT joints.\n"
        "B. MEMBRANE-faced gypsum board shall remain intact during prep.\n"
        "PART 3 - EXECUTION\n"
        "3.1 INSTALLATION\n"
        "A. Coordinate with adjacent trades for FASTENER spacing and\n"
        "   ADHESIVE cure times. Field-verify substrate moisture.\n"
    )
    sa = _reload_spec_ai()
    _patch_pdfplumber(monkeypatch, [_FakePage(div09_text)])

    # No roofing pages and no fallback hits -> None.
    result = sa.extract_division_7_from_pdf("/fake/path.pdf")
    assert result is None, (
        "Non-roofing Division 09 page was collected as Division 07 content. "
        "The support-only fallback should be gone."
    )


def test_roofing_page_with_specific_keyword_is_still_collected(monkeypatch):
    """Sanity: a real Division 07 membrane page with TPO, ROOF SYSTEM,
    and a 07 52 section header must still be collected. Guards against
    the tightening accidentally rejecting valid pages.
    """
    div07_text = (
        "SECTION 075423 - THERMOPLASTIC POLYOLEFIN ROOFING\n"
        "PART 1 - GENERAL\n"
        "1.1 SUMMARY\n"
        "A. Section includes a fully adhered TPO ROOF SYSTEM with\n"
        "   60-mil ROOFING MEMBRANE over POLYISO insulation.\n"
        "1.2 SUBMITTALS\n"
        "A. Provide product data including MIL thickness and WARRANTY terms.\n"
        "PART 2 - PRODUCTS\n"
        "2.1 MEMBRANE\n"
        "A. Approved MANUFACTURER: CARLISLE, FIRESTONE, GAF, JOHNS MANVILLE.\n"
        "B. THICKNESS: 60 mil minimum, FULLY ADHERED.\n"
    )
    sa = _reload_spec_ai()
    _patch_pdfplumber(monkeypatch, [_FakePage(div07_text)])

    result = sa.extract_division_7_from_pdf("/fake/path.pdf")
    assert result is not None
    assert result["page_count_collected"] == 1
    assert "TPO" in result["text"].upper()


# --------------------------------------------------------------------------
# Memory-bounded collection tests (Path A fix)
# --------------------------------------------------------------------------

def test_collection_caps_at_max_kept_pages(monkeypatch):
    """Synthesize a PDF with 200 valid Division 07 pages. The collector
    should keep at most MAX_KEPT_PAGES of them (the highest-scoring ones)
    rather than holding all 200 in memory.
    """
    sa = _reload_spec_ai()
    valid_div07_text = (
        "SECTION 075423 - THERMOPLASTIC POLYOLEFIN ROOFING\n"
        "PART 1 - GENERAL\n"
        "A. TPO ROOF SYSTEM with 60-mil ROOFING MEMBRANE.\n"
        "B. MANUFACTURER: CARLISLE.\n"
    )
    pages = [_FakePage(valid_div07_text) for _ in range(200)]
    _patch_pdfplumber(monkeypatch, pages)

    result = sa.extract_division_7_from_pdf("/fake/path.pdf")
    assert result is not None
    # Hard cap from spec
    assert result["page_count_collected"] <= sa.MAX_KEPT_PAGES, (
        f"Collected {result['page_count_collected']} pages; "
        f"expected at most {sa.MAX_KEPT_PAGES}"
    )
    assert result["page_count_total"] == 200


def test_high_scoring_page_evicts_low_scoring_when_cap_reached(monkeypatch):
    """When the candidate list is full of low-score pages, a higher-score
    page later in the PDF should replace one of them.
    """
    sa = _reload_spec_ai()

    # Build MAX_KEPT_PAGES pages of "low score" (just 1 specific keyword
    # plus a single div07 header to satisfy collection) ...
    low_score_text = (
        "SECTION 075423 - THERMOPLASTIC POLYOLEFIN ROOFING\n"
        "A. TPO is the system type.\n"
    )
    # ... and one final page with extra membrane-boost keywords for a
    # higher score.
    high_score_text = (
        "SECTION 075423 - THERMOPLASTIC POLYOLEFIN ROOFING\n"
        "A. TPO ROOF SYSTEM with FULLY ADHERED 60-MIL ROOFING MEMBRANE.\n"
        "B. POLYISOCYANURATE INSULATION over COVER BOARD.\n"
        "C. MANUFACTURER warranty terms specified.\n"
    )

    pages = [_FakePage(low_score_text)] * sa.MAX_KEPT_PAGES + [_FakePage(high_score_text)]
    _patch_pdfplumber(monkeypatch, pages)

    result = sa.extract_division_7_from_pdf("/fake/path.pdf")
    assert result is not None
    # The high-score page (1-indexed = MAX_KEPT_PAGES + 1) must appear in
    # the assembled text; its content includes phrases not in the low pages.
    assert "FULLY ADHERED" in result["text"].upper()
    assert result["page_count_collected"] == sa.MAX_KEPT_PAGES


def test_two_pass_does_not_hold_all_text_in_memory(monkeypatch):
    """Verify the implementation actually does the two-pass work: in Pass 1
    we should NOT call extract_text(layout=True). We track calls on a
    counter to enforce this.

    A correct implementation calls layout=True exactly N times, where N is
    the number of pages we keep (≤ MAX_KEPT_PAGES). An incorrect (single-
    pass) implementation calls it once per accepted page during Pass 1.
    """
    sa = _reload_spec_ai()

    layout_call_count = {"n": 0}

    class _CountingPage(_FakePage):
        def extract_text(self, layout=False):
            if layout:
                layout_call_count["n"] += 1
            return self._text

    valid_div07_text = (
        "SECTION 075423 - THERMOPLASTIC POLYOLEFIN ROOFING\n"
        "A. TPO ROOFING MEMBRANE 60 MIL fully adhered.\n"
        "B. MANUFACTURER: CARLISLE.\n"
    )
    pages = [_CountingPage(valid_div07_text) for _ in range(50)]
    _patch_pdfplumber(monkeypatch, pages)

    result = sa.extract_division_7_from_pdf("/fake/path.pdf")
    assert result is not None
    # Allow up to MAX_KEPT_PAGES * 2 to give room for fallback paths inside
    # the Pass 2 try/except, but the count MUST be ≤ pages collected.
    n_calls = layout_call_count["n"]
    assert n_calls <= result["page_count_collected"] * 2, (
        f"Layout extract called {n_calls} times but only "
        f"{result['page_count_collected']} pages collected — looks like "
        "Pass 1 is doing the heavy work too."
    )
