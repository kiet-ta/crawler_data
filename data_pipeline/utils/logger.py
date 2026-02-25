"""
Structured Logging Module

This module provides a centralized logging configuration for the entire pipeline.
Why: Structured logging (JSON format) enables better log aggregation, monitoring,
and debugging in production environments. It's searchable and machine-parseable.
"""

import logging
import json
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Optional
from config import PipelineConfig


class JSONFormatter(logging.Formatter):
    """
    Custom formatter that outputs logs in JSON format.
    
    Why: JSON logs are easily parsed by log aggregation tools (ELK, Splunk, CloudWatch).
    They preserve data types and make it simple to filter/search by specific fields.
    """
    
    def format(self, record: logging.LogRecord) -> str:
        """
        Format log record as JSON string.
        
        Args:
            record: The log record to format
            
        Returns:
            JSON-formatted log string
        """
        log_data: Dict[str, Any] = {
            "timestamp": datetime.utcnow().isoformat() + "Z",
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "module": record.module,
            "function": record.funcName,
            "line": record.lineno,
        }
        
        # Add exception info if present
        if record.exc_info:
            log_data["exception"] = self.formatException(record.exc_info)
            
        # Add extra fields if provided
        if hasattr(record, "extra_fields"):
            log_data.update(record.extra_fields)
            
        return json.dumps(log_data, ensure_ascii=False)


class TextFormatter(logging.Formatter):
    """
    Human-readable text formatter for development.
    
    Why: While JSON is great for production, human-readable logs are easier
    to scan during local development and debugging.
    """
    
    def __init__(self):
        super().__init__(
            fmt='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
            datefmt='%Y-%m-%d %H:%M:%S'
        )


def setup_logger(
    name: str,
    log_level: Optional[str] = None,
    log_format: Optional[str] = None,
    log_file: Optional[Path] = None
) -> logging.Logger:
    """
    Set up and configure a logger instance.
    
    Args:
        name: Name of the logger (typically __name__ of the calling module)
        log_level: Logging level (DEBUG, INFO, WARNING, ERROR, CRITICAL)
        log_format: Format type ('json' or 'text')
        log_file: Optional file path to write logs to
        
    Returns:
        Configured logger instance
        
    Why: Centralized logger setup ensures consistent configuration across all modules.
    Allows per-module loggers while maintaining uniform formatting and output.
    
    Example:
        >>> logger = setup_logger(__name__)
        >>> logger.info("Processing started", extra={"extra_fields": {"file_count": 10}})
    """
    # Use config defaults if not provided
    log_level = log_level or PipelineConfig.LOG_LEVEL
    log_format = log_format or PipelineConfig.LOG_FORMAT
    log_file = log_file or PipelineConfig.LOG_FILE
    
    # Create logger
    logger = logging.getLogger(name)
    logger.setLevel(getattr(logging, log_level.upper()))
    
    # Prevent duplicate handlers
    if logger.handlers:
        return logger
    
    # Choose formatter
    formatter = JSONFormatter() if log_format == "json" else TextFormatter()
    
    # Console handler (stdout)
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(logging.DEBUG)
    console_handler.setFormatter(formatter)
    logger.addHandler(console_handler)
    
    # File handler (if log file specified)
    if log_file:
        log_file.parent.mkdir(parents=True, exist_ok=True)
        file_handler = logging.FileHandler(log_file, encoding='utf-8')
        file_handler.setLevel(logging.DEBUG)
        file_handler.setFormatter(formatter)
        logger.addHandler(file_handler)
    
    return logger


def log_with_context(logger: logging.Logger, level: str, message: str, **context) -> None:
    """
    Log a message with additional context fields.
    
    Args:
        logger: Logger instance to use
        level: Log level ('debug', 'info', 'warning', 'error', 'critical')
        message: Log message
        **context: Additional context to include in the log
        
    Why: Provides a clean API for adding structured context to log messages
    without polluting the main message string with variables.
    
    Example:
        >>> log_with_context(logger, 'info', 'File processed', 
        ...                  filename='doc.pdf', page_count=5)
    """
    log_func = getattr(logger, level.lower())
    log_func(message, extra={"extra_fields": context})
