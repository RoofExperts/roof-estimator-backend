"""
A/B comparison harness for the vision providers.

Runs the SAME plan PDF through both Anthropic Claude Opus 4.7 and OpenAI GPT-4o,
prints the extracted measurements side-by-side, and writes a JSON report.

Usage:
    python scripts/compare_providers.py path/to/plan.pdf

Requires both ANTHROPIC_API_KEY and OPENAI_API_KEY to be set.
"""
import os
import sys
import json
import time
from pathlib import Path


def run_with_provider(provider: str, file_path: str) -> dict:
    """Run the full pipeline with a specific provider and return results."""
    os.environ["VISION_PROVIDER"] = provider
    if "vision_ai" in sys.modules:
        del sys.modules["vision_ai"]
    import vision_ai

    print(f"\n{'='*70}")
    print(f"  Running with VISION_PROVIDER={provider}")
    print(f"{'='*70}")

    t0 = time.time()
    page_images = vision_ai.convert_pdf_to_images(file_path)
    print(f"[{provider}] PDF converted to {len(page_images)} images in {time.time()-t0:.1f}s")

    results = {
        "provider": provider,
        "model": vision_ai.ANTHROPIC_MODEL if provider == "anthropic" else vision_ai.OPENAI_MODEL,
        "image_dpi": vision_ai.IMAGE_DPI,
        "page_count": len(page_images),
        "scale_detections": [],
        "page_classifications": [],
        "elapsed_seconds": 0,
    }

    # Classify each page
    for idx, page_data in enumerate(page_images[:5]):  # cap at 5 pages for the harness
        page_num = page_data["page_number"]
        cls = {}
        try:
            cls = vision_ai.classify_page(page_data["image_base64"])
            results["page_classifications"].append({
                "page": page_num,
                "type": cls.get("page_type"),
                "is_roof_relevant": cls.get("is_roof_relevant"),
            })
        except Exception as e:
            results["page_classifications"].append({"page": page_num, "error": str(e)})

        # Try scale detection on relevant pages
        if cls.get("page_type") in ("slab_plan", "roof_plan", "floor_plan"):
            try:
                scale = vision_ai.detect_scale(page_data["image_base64"])
                results["scale_detections"].append({
                    "page": page_num,
                    "scale_found": scale.get("scale_found"),
                    "scale_notation": scale.get("scale_notation"),
                    "scale_ratio": scale.get("scale_ratio"),
                    "confidence": scale.get("confidence"),
                })
            except Exception as e:
                results["scale_detections"].append({"page": page_num, "error": str(e)})

    results["elapsed_seconds"] = round(time.time() - t0, 1)
    return results


def main():
    if len(sys.argv) != 2:
        print("Usage: python scripts/compare_providers.py path/to/plan.pdf")
        sys.exit(1)

    file_path = sys.argv[1]
    if not Path(file_path).exists():
        print(f"File not found: {file_path}")
        sys.exit(1)

    if not os.getenv("ANTHROPIC_API_KEY"):
        print("ANTHROPIC_API_KEY not set"); sys.exit(1)
    if not os.getenv("OPENAI_API_KEY"):
        print("OPENAI_API_KEY not set"); sys.exit(1)

    anthropic_results = run_with_provider("anthropic", file_path)
    openai_results    = run_with_provider("openai",    file_path)

    report = {
        "input_file": file_path,
        "anthropic": anthropic_results,
        "openai":    openai_results,
    }

    out_path = Path(file_path).with_suffix(".comparison.json")
    out_path.write_text(json.dumps(report, indent=2))

    print(f"\n{'='*70}")
    print(f"  COMPARISON SUMMARY")
    print(f"{'='*70}")
    print(f"  Anthropic:  {anthropic_results['elapsed_seconds']}s, "
          f"{len(anthropic_results['scale_detections'])} scales detected")
    print(f"  OpenAI:     {openai_results['elapsed_seconds']}s, "
          f"{len(openai_results['scale_detections'])} scales detected")
    print(f"\n  Full report written to: {out_path}")


if __name__ == "__main__":
    main()
