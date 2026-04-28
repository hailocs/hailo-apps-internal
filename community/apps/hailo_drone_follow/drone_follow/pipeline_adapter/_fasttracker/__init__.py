"""Vendored FastTracker tracker files.

Source: https://github.com/Hamidreza-Hashempoor/FastTracker
License: MIT

Heavy dependencies (torch, lap, cython_bbox) replaced with scipy/numpy equivalents.
Only the tracker logic is included — no detector or C++ extensions.
"""

from .fasttracker import Fasttracker

__all__ = ["Fasttracker"]
