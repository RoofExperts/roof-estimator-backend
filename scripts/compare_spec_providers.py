"""
A/B comparison harness for the spec reader providers.

Runs the SAME spec PDF through Claude Sonnet 4.6 and gpt-4o-mini, prints
results side-by-side, writes a JSON report.

Usage:
    python scripts/compare_spec_providers.py path/to/spec.pdf

Requires both ANTHROPIC_API_KEY and OPENAI_API_KEY to be set.
"""
import os
import sys
import json
import time
from pathlib import Path


def run_with_provider(provider: str, file_path: str) -> dict:
    os.environ["SPEC_PROVIDER"] = provider
    if "spec_ai" in sys.modules:
        del sys.modules["spec_ai"]
    import spec_ai

    print(f"\n{'=' * 70}")
    print(f"  Running spec reader with SPEC_PROVIDER={provider}")
    print(f"  Model: {spec_ai.SPEC_MODEL_ANTHROPIC if provider == 'anthropic' else spec_ai.SPEC_MODEL_OPENAI}")
    print(f"{'=' * 70}")

    t0 = time.time()
    try:
        result = spec_ai.analyze_spec_text_from_pdf(file_path)
    except Exception as e:
        result = {"error": str(e)}
    elapsed = round(time.time() - t0, 1)

    return {
        "provider": provider,
        "model": spec_ai.SPEC_MODEL_ANTHROPIC if provider == "anthropic" else spec_ai.SPEC_MODEL_OPENAI,
        "elapsed_seconds": elapsed,
        "result": result,
    }


def diff_field(name: str, a, b):
    if a == b:
        return f"  ✓  {name}: {a!r} (match)"
    return f"  ✗  {name}:\n      anthropic: {a!r}\n      openai:    {b!r}"


def main():
    if len(sys.argv) != 2:
        print("Usage: python scripts/compare_spec_providers.py path/to/spec.pdf")
        sys.exit(1)

    file_path = sys.argv[1]
    if not Path(file_path).exists():
        print(f"File not found: {file_path}")
        sys.exit(1)

    if not os.getenv("ANTHROPIC_API_KEY"):
        print("ANTHROPIC_API_KEY not set"); sys.exit(1)
    if not os.getenv("OPENAI_API_KEY"):
        print("OPENAI_API_KEY not set"); sys.exit(1)

    anth = run_with_provider("anthropic", file_path)
    oai  = run_with_provider("openai",    file_path)

    print(f"\n{'=' * 70}")
    print(f"  COMPARISON")
    print(f"{'=' * 70}")
    print(f"  Anthropic: {anth['elapsed_seconds']}s ({anth['model']})")
    print(f"  OpenAI:    {oai['elapsed_seconds']}s ({oai['model']})")
    print()

    a_res = anth["result"]
    o_res = oai["result"]
    if "error" in a_res or "error" in o_res:
        print("  At least one provider returned an error:")
        if "error" in a_res: print(f"    Anthropic: {a_res['error']}")
        if "error" in o_res: print(f"    OpenAI:    {o_res['error']}")
    else:
        for field in ["roof_system_type", "membrane_type", "membrane_thickness",
                      "attachment_method", "insulation_type", "cover_board",
                      "warranty_years", "manufacturer"]:
            print(diff_field(field, a_res.get(field), o_res.get(field)))

    out_path = Path(file_path).with_suffix(".spec-comparison.json")
    out_path.write_text(json.dumps({
        "input_file": file_path,
        "anthropic": anth,
        "openai":    oai,
    }, indent=2))
    print(f"\n  Full report written to: {out_path}")


if __name__ == "__main__":
    main()
