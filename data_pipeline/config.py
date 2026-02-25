"""
Configuration Module for Data Pipeline

This module centralizes all configuration settings for the PII redaction pipeline.
Using a centralized config promotes maintainability and makes environment-specific
adjustments easier without modifying core business logic.
"""

import os
from pathlib import Path
from typing import Dict, List


class PipelineConfig:
    """
    Central configuration class for the data pipeline.
    
    Why: Separating configuration from implementation allows for easy testing,
    deployment to different environments, and reduces magic numbers in the codebase.
    """
    
    # Project Paths
    BASE_DIR = Path(__file__).resolve().parent
    DATASET_DIR = BASE_DIR.parent / "dataset" / "raw"
    
    # Document Generation Settings
    TARGET_PDF_COUNT = 30
    TARGET_IMAGE_COUNT = 10
    PDF_PAGE_COUNT_MIN = 3
    PDF_PAGE_COUNT_MAX = 5
    
    # Document Types
    DOCUMENT_TYPES = ["sales_contract", "deposit_contract", "lease_agreement"]
    
    # Crawler Settings
    CRAWLER_USER_AGENT = (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36"
    )
    CRAWLER_HEADLESS = True
    CRAWLER_MIN_DELAY = 2.0  # seconds - mimics human behavior
    CRAWLER_MAX_DELAY = 5.0  # seconds

    # Browser channel: 'msedge' uses the system-installed Microsoft Edge (no download needed).
    # Other valid values: 'chrome', 'chrome-beta', 'msedge-beta', or None (uses bundled Chromium).
    CRAWLER_BROWSER_CHANNEL: str = "msedge"
    
    # Search queries for template discovery
    TEMPLATE_SEARCH_QUERIES = [
        "mẫu hợp đồng mua bán nhà đất",
        "hợp đồng đặt cọc bất động sản",
        "mẫu hợp đồng thuê nhà",
    ]
    
    # OCR Settings
    OCR_LANGUAGES = ['vi', 'en']  # Vietnamese and English
    OCR_GPU = False  # Set to True if CUDA is available
    
    # PII Detection Patterns (Vietnamese specific)
    PII_PATTERNS: Dict[str, str] = {
        # CCCD: 12 consecutive digits
        "cccd": r'\b\d{12}\b',
        
        # Date of Birth: Various Vietnamese formats
        # DD/MM/YYYY, DD-MM-YYYY, Ngày DD tháng MM năm YYYY
        "dob": r'(?:\d{1,2}[/-]\d{1,2}[/-]\d{4})|(?:ngày\s+\d{1,2}\s+tháng\s+\d{1,2}\s+năm\s+\d{4})',
        
        # Names after common prefixes in Vietnamese contracts
        # Captures names following "Ông/Bà:", "Bên A:", "Bên B:", "Họ và tên:"
        "name": r'(?:Ông/Bà|Bên\s+[AB]|Họ\s+và\s+tên)\s*:\s*([A-ZÀÁẠẢÃÂẦẤẬẨẪĂẰẮẶẲẴÈÉẸẺẼÊỀẾỆỂỄÌÍỊỈĨÒÓỌỎÕÔỒỐỘỔỖƠỜỚỢỞỠÙÚỤỦŨƯỪỨỰỬỮỲÝỴỶỸĐ][a-zàáạảãâầấậẩẫăằắặẳẵèéẹẻẽêềếệểễìíịỉĩòóọỏõôồốộổỗơờớợởỡùúụủũưừứựửữỳýỵỷỹđ]+(?:\s+[A-ZÀÁẠẢÃÂẦẤẬẨẪĂẰẮẶẲẴÈÉẸẺẼÊỀẾỆỂỄÌÍỊỈĨÒÓỌỎÕÔỒỐỘỔỖƠỜỚỢỞỠÙÚỤỦŨƯỪỨỰỬỮỲÝỴỶỸĐ][a-zàáạảãâầấậẩẫăằắặẳẵèéẹẻẽêềếệểễìíịỉĩòóọỏõôồốộổỗơờớợởỡùúụủũưừứựửữỳýỵỷỹđ]+){1,3})',
        
        # Phone numbers: Vietnamese format (10-11 digits)
        "phone": r'\b0\d{9,10}\b',
        
        # Address patterns (simplified)
        "address": r'(?:Địa\s+chỉ|Nơi\s+ở)\s*:\s*(.{10,100})',
    }
    
    # Redaction Settings
    REDACTION_COLOR = (0, 0, 0)  # Black boxes
    REDACTION_THICKNESS = -1  # Filled rectangle
    REDACTION_PADDING = 5  # pixels - extra padding around detected text
    
    # Logging Settings
    LOG_LEVEL = "INFO"
    LOG_FORMAT = "json"  # json or text
    LOG_FILE = BASE_DIR / "pipeline.log"
    
    # Performance Settings
    MAX_CONCURRENT_TASKS = 5  # For async operations
    
    @classmethod
    def ensure_directories(cls) -> None:
        """
        Create necessary directories if they don't exist.
        
        Why: Defensive programming - prevents runtime errors when trying to save files
        to non-existent directories. Should be called during pipeline initialization.
        """
        cls.DATASET_DIR.mkdir(parents=True, exist_ok=True)
        
    @classmethod
    def get_output_path(cls, filename: str) -> Path:
        """
        Get the full output path for a processed file.
        
        Args:
            filename: Name of the file to save
            
        Returns:
            Full path where the file should be saved
            
        Why: Centralizes path construction logic and ensures consistency across modules.
        """
        return cls.DATASET_DIR / filename
