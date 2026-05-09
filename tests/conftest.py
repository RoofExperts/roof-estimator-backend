"""
pytest configuration for the test suite.

Installs stubs for heavy C/Rust-backed libraries into sys.modules BEFORE any
test file is imported, so tests run in environments where the underlying system
libraries (cryptography/cffi/Rust) are broken or unavailable (e.g., some CI
sandboxes).

In production the real libraries are always installed and used.

Libraries stubbed here:
  - pdfplumber  (requires cryptography/cffi — broken in some containers)
  - fitz        (PyMuPDF — requires libmupdf — may be absent in lean CI images)
"""
import sys
import types

for _mod_name in ("pdfplumber", "fitz"):
    if _mod_name not in sys.modules:
        sys.modules[_mod_name] = types.ModuleType(_mod_name)
