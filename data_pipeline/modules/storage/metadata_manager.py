"""
Metadata Manager Module

This module handles creation, updating, and persistence of pipeline metadata.
All operations are tracked and saved to metadata.json for traceability.

Why metadata: Comprehensive metadata enables:
1. Reproducibility - know exactly what was processed and when
2. Debugging - trace issues back to specific processing steps
3. ML Training - understand dataset composition and quality
4. Compliance - audit trail for data processing
"""

import json
from typing import List, Dict, Any, Optional
from pathlib import Path
from datetime import datetime

from config import PipelineConfig
from modules.processing.pii_detector import PIIMatch
from utils.logger import setup_logger, log_with_context


logger = setup_logger(__name__)


class MetadataManager:
    """
    Manages metadata collection and persistence for the entire pipeline.
    
    Why centralized: Having a single source of truth for metadata ensures
    consistency and makes it easy to add new metadata fields without
    modifying multiple parts of the codebase.
    """
    
    def __init__(self, output_path: Optional[Path] = None):
        """
        Initialize metadata manager.
        
        Args:
            output_path: Path where metadata.json will be saved
                        Defaults to dataset directory
        """
        self.output_path = output_path or (PipelineConfig.DATASET_DIR / "metadata.json")
        self.metadata: Dict[str, Any] = {
            "dataset_info": {},
            "documents": [],
            "processing_stats": {},
            "pipeline_version": "1.0.0"
        }
        
    def initialize_dataset_info(self, **kwargs) -> None:
        """
        Initialize dataset-level metadata.
        
        Args:
            **kwargs: Arbitrary dataset-level metadata fields
            
        Why: Dataset-level info provides context about the entire collection,
        useful for understanding dataset provenance and characteristics.
        """
        self.metadata["dataset_info"] = {
            "generated_at": datetime.utcnow().isoformat() + "Z",
            "total_files": 0,  # Will be updated as documents are added
            **kwargs
        }
        
        logger.info("Dataset metadata initialized")
        
    def add_document(self, document_metadata: Dict[str, Any]) -> None:
        """
        Add metadata for a single document.
        
        Args:
            document_metadata: Dictionary containing document-specific metadata
            
        Why: Tracks each document individually, allowing for fine-grained
        analysis and debugging of specific files.
        
        Expected fields:
            - filename: str
            - doc_type: str
            - redacted_boxes: List[Dict]
            - processing_timestamp: str (ISO format)
            - any other document-specific metadata
        """
        # Ensure required fields
        if "filename" not in document_metadata:
            logger.warning("Document metadata missing 'filename' field")
            return
            
        # Add processing timestamp if not present
        if "processing_timestamp" not in document_metadata:
            document_metadata["processing_timestamp"] = datetime.utcnow().isoformat() + "Z"
            
        self.metadata["documents"].append(document_metadata)
        
        # Update total count
        self.metadata["dataset_info"]["total_files"] = len(self.metadata["documents"])
        
        log_with_context(
            logger, 'debug', 'Document metadata added',
            filename=document_metadata.get("filename"),
            doc_type=document_metadata.get("doc_type")
        )
        
    def add_pii_matches_to_document(
        self,
        filename: str,
        pii_matches: List[PIIMatch]
    ) -> None:
        """
        Add PII detection results to a document's metadata.
        
        Args:
            filename: Name of the document
            pii_matches: List of detected PII matches
            
        Why: Links PII detection results to specific documents,
        enabling validation and analysis of redaction quality.
        """
        # Find the document
        doc_metadata = None
        for doc in self.metadata["documents"]:
            if doc.get("filename") == filename:
                doc_metadata = doc
                break
                
        if not doc_metadata:
            logger.warning(f"Document not found in metadata: {filename}")
            return
            
        # Convert PIIMatch objects to dictionaries
        redacted_boxes = [match.to_dict() for match in pii_matches]
        
        doc_metadata["redacted_boxes"] = redacted_boxes
        doc_metadata["pii_count"] = len(redacted_boxes)
        
        # Calculate PII statistics for this document
        pii_stats = {}
        for match in pii_matches:
            pii_type = match.pii_type
            pii_stats[pii_type] = pii_stats.get(pii_type, 0) + 1
            
        doc_metadata["pii_statistics"] = pii_stats
        
        log_with_context(
            logger, 'debug', 'PII metadata added to document',
            filename=filename,
            pii_count=len(pii_matches)
        )
        
    def update_processing_stats(self, stats: Dict[str, Any]) -> None:
        """
        Update pipeline-level processing statistics.
        
        Args:
            stats: Dictionary of processing statistics
            
        Why: High-level stats provide quick insights into pipeline execution,
        useful for monitoring and optimization.
        
        Example stats:
            - total_processing_time: float (seconds)
            - documents_processed: int
            - documents_failed: int
            - total_pii_detected: int
            - ocr_errors: int
        """
        self.metadata["processing_stats"].update(stats)
        
        logger.debug("Processing stats updated")
        
    def calculate_aggregate_stats(self) -> Dict[str, Any]:
        """
        Calculate aggregate statistics from all documents.
        
        Returns:
            Dictionary of aggregate statistics
            
        Why: Provides overview metrics without requiring external analysis.
        Useful for quick validation that the pipeline ran successfully.
        """
        stats = {
            "total_documents": len(self.metadata["documents"]),
            "total_pii_detected": 0,
            "pii_by_type": {},
            "documents_by_type": {},
            "avg_pii_per_document": 0.0
        }
        
        for doc in self.metadata["documents"]:
            # Count PII
            pii_count = doc.get("pii_count", 0)
            stats["total_pii_detected"] += pii_count
            
            # Aggregate by PII type
            pii_stats = doc.get("pii_statistics", {})
            for pii_type, count in pii_stats.items():
                stats["pii_by_type"][pii_type] = stats["pii_by_type"].get(pii_type, 0) + count
                
            # Count documents by type
            doc_type = doc.get("doc_type", "unknown")
            stats["documents_by_type"][doc_type] = stats["documents_by_type"].get(doc_type, 0) + 1
            
        # Calculate average
        if stats["total_documents"] > 0:
            stats["avg_pii_per_document"] = round(
                stats["total_pii_detected"] / stats["total_documents"], 2
            )
            
        return stats
        
    def save(self) -> None:
        """
        Save metadata to JSON file.
        
        Why: Persists all collected metadata to disk, ensuring it's available
        for later analysis, debugging, or ML training pipeline consumption.
        
        Raises:
            Exception: If file writing fails (logged and re-raised)
        """
        try:
            # Calculate and add aggregate stats before saving
            aggregate_stats = self.calculate_aggregate_stats()
            self.metadata["aggregate_statistics"] = aggregate_stats
            
            # Add final save timestamp
            self.metadata["dataset_info"]["saved_at"] = datetime.utcnow().isoformat() + "Z"
            
            # Ensure output directory exists
            self.output_path.parent.mkdir(parents=True, exist_ok=True)
            
            # Write JSON with pretty formatting
            with open(self.output_path, 'w', encoding='utf-8') as f:
                json.dump(self.metadata, f, ensure_ascii=False, indent=2)
                
            log_with_context(
                logger, 'info', 'Metadata saved',
                path=str(self.output_path),
                total_documents=len(self.metadata["documents"])
            )
            
        except Exception as e:
            log_with_context(
                logger, 'error', 'Failed to save metadata',
                path=str(self.output_path),
                error=str(e),
                error_type=type(e).__name__
            )
            raise
            
    def load(self) -> bool:
        """
        Load existing metadata from file.
        
        Returns:
            True if loaded successfully, False if file doesn't exist
            
        Why: Allows resuming or appending to existing datasets without
        losing previous metadata.
        
        Raises:
            Exception: If file exists but can't be parsed (logged and re-raised)
        """
        if not self.output_path.exists():
            logger.info("No existing metadata file found")
            return False
            
        try:
            with open(self.output_path, 'r', encoding='utf-8') as f:
                self.metadata = json.load(f)
                
            log_with_context(
                logger, 'info', 'Metadata loaded',
                path=str(self.output_path),
                documents=len(self.metadata.get("documents", []))
            )
            return True
            
        except Exception as e:
            log_with_context(
                logger, 'error', 'Failed to load metadata',
                path=str(self.output_path),
                error=str(e),
                error_type=type(e).__name__
            )
            raise
            
    def get_summary(self) -> str:
        """
        Get a human-readable summary of the metadata.
        
        Returns:
            Formatted summary string
            
        Why: Provides quick overview for logging and user feedback
        without requiring external tools to parse JSON.
        """
        agg_stats = self.calculate_aggregate_stats()
        
        summary = f"""
Dataset Summary:
----------------
Total Documents: {agg_stats['total_documents']}
Total PII Detected: {agg_stats['total_pii_detected']}
Average PII per Document: {agg_stats['avg_pii_per_document']}

PII by Type:
{json.dumps(agg_stats['pii_by_type'], indent=2)}

Documents by Type:
{json.dumps(agg_stats['documents_by_type'], indent=2)}
        """
        
        return summary.strip()
