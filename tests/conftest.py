"""
pytest configuration for the test suite.

Installs a pdfplumber stub into sys.modules BEFORE any test file is imported,
so that tests run in environments where the underlying C/Rust libraries
(cryptography/cffi) are broken or unavailable (e.g., some CI sandboxes).

In production the real pdfplumber is always installed and used.
"""
import sys
import types

# Install the stub unconditionally at collection time if pdfplumber is not
# already cleanly importable. We do this at module level (not inside a fixture)
# so spec_ai can be imported during test collection without hitting the Rust panic.
if "pdfplumber" not in sys.modules:
    stub = types.ModuleType("pdfplumber")
    sys.modules["pdfplumber"] = stub
