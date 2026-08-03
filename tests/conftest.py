"""Pytest configuration.

Ensures the project root directory is on ``sys.path`` so that modules living
at the project root (e.g. ``security.py``) can be imported by tests in this
``tests/`` package regardless of how pytest is invoked.

Also guarantees a hermetic test environment: if no background source is
configured (no TWIN_BACKGROUND env var and no local linkedin.pdf), a minimal
placeholder is injected so that importing ``context`` never raises. In a dev
environment with a real ``.env`` this fallback is ignored (``.env`` wins).
"""

import os
import sys

# Add the project root (parent of this tests/ dir) to sys.path so that
# ``import security`` resolves correctly.
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