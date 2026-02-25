"""
PII Detection Module

This module identifies Personally Identifiable Information (PII) in OCR-extracted
text using regex patterns and contextual analysis.

Why regex: Regex provides precise, deterministic pattern matching for structured
PII like CCCD numbers and dates. It's faster than ML-based NER for known patterns.
"""

import re
from typing import List, Dict, Any, Tuple, Optional
from dataclasses import dataclass

from config import PipelineConfig
from utils.logger import setup_logger, log_with_context


logger = setup_logger(__name__)


@dataclass
class PIIMatch:
    """
    Data class representing a detected PII instance.
    
    Why dataclass: Provides clean, type-safe structure for PII matches.
    Makes code more maintainable and self-documenting.
    """
    pii_type: str          # Type of PII (cccd, name, dob, etc.)
    value: str             # The actual PII text
    confidence: float      # Detection confidence (0-1)
    bbox: List[List[int]]  # Bounding box from OCR [[x1,y1], [x2,y2], [x3,y3], [x4,y4]]
    page: int              # Page number (0-indexed)
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return {
            'type': self.pii_type,
            'value_length': len(self.value),  # Store length, not actual value for privacy
            'confidence': round(self.confidence, 3),
            'bbox': self._bbox_to_xyxywh(),
            'page': self.page
        }
        
    def _bbox_to_xyxywh(self) -> List[int]:
        """
        Convert bounding box to [x, y, width, height] format.
        
        Returns:
            [x, y, w, h] where (x,y) is top-left corner
            
        Why this format: Standard bounding box format used in computer vision.
        Makes it compatible with OpenCV drawing functions.
        """
        if not self.bbox or len(self.bbox) < 4:
            return [0, 0, 0, 0]
            
        # Extract all x and y coordinates
        x_coords = [point[0] for point in self.bbox]
        y_coords = [point[1] for point in self.bbox]
        
        x_min = int(min(x_coords))
        y_min = int(min(y_coords))
        x_max = int(max(x_coords))
        y_max = int(max(y_coords))
        
        width = x_max - x_min
        height = y_max - y_min
        
        return [x_min, y_min, width, height]


class PIIDetector:
    """
    Detects various types of PII in OCR-extracted text.
    
    Why pattern-based: For structured PII (IDs, dates, phones), regex patterns
    provide deterministic, explainable results. They're also much faster than
    ML models and don't require training data.
    """
    
    def __init__(self):
        """Initialize the detector with configured patterns."""
        self.patterns = {
            pii_type: re.compile(pattern, re.IGNORECASE | re.UNICODE)
            for pii_type, pattern in PipelineConfig.PII_PATTERNS.items()
        }
        logger.info(f"PII Detector initialized with {len(self.patterns)} patterns")
        
    def _calculate_confidence(
        self, 
        pii_type: str, 
        match: re.Match, 
        ocr_confidence: float
    ) -> float:
        """
        Calculate detection confidence score.
        
        Args:
            pii_type: Type of PII detected
            match: Regex match object
            ocr_confidence: OCR confidence for this text region
            
        Returns:
            Combined confidence score (0-1)
            
        Why combined confidence: Both regex match quality and OCR confidence
        matter. A perfect regex match on poorly-recognized text is less reliable
        than a perfect match on clear text.
        """
        # Base confidence from regex match quality
        regex_confidence = 1.0  # Assume perfect match for now
        
        # For structured data (CCCD, phone), exact length match increases confidence
        if pii_type in ['cccd', 'phone']:
            matched_text = match.group(0)
            # Remove non-digits
            digits_only = re.sub(r'\D', '', matched_text)
            expected_length = 12 if pii_type == 'cccd' else 10
            
            if len(digits_only) == expected_length:
                regex_confidence = 1.0
            else:
                regex_confidence = 0.7  # Partial match
                
        # Combine with OCR confidence (weighted average)
        combined = (regex_confidence * 0.6) + (ocr_confidence * 0.4)
        
        return min(combined, 1.0)
        
    def detect_in_text(
        self, 
        text: str, 
        bbox: List[List[int]], 
        ocr_confidence: float,
        page: int = 0
    ) -> List[PIIMatch]:
        """
        Detect PII in a single text region.
        
        Args:
            text: OCR-extracted text
            bbox: Bounding box of the text region
            ocr_confidence: OCR confidence score
            page: Page number
            
        Returns:
            List of PIIMatch objects
            
        Why per-region detection: Each OCR result has its own bounding box.
        We need to associate detected PII with its spatial location.
        """
        matches = []
        
        for pii_type, pattern in self.patterns.items():
            for regex_match in pattern.finditer(text):
                confidence = self._calculate_confidence(
                    pii_type, 
                    regex_match, 
                    ocr_confidence
                )
                
                # Only include high-confidence matches
                if confidence >= 0.5:
                    pii_match = PIIMatch(
                        pii_type=pii_type,
                        value=regex_match.group(0),
                        confidence=confidence,
                        bbox=bbox,
                        page=page
                    )
                    matches.append(pii_match)
                    
                    log_with_context(
                        logger, 'debug', 'PII detected',
                        pii_type=pii_type,
                        confidence=confidence,
                        page=page
                    )
                    
        return matches
        
    def detect_in_ocr_results(
        self, 
        ocr_results: List[Dict[str, Any]]
    ) -> List[PIIMatch]:
        """
        Detect PII across all OCR results from a document.
        
        Args:
            ocr_results: List of OCR results per page from OCREngine
            
        Returns:
            List of all detected PII matches
            
        Why: Orchestrates PII detection across entire multi-page documents,
        properly tracking page numbers and coordinates.
        """
        all_matches = []
        
        for page_data in ocr_results:
            page_num = page_data.get('page', 0)
            ocr_page_results = page_data.get('ocr_results', [])
            
            for bbox, text, confidence in ocr_page_results:
                # Skip low-confidence OCR results
                if confidence < 0.3:
                    continue
                    
                # Detect PII in this text region
                pii_matches = self.detect_in_text(
                    text=text,
                    bbox=bbox,
                    ocr_confidence=confidence,
                    page=page_num
                )
                
                all_matches.extend(pii_matches)
                
        log_with_context(
            logger, 'info', 'PII detection completed',
            total_matches=len(all_matches),
            pages_processed=len(ocr_results)
        )
        
        return all_matches
        
    def get_pii_statistics(self, matches: List[PIIMatch]) -> Dict[str, int]:
        """
        Get statistics about detected PII.
        
        Args:
            matches: List of PII matches
            
        Returns:
            Dictionary mapping PII type to count
            
        Why: Useful for logging, monitoring, and validating that the
        detection process is working as expected.
        """
        stats = {}
        
        for match in matches:
            pii_type = match.pii_type
            stats[pii_type] = stats.get(pii_type, 0) + 1
            
        return stats
