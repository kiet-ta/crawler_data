"""
OCR Engine Module

This module handles Optical Character Recognition (OCR) for extracting text
from PDF documents and images.

Why EasyOCR: EasyOCR provides excellent support for Vietnamese text recognition
and doesn't require separate language pack installations like Tesseract.
"""

import re
from typing import List, Dict, Any, Tuple, Optional
from pathlib import Path
import numpy as np
import cv2
from pdf2image import convert_from_path
import easyocr

from config import PipelineConfig
from utils.logger import setup_logger, log_with_context


logger = setup_logger(__name__)


class OCREngine:
    """
    Wrapper for EasyOCR with optimized configuration for document processing.
    
    Why a wrapper: Encapsulating EasyOCR in a wrapper class allows us to:
    1. Add custom preprocessing logic
    2. Standardize the output format
    3. Make it easier to swap OCR engines if needed
    4. Add performance monitoring and error handling
    """
    
    def __init__(self):
        """
        Initialize the OCR reader.
        
        Why lazy loading: EasyOCR model loading is expensive. We do it once
        during initialization and reuse the reader for all documents.
        """
        logger.info("Initializing EasyOCR reader")
        try:
            self.reader = easyocr.Reader(
                lang_list=PipelineConfig.OCR_LANGUAGES,
                gpu=PipelineConfig.OCR_GPU,
                verbose=False  # Suppress EasyOCR's internal logging
            )
            logger.info("EasyOCR reader initialized successfully")
        except Exception as e:
            log_with_context(
                logger, 'error', 'Failed to initialize EasyOCR',
                error=str(e), error_type=type(e).__name__
            )
            raise
            
    def _preprocess_image(self, image: np.ndarray) -> np.ndarray:
        """
        Preprocess image to improve OCR accuracy.
        
        Args:
            image: Input image as numpy array
            
        Returns:
            Preprocessed image
            
        Why preprocessing: Enhancing contrast and removing noise significantly
        improves OCR accuracy, especially for scanned documents with varying quality.
        """
        # Convert to grayscale if needed
        if len(image.shape) == 3:
            gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
        else:
            gray = image
            
        # Apply adaptive thresholding to handle varying lighting
        binary = cv2.adaptiveThreshold(
            gray, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, 
            cv2.THRESH_BINARY, 11, 2
        )
        
        # Denoise
        denoised = cv2.fastNlMeansDenoising(binary, h=10)
        
        return denoised
        
    def extract_text_from_image(
        self, 
        image: np.ndarray,
        preprocess: bool = True
    ) -> List[Tuple[List[List[int]], str, float]]:
        """
        Extract text from a single image.
        
        Args:
            image: Image as numpy array
            preprocess: Whether to apply preprocessing
            
        Returns:
            List of tuples: (bounding_box, text, confidence)
            bounding_box is [[x1,y1], [x2,y2], [x3,y3], [x4,y4]]
            
        Why return format: EasyOCR's native format includes both text location
        and content, which we need for redaction. The confidence score helps
        filter out false positives.
        """
        try:
            if preprocess:
                image = self._preprocess_image(image)
                
            results = self.reader.readtext(image)
            
            log_with_context(
                logger, 'debug', 'OCR extraction completed',
                text_regions_found=len(results)
            )
            
            return results
            
        except Exception as e:
            log_with_context(
                logger, 'error', 'OCR extraction failed',
                error=str(e), error_type=type(e).__name__
            )
            return []
            
    def extract_text_from_pdf(self, pdf_path: Path) -> List[Dict[str, Any]]:
        """
        Extract text from all pages of a PDF.
        
        Args:
            pdf_path: Path to PDF file
            
        Returns:
            List of dictionaries, one per page, containing OCR results
            
        Why convert to images: PDF text extraction alone misses scanned PDFs.
        Converting to images ensures we can OCR any PDF type.
        """
        logger.info(f"Processing PDF: {pdf_path.name}")
        
        all_results = []
        
        try:
            # Convert PDF pages to images
            images = convert_from_path(
                pdf_path, 
                dpi=300,  # High DPI for better OCR accuracy
                fmt='png'
            )
            
            log_with_context(
                logger, 'info', 'PDF converted to images',
                filename=pdf_path.name,
                page_count=len(images)
            )
            
            for page_num, image in enumerate(images):
                # Convert PIL Image to numpy array
                img_array = np.array(image)
                
                # Extract text
                ocr_results = self.extract_text_from_image(img_array)
                
                all_results.append({
                    'page': page_num,
                    'image_shape': img_array.shape,
                    'ocr_results': ocr_results
                })
                
                log_with_context(
                    logger, 'debug', 'Page processed',
                    page=page_num,
                    text_regions=len(ocr_results)
                )
                
        except Exception as e:
            log_with_context(
                logger, 'error', 'PDF processing failed',
                filename=pdf_path.name,
                error=str(e),
                error_type=type(e).__name__
            )
            # Return empty results rather than crashing
            return []
            
        return all_results
        
    def extract_text_from_image_file(self, image_path: Path) -> List[Dict[str, Any]]:
        """
        Extract text from a standalone image file.
        
        Args:
            image_path: Path to image file
            
        Returns:
            List with single dictionary containing OCR results
        """
        logger.info(f"Processing image: {image_path.name}")
        
        try:
            # Read image
            image = cv2.imread(str(image_path))
            
            if image is None:
                logger.error(f"Failed to read image: {image_path}")
                return []
                
            # Extract text
            ocr_results = self.extract_text_from_image(image)
            
            return [{
                'page': 0,
                'image_shape': image.shape,
                'ocr_results': ocr_results
            }]
            
        except Exception as e:
            log_with_context(
                logger, 'error', 'Image processing failed',
                filename=image_path.name,
                error=str(e),
                error_type=type(e).__name__
            )
            return []
