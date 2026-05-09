"""
Smoke tests for the vision provider switch.

These tests do NOT call real APIs. They verify:
  1. Provider configuration loads correctly from env vars
  2. The correct client is selected based on VISION_PROVIDER
  3. Pre-flight checks fail gracefully when keys are missing

Run with: python -m pytest tests/test_vision_smoke.py -v
"""
import os
import pytest


def _reload_vision_ai():
    """Reload vision_ai with current env vars."""
    import sys
    if "vision_ai" in sys.modules:
        del sys.modules["vision_ai"]
    import vision_ai
    return vision_ai


def test_default_provider_is_anthropic(monkeypatch):
    monkeypatch.delenv("VISION_PROVIDER", raising=False)
    va = _reload_vision_ai()
    assert va.VISION_PROVIDER == "anthropic"


def test_provider_switch_to_openai(monkeypatch):
    monkeypatch.setenv("VISION_PROVIDER", "openai")
    va = _reload_vision_ai()
    assert va.VISION_PROVIDER == "openai"


def test_anthropic_dpi_is_higher_than_openai(monkeypatch):
    monkeypatch.setenv("VISION_PROVIDER", "anthropic")
    va = _reload_vision_ai()
    anth_dpi = va.IMAGE_DPI

    monkeypatch.setenv("VISION_PROVIDER", "openai")
    va = _reload_vision_ai()
    oai_dpi = va.IMAGE_DPI

    assert anth_dpi > oai_dpi, "Anthropic should use higher DPI than OpenAI"


def test_anthropic_missing_key_raises(monkeypatch):
    monkeypatch.setenv("VISION_PROVIDER", "anthropic")
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    va = _reload_vision_ai()
    with pytest.raises(RuntimeError, match="ANTHROPIC_API_KEY"):
        va._get_anthropic_client()


def test_openai_missing_key_raises(monkeypatch):
    monkeypatch.setenv("VISION_PROVIDER", "openai")
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    va = _reload_vision_ai()
    with pytest.raises(RuntimeError, match="OPENAI_API_KEY"):
        va._get_openai_client()


def test_unknown_provider_raises(monkeypatch):
    monkeypatch.setenv("VISION_PROVIDER", "bogus")
    va = _reload_vision_ai()
    with pytest.raises(RuntimeError, match="Unknown VISION_PROVIDER"):
        va.call_vision_api("fake_b64", "fake_prompt")
