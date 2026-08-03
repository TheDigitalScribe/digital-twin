"""Pytest configuration.

Ensures the project root directory is on ``sys.path`` so that the
``digitaltwin`` package can be imported by tests regardless of how pytest
is invoked.

Also guarantees a hermetic test environment: `TWIN_BACKGROUND` is always set
to a minimal placeholder so importing ``context`` never raises. In a dev
environment with a real ``.env``, the real value wins (``setdefault`` doesn't
override existing env vars).
"""

import os
import sys

# Add the project root (parent of this tests/ dir) to sys.path so that
# ``import digitaltwin`` resolves correctly.
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

# Ensure a background source exists for hermetic CI runs. The real .env /
# local linkedin.pdf take precedence when present; this only guarantees that
# importing context.py never crashes for lack of a background source.
os.environ.setdefault(
    "TWIN_BACKGROUND",
    (
        "Test Candidate\nSoftware Engineer\n"
        "test@example.com\nlinkedin.com/in/testcandidate\n"
        "Skills: Python, Kubernetes, AWS\n"
        "Experience: Senior Engineer at Example Corp (4 years)."
    ),
)

# The tests/ suite must never require real API credentials. Any accidental
# access to the OpenAI client during tests will fail loudly on missing key.
os.environ.setdefault("OPENAI_API_KEY", "test-invalid-key-not-used")