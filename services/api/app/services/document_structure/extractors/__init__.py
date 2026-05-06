"""
Document Structure Extractors
==============================
Chapter detection strategies.
"""

from app.services.document_structure.extractors.toc_extractor import TOCExtractor
from app.services.document_structure.extractors.heuristic_detector import HeuristicDetector
from app.services.document_structure.extractors.structural_analyzer import StructuralAnalyzer

__all__ = [
    "TOCExtractor",
    "HeuristicDetector",
    "StructuralAnalyzer",
]
