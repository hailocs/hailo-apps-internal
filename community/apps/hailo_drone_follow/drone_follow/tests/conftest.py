"""Path setup so tests can import the drone_follow package."""

import os
import sys

# Add repo root (parent of drone_follow/) to sys.path
_repo_root = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if _repo_root not in sys.path:
    sys.path.insert(0, _repo_root)
