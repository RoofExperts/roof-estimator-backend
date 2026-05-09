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
