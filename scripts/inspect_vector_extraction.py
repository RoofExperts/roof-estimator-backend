"""
Inspect vector extraction output for a single PDF.

Doesn't compare against vision — just shows what the vector path produced,
including raw geometry counts, dimension callouts found, derived scale,
and final measurements.

Usage:
    python scripts/inspect_vector_extraction.py path/to/plan.pdf
"""
import sys
import json
from pathlib import Path

if len(sys.argv) != 2:
    print("Usage: python scripts/inspect_vector_extraction.py path/to/plan.pdf")
    sys.exit(1)

file_path = sys.argv[1]
if not Path(file_path).exists():
    print(f"File not found: {file_path}")
    sys.exit(1)

# Simulate page classifications (every page treated as roof_plan for inspection)
import fitz
doc = fitz.open(file_path)
fake_classifications = {
    i + 1: {"page_type": "roof_plan", "is_roof_relevant": True}
    for i in range(len(doc))
}
doc.close()

from vector_extraction import extract_vector_measurements, detect_pdf_type

print(f"\nFile: {file_path}")
print(f"PDF type: {detect_pdf_type(file_path)}")
print()

result = extract_vector_measurements(file_path, fake_classifications)
print(json.dumps(result, indent=2, default=str))

out_path = Path(file_path).with_suffix(".vector-inspect.json")
out_path.write_text(json.dumps(result, indent=2, default=str))
print(f"\nWritten to: {out_path}")
