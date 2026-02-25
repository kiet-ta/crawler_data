"""
Redaction Module

This module handles the visual redaction of PII by drawing black boxes over
detected sensitive information in images and PDFs.

Why visual redaction: Unlike simple text removal, visual redaction ensures that
the original document structure is preserved while making PII unreadable. This
is crucial for ML training where document layout matters.
"""

from typing import List, Dict, Any, Tuple
from pathlib import Path
import numpy as np
import cv2
from pdf2image import convert_from_path
from PIL import Image

from config import PipelineConfig
from modules.processing.pii_detector import PIIMatch
from utils.logger import setup_logger, log_with_context


logger = setup_logger(__name__)


class DocumentRedactor:
    """
    Handles visual redaction of PII in documents.
    
    Why class-based: Encapsulates redaction logic and configuration,
    making it easy to adjust redaction parameters without modifying
    the core algorithm.
    """
    
    def __init__(self):
        """Initialize redactor with configuration settings."""
        self.redaction_color = PipelineConfig.REDACTION_COLOR
        self.redaction_thickness = PipelineConfig.REDACTION_THICKNESS
        self.padding = PipelineConfig.REDACTION_PADDING
        
    def _draw_redaction_box(
        self, 
        image: np.ndarray, 
        bbox: List[int]
    ) -> np.ndarray:
        """
        Draw a black box over a region of the image.
        
        Args:
            image: Image as numpy array
            bbox: Bounding box as [x, y, width, height]
            
        Returns:
            Modified image with redaction box
            
        Why padding: Adding padding around detected text ensures we don't
        miss any pixels at the edges due to OCR bounding box inaccuracies.
        """
        x, y, w, h = bbox
        
        # Apply padding
        x = max(0, x - self.padding)
        y = max(0, y - self.padding)
        w = w + (2 * self.padding)
        h = h + (2 * self.padding)
        
        # Ensure we don't go beyond image boundaries
        img_height, img_width = image.shape[:2]
        w = min(w, img_width - x)
        h = min(h, img_height - y)
        
        # Draw filled rectangle
        cv2.rectangle(
            image,
            (x, y),
            (x + w, y + h),
            self.redaction_color,
            self.redaction_thickness
        )
        
        return image
        
    def redact_image(
        self, 
        image: np.ndarray, 
        pii_matches: List[PIIMatch],
        page_num: int = 0
    ) -> Tuple[np.ndarray, int]:
        """
        Redact PII from a single image.
        
        Args:
            image: Image as numpy array
            pii_matches: List of PII matches to redact
            page_num: Page number (for multi-page documents)
            
        Returns:
            Tuple of (redacted_image, redaction_count)
            
        Why return count: Tracking redaction count helps validate that
        the redaction process is working correctly.
        """
        redacted_image = image.copy()
        redaction_count = 0
        
        for match in pii_matches:
            # Only redact matches from this page
            if match.page != page_num:
                continue
                
            try:
                bbox = match._bbox_to_xyxywh()
                redacted_image = self._draw_redaction_box(redacted_image, bbox)
                redaction_count += 1
                
                log_with_context(
                    logger, 'debug', 'Applied redaction',
                    pii_type=match.pii_type,
                    page=page_num,
                    bbox=bbox
                )
                
            except Exception as e:
                # Log but continue - don't let one bad redaction stop the whole process
                log_with_context(
                    logger, 'warning', 'Failed to apply redaction',
                    pii_type=match.pii_type,
                    page=page_num,
                    error=str(e)
                )
                continue
                
        log_with_context(
            logger, 'info', 'Image redaction completed',
            page=page_num,
            redactions_applied=redaction_count
        )
        
        return redacted_image, redaction_count
        
    def redact_pdf(
        self, 
        pdf_path: Path, 
        pii_matches: List[PIIMatch],
        output_path: Path
    ) -> Dict[str, Any]:
        """
        Redact PII from a PDF document.
        
        Args:
            pdf_path: Path to input PDF
            pii_matches: List of PII matches to redact
            output_path: Path to save redacted PDF
            
        Returns:
            Dictionary with redaction metadata
            
        Why PDF handling: PDFs need special handling - convert to images,
        redact, then save as images or reassemble into PDF. We save as
        images for simplicity in this pipeline.
        """
        logger.info(f"Redacting PDF: {pdf_path.name}")
        
        try:
            # Convert PDF to images
            images = convert_from_path(pdf_path, dpi=300)
            
            total_redactions = 0
            redacted_images = []
            
            for page_num, image in enumerate(images):
                # Convert PIL Image to numpy array
                img_array = np.array(image)
                
                # Redact this page
                redacted_img, redaction_count = self.redact_image(
                    img_array, 
                    pii_matches, 
                    page_num
                )
                
                redacted_images.append(redacted_img)
                total_redactions += redaction_count
                
            # Save redacted version
            # For multi-page PDFs, we save as PNG images (page_0.png, page_1.png, etc.)
            # In production, you might want to reassemble into a PDF
            if len(redacted_images) == 1:
                # Single page - save as single image
                output_img_path = output_path.with_suffix('.png')
                cv2.imwrite(str(output_img_path), redacted_images[0])
                saved_files = [output_img_path.name]
            else:
                # Multi-page - save each page
                saved_files = []
                base_name = output_path.stem
                
                for page_num, redacted_img in enumerate(redacted_images):
                    page_output = output_path.parent / f"{base_name}_page_{page_num}.png"
                    cv2.imwrite(str(page_output), redacted_img)
                    saved_files.append(page_output.name)
                    
            log_with_context(
                logger, 'info', 'PDF redaction completed',
                filename=pdf_path.name,
                pages=len(redacted_images),
                total_redactions=total_redactions
            )
            
            return {
                'original_file': pdf_path.name,
                'redacted_files': saved_files,
                'pages': len(redacted_images),
                'total_redactions': total_redactions
            }
            
        except Exception as e:
            log_with_context(
                logger, 'error', 'PDF redaction failed',
                filename=pdf_path.name,
                error=str(e),
                error_type=type(e).__name__
            )
            raise
            
    def redact_image_file(
        self, 
        image_path: Path, 
        pii_matches: List[PIIMatch],
        output_path: Path
    ) -> Dict[str, Any]:
        """
        Redact PII from a standalone image file.
        
        Args:
            image_path: Path to input image
            pii_matches: List of PII matches to redact
            output_path: Path to save redacted image
            
        Returns:
            Dictionary with redaction metadata
        """
        logger.info(f"Redacting image: {image_path.name}")
        
        try:
            # Read image
            image = cv2.imread(str(image_path))
            
            if image is None:
                raise ValueError(f"Failed to read image: {image_path}")
                
            # Redact
            redacted_image, redaction_count = self.redact_image(
                image, 
                pii_matches, 
                page_num=0
            )
            
            # Save
            cv2.imwrite(str(output_path), redacted_image)
            
            log_with_context(
                logger, 'info', 'Image redaction completed',
                filename=image_path.name,
                redactions=redaction_count
            )
            
            return {
                'original_file': image_path.name,
                'redacted_file': output_path.name,
                'total_redactions': redaction_count
            }
            
        except Exception as e:
            log_with_context(
                logger, 'error', 'Image redaction failed',
                filename=image_path.name,
                error=str(e),
                error_type=type(e).__name__
            )
            raise


def redact_document(
    document_path: Path,
    pii_matches: List[PIIMatch],
    output_dir: Path
) -> Dict[str, Any]:
    """
    Convenience function to redact a document (auto-detects PDF vs image).
    
    Args:
        document_path: Path to document to redact
        pii_matches: List of PII matches
        output_dir: Directory to save redacted files
        
    Returns:
        Redaction metadata dictionary
        
    Why: Provides a simple interface that automatically handles different
    file types without the caller needing to know the details.
    """
    redactor = DocumentRedactor()
    
    # Determine output path
    output_path = output_dir / f"redacted_{document_path.name}"
    
    # Process based on file type
    if document_path.suffix.lower() == '.pdf':
        return redactor.redact_pdf(document_path, pii_matches, output_path)
    else:
        # Assume image
        return redactor.redact_image_file(document_path, pii_matches, output_path)
