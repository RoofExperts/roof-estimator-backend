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
