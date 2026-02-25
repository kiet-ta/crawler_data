"""
Main Pipeline Orchestrator

This module coordinates all pipeline components to create a complete
end-to-end data processing workflow.

Why orchestrator: Separates high-level workflow logic from low-level
processing details. Makes the pipeline easier to understand, test, and modify.
"""

import asyncio
import time
from pathlib import Path
from typing import List, Dict, Any, Optional

from config import PipelineConfig
from modules.ingestion.crawler import run_crawler
from modules.ingestion.document_generator import generate_all_documents
from modules.processing.ocr_engine import OCREngine
from modules.processing.pii_detector import PIIDetector
from modules.redaction.redactor import DocumentRedactor
from modules.storage.metadata_manager import MetadataManager
from utils.logger import setup_logger, log_with_context


logger = setup_logger(__name__)


class DataPipeline:
    """
    Main pipeline orchestrator for PII redaction workflow.
    
    Why class-based: Encapsulates pipeline state and allows for
    dependency injection, making testing and configuration easier.
    """
    
    def __init__(self, skip_crawler: bool = True):
        """
        Initialize the pipeline.
        
        Args:
            skip_crawler: If True, skip web crawling and only generate synthetic docs
                         Why: Crawling is slow and may fail. For development/testing,
                         synthetic docs are sufficient and more reliable.
        """
        self.skip_crawler = skip_crawler
        self.ocr_engine: Optional[OCREngine] = None
        self.pii_detector: Optional[PIIDetector] = None
        self.redactor: Optional[DocumentRedactor] = None
        self.metadata_manager: Optional[MetadataManager] = None
        
    def _initialize_components(self) -> None:
        """
        Initialize all pipeline components.
        
        Why lazy initialization: Some components (like OCR) are expensive to
        initialize. We only create them when actually running the pipeline.
        """
        logger.info("Initializing pipeline components")
        
        # Ensure output directories exist
        PipelineConfig.ensure_directories()
        
        # Initialize components
        self.ocr_engine = OCREngine()
        self.pii_detector = PIIDetector()
        self.redactor = DocumentRedactor()
        self.metadata_manager = MetadataManager()
        
        # Initialize metadata
        self.metadata_manager.initialize_dataset_info(
            pipeline_version="1.0.0",
            configuration={
                "target_pdf_count": PipelineConfig.TARGET_PDF_COUNT,
                "target_image_count": PipelineConfig.TARGET_IMAGE_COUNT,
                "ocr_languages": PipelineConfig.OCR_LANGUAGES,
                "pii_patterns": list(PipelineConfig.PII_PATTERNS.keys())
            }
        )
        
        logger.info("Pipeline components initialized successfully")
        
    async def _run_ingestion(self) -> List[Dict[str, Any]]:
        """
        Run the ingestion phase (crawling + document generation).
        
        Returns:
            List of metadata for generated documents
            
        Why async: Allows web crawling (if enabled) to run asynchronously
        while document generation can proceed in parallel.
        """
        logger.info("=" * 60)
        logger.info("PHASE 1: DOCUMENT INGESTION")
        logger.info("=" * 60)
        
        documents_metadata = []
        
        # Optional: Run web crawler
        if not self.skip_crawler:
            try:
                logger.info("Starting web crawler")
                templates = await run_crawler()
                log_with_context(
                    logger, 'info', 'Crawler completed',
                    templates_found=len(templates)
                )
                # Note: In a full implementation, you'd download these templates
                # For this demo, we're just generating synthetic docs
            except Exception as e:
                log_with_context(
                    logger, 'error', 'Crawler failed',
                    error=str(e)
                )
                # Continue even if crawler fails
        else:
            logger.info("Skipping web crawler (skip_crawler=True)")
            
        # Generate synthetic documents
        logger.info("Generating synthetic documents")
        try:
            documents_metadata = generate_all_documents()
            log_with_context(
                logger, 'info', 'Document generation completed',
                total_documents=len(documents_metadata)
            )
        except Exception as e:
            log_with_context(
                logger, 'error', 'Document generation failed',
                error=str(e)
            )
            raise
            
        return documents_metadata
        
    def _run_processing(self) -> List[Dict[str, Any]]:
        """
        Run the processing phase (OCR + PII detection + redaction).
        
        Returns:
            List of processing results for all documents
            
        Why: Orchestrates the core processing logic - extracting text,
        finding PII, and redacting it. Each step builds on the previous.
        """
        logger.info("=" * 60)
        logger.info("PHASE 2: OCR & PII DETECTION")
        logger.info("=" * 60)
        
        processing_results = []
        dataset_dir = PipelineConfig.DATASET_DIR
        
        # Get all files in dataset directory
        pdf_files = list(dataset_dir.glob("*.pdf"))
        image_files = list(dataset_dir.glob("*.png")) + list(dataset_dir.glob("*.jpg"))
        
        all_files = pdf_files + image_files
        
        log_with_context(
            logger, 'info', 'Starting document processing',
            total_files=len(all_files),
            pdfs=len(pdf_files),
            images=len(image_files)
        )
        
        for idx, file_path in enumerate(all_files, 1):
            try:
                logger.info(f"Processing file {idx}/{len(all_files)}: {file_path.name}")
                
                # Step 1: OCR
                if file_path.suffix.lower() == '.pdf':
                    ocr_results = self.ocr_engine.extract_text_from_pdf(file_path)
                else:
                    ocr_results = self.ocr_engine.extract_text_from_image_file(file_path)
                    
                if not ocr_results:
                    logger.warning(f"No OCR results for {file_path.name}, skipping")
                    continue
                    
                # Step 2: PII Detection
                pii_matches = self.pii_detector.detect_in_ocr_results(ocr_results)
                
                pii_stats = self.pii_detector.get_pii_statistics(pii_matches)
                log_with_context(
                    logger, 'info', 'PII detection completed',
                    filename=file_path.name,
                    pii_found=len(pii_matches),
                    pii_stats=pii_stats
                )
                
                # Step 3: Redaction
                redaction_result = self._redact_document(file_path, pii_matches)
                
                # Collect results
                processing_results.append({
                    'filename': file_path.name,
                    'ocr_pages': len(ocr_results),
                    'pii_matches': pii_matches,
                    'redaction_result': redaction_result,
                    'success': True
                })
                
                # Update metadata
                self.metadata_manager.add_pii_matches_to_document(
                    file_path.name,
                    pii_matches
                )
                
            except Exception as e:
                log_with_context(
                    logger, 'error', 'Failed to process file',
                    filename=file_path.name,
                    error=str(e),
                    error_type=type(e).__name__
                )
                
                processing_results.append({
                    'filename': file_path.name,
                    'success': False,
                    'error': str(e)
                })
                
                # Continue processing other files
                continue
                
        return processing_results
        
    def _redact_document(
        self, 
        file_path: Path, 
        pii_matches: List
    ) -> Dict[str, Any]:
        """
        Redact PII from a single document.
        
        Args:
            file_path: Path to document
            pii_matches: List of detected PII matches
            
        Returns:
            Redaction result dictionary
        """
        logger.info(f"Redacting: {file_path.name}")
        
        try:
            # Create redacted output directory
            redacted_dir = PipelineConfig.DATASET_DIR / "redacted"
            redacted_dir.mkdir(exist_ok=True)
            
            output_path = redacted_dir / file_path.name
            
            # Redact based on file type
            if file_path.suffix.lower() == '.pdf':
                result = self.redactor.redact_pdf(file_path, pii_matches, output_path)
            else:
                result = self.redactor.redact_image_file(file_path, pii_matches, output_path)
                
            return result
            
        except Exception as e:
            log_with_context(
                logger, 'error', 'Redaction failed',
                filename=file_path.name,
                error=str(e)
            )
            raise
            
    def _finalize_metadata(
        self, 
        documents_metadata: List[Dict[str, Any]],
        processing_results: List[Dict[str, Any]],
        total_time: float
    ) -> None:
        """
        Finalize and save all metadata.
        
        Args:
            documents_metadata: Metadata from document generation
            processing_results: Results from processing phase
            total_time: Total pipeline execution time in seconds
        """
        logger.info("=" * 60)
        logger.info("PHASE 3: METADATA FINALIZATION")
        logger.info("=" * 60)
        
        # Add all document metadata
        for doc_meta in documents_metadata:
            self.metadata_manager.add_document(doc_meta)
            
        # Calculate processing statistics
        successful = sum(1 for r in processing_results if r.get('success', False))
        failed = len(processing_results) - successful
        total_pii = sum(
            len(r.get('pii_matches', [])) 
            for r in processing_results 
            if r.get('success', False)
        )
        
        processing_stats = {
            "total_processing_time_seconds": round(total_time, 2),
            "documents_processed": len(processing_results),
            "documents_successful": successful,
            "documents_failed": failed,
            "total_pii_detected": total_pii,
        }
        
        self.metadata_manager.update_processing_stats(processing_stats)
        
        # Save metadata
        self.metadata_manager.save()
        
        # Print summary
        logger.info("\n" + self.metadata_manager.get_summary())
        
        log_with_context(
            logger, 'info', 'Pipeline completed successfully',
            total_time=round(total_time, 2),
            documents_processed=successful,
            documents_failed=failed
        )
        
    async def run(self) -> None:
        """
        Execute the complete pipeline.
        
        Why async: Allows ingestion phase (particularly crawling) to use
        async I/O for better performance.
        
        Raises:
            Exception: Any unhandled errors (after logging)
        """
        start_time = time.time()
        
        logger.info("#" * 60)
        logger.info("# PII REDACTION DATA PIPELINE")
        logger.info("#" * 60)
        
        try:
            # Initialize
            self._initialize_components()
            
            # Phase 1: Ingestion
            documents_metadata = await self._run_ingestion()
            
            # Phase 2: Processing
            processing_results = self._run_processing()
            
            # Phase 3: Finalize
            total_time = time.time() - start_time
            self._finalize_metadata(documents_metadata, processing_results, total_time)
            
            logger.info("#" * 60)
            logger.info("# PIPELINE EXECUTION COMPLETED")
            logger.info(f"# Total Time: {total_time:.2f} seconds")
            logger.info("#" * 60)
            
        except KeyboardInterrupt:
            logger.warning("Pipeline interrupted by user")
            raise
        except Exception as e:
            log_with_context(
                logger, 'error', 'Pipeline failed',
                error=str(e),
                error_type=type(e).__name__
            )
            raise


async def main():
    """
    Main entry point for the pipeline.
    
    Why: Provides a clean entry point and handles async context properly.
    """
    pipeline = DataPipeline(skip_crawler=True)
    await pipeline.run()


if __name__ == "__main__":
    # Run the pipeline
    asyncio.run(main())
