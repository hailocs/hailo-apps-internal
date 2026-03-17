"""Retail shelf analyzer application for Hailo AI processors.

This package provides a retail shelf analysis pipeline that uses tiled inference
to detect small products on store shelves from high-resolution camera input.
Counts products per shelf zone and detects empty spots.
"""

from .retail_shelf_analyzer_pipeline import GStreamerRetailShelfAnalyzerApp

__all__ = [
    'GStreamerRetailShelfAnalyzerApp',
]
