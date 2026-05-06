"""
Confidence Scorer
=================
BLOCK 6B: Text Segmentation & Chapter Detection Layer

Fusion system that combines multiple detection strategies
and produces a unified, high-confidence chapter list.
"""

import logging
from typing import List, Dict, Set
from collections import defaultdict

from app.services.document_structure.models import DetectedChapter

logger = logging.getLogger(__name__)


class ConfidenceScorer:
    """
    Fuse multiple chapter detection strategies into final chapter list.
    
    Strategy:
    1. Group detections by page overlap
    2. Calculate fusion confidence score
    3. Prefer higher-confidence methods (TOC > Heuristic > Structural)
    4. Resolve conflicts
    5. Output unified chapter list
    
    Confidence fusion formula:
    - Single detection: Use detection confidence
    - Multiple detections on same page: Max confidence + 0.1 boost (cap at 0.98)
    - Overlapping detections: Average confidence weighted by method priority
    """
    
    # Method priority (higher = more trusted)
    METHOD_PRIORITY = {
        'toc': 3,
        'heuristic': 2,
        'structural': 1,
        'manual': 4,  # Manual overrides (future)
    }
    
    def fuse_detections(
        self,
        detections: List[List[DetectedChapter]],
        min_confidence: float = 0.6
    ) -> List[DetectedChapter]:
        """
        Fuse multiple detection results into final chapter list.
        
        Args:
            detections: List of detection results from different strategies
            min_confidence: Minimum confidence threshold
            
        Returns:
            Unified list of chapters with fusion confidence scores
        """
        if not detections:
            return []
        
        # Flatten all detections
        all_detections = [ch for detection_list in detections for ch in detection_list]
        
        if not all_detections:
            return []
        
        # Group by page overlap
        page_groups = self._group_by_page_overlap(all_detections)
        
        # Fuse each group
        fused_chapters = []
        for group in page_groups:
            fused = self._fuse_group(group)
            if fused and fused.confidence >= min_confidence:
                fused_chapters.append(fused)
        
        # Sort by start page
        fused_chapters.sort(key=lambda c: c.start_page)
        
        # Assign order indices
        for i, chapter in enumerate(fused_chapters):
            chapter.order_index = i
        
        logger.info(
            f"Fused {len(all_detections)} detections into {len(fused_chapters)} chapters "
            f"(avg confidence: {self._avg_confidence(fused_chapters):.2f})"
        )
        
        return fused_chapters
    
    def _group_by_page_overlap(
        self,
        detections: List[DetectedChapter]
    ) -> List[List[DetectedChapter]]:
        """
        Group detections that refer to the same chapter (overlapping pages).
        
        Args:
            detections: All detections
            
        Returns:
            List of detection groups
        """
        if not detections:
            return []
        
        # Sort by start page
        sorted_detections = sorted(detections, key=lambda c: c.start_page)
        
        groups = []
        current_group = [sorted_detections[0]]
        
        for detection in sorted_detections[1:]:
            # Check if overlaps with current group
            group_start = min(d.start_page for d in current_group)
            group_end = max(d.end_page for d in current_group)
            
            # Overlap if detection starts before group ends
            if detection.start_page <= group_end + 1:  # Allow 1 page gap
                current_group.append(detection)
            else:
                # Start new group
                groups.append(current_group)
                current_group = [detection]
        
        # Add final group
        if current_group:
            groups.append(current_group)
        
        return groups
    
    def _fuse_group(self, group: List[DetectedChapter]) -> DetectedChapter:
        """
        Fuse a group of overlapping detections into single chapter.
        
        Args:
            group: Detections referring to same chapter
            
        Returns:
            Fused chapter with combined confidence
        """
        if not group:
            return None
        
        if len(group) == 1:
            return group[0]
        
        # Select best detection as base
        best = max(
            group,
            key=lambda d: (
                self.METHOD_PRIORITY.get(d.detection_method, 0),
                d.confidence
            )
        )
        
        # Calculate fusion confidence
        confidences = [d.confidence for d in group]
        methods = set(d.detection_method for d in group)
        
        # Base confidence from best detection
        fusion_confidence = best.confidence
        
        # Boost if multiple methods agree (max +0.15)
        if len(methods) > 1:
            method_boost = min(0.05 * (len(methods) - 1), 0.15)
            fusion_confidence = min(fusion_confidence + method_boost, 0.98)
        
        # Weighted average of other detections
        if len(group) > 1:
            weights = [
                self.METHOD_PRIORITY.get(d.detection_method, 1) 
                for d in group
            ]
            weighted_conf = sum(
                c * w for c, w in zip(confidences, weights)
            ) / sum(weights)
            
            # Blend with best
            fusion_confidence = 0.7 * fusion_confidence + 0.3 * weighted_conf
            fusion_confidence = min(fusion_confidence, 0.98)
        
        # Use consensus for page range
        start_page = min(d.start_page for d in group)
        end_page = max(d.end_page for d in group)
        
        # Create fused chapter
        fused = DetectedChapter(
            title=best.title,  # Use best detection's title
            start_page=start_page,
            end_page=end_page,
            confidence=fusion_confidence,
            detection_method=f"fusion({','.join(sorted(methods))})",
            text_content=best.text_content,
            char_count=best.char_count
        )
        
        logger.debug(
            f"Fused {len(group)} detections into chapter '{fused.title}' "
            f"(confidence: {fusion_confidence:.2f})"
        )
        
        return fused
    
    def _avg_confidence(self, chapters: List[DetectedChapter]) -> float:
        """Calculate average confidence of chapter list."""
        if not chapters:
            return 0.0
        return sum(c.confidence for c in chapters) / len(chapters)
