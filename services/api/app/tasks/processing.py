"""
Processing Tasks
================
BLOCK 5B: Processing Orchestration Layer
BLOCK 6A: TTS Integration
BLOCK 6B: Chapter Detection & Text Segmentation
BLOCK 6C: Audio Assembly & Output Layer

Celery tasks for document processing orchestration with TTS, chapter detection,
and audio assembly.
"""

import asyncio
import logging
import os
import tempfile
import time
from datetime import datetime
from pathlib import Path
from uuid import UUID

from celery import Task
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine, async_sessionmaker

from app.celery_app import celery_app
from app.core.config import settings
from app.db.models.processing_job import ProcessingJob, JobStatus
from app.db.models.document import Document, ProcessingStatus
from app.services.tts.tts_service import TTSService
from app.services.storage_service import get_storage_service
from app.services.document_structure.engine import DocumentStructureEngine
from app.services.audio.assembler import AudioAssembler
from app.services.audio.normalizer import AudioNormalizer
from app.services.audio.metadata import AudioMetadataWriter, AudioMetadata
from app.financial.financial_metrics import (
    chapters_detected_total,
    chapter_detection_confidence,
    text_chunks_generated_total,
    document_structure_analysis_duration,
    audio_assembly_duration_seconds,
    audio_file_size_bytes,
    full_audiobook_generated_total,
    audio_normalization_duration_seconds,
    audio_metadata_write_duration_seconds,
)

logger = logging.getLogger(__name__)


# ============================================
# ASYNC DATABASE HELPER
# ============================================

# Create async engine for Celery tasks
async_engine = create_async_engine(
    str(settings.database_async_url),
    pool_size=5,
    max_overflow=10,
    pool_pre_ping=True,
    echo=False,
)

AsyncSessionLocal = async_sessionmaker(
    async_engine,
    class_=AsyncSession,
    expire_on_commit=False,
)


async def get_async_session() -> AsyncSession:
    """Get async database session for Celery tasks."""
    async with AsyncSessionLocal() as session:
        yield session


# ============================================
# CUSTOM TASK CLASS
# ============================================

class ProcessingTask(Task):
    """
    Custom Celery task class with retry logic.
    """
    
    autoretry_for = (Exception,)
    retry_kwargs = {"max_retries": 3}
    retry_backoff = True
    retry_backoff_max = 600  # 10 minutes
    retry_jitter = True


# ============================================
# MAIN PROCESSING TASK
# ============================================

@celery_app.task(
    name="process_document_job",
    base=ProcessingTask,
    bind=True,
    acks_late=True,
    reject_on_worker_lost=True,
)
def process_document_job(self, job_id: str):
    """
    Process a document job through the pipeline.
    
    THIS IS A PLACEHOLDER ORCHESTRATION TASK.
    No actual TTS processing happens here - this is just infrastructure.
    
    The real processing logic will be implemented in Block 6.
    For now, this simulates a processing pipeline to validate the orchestration.
    
    Args:
        self: Celery task instance
        job_id: Processing job UUID (as string)
        
    Flow:
        1. Fetch job from database
        2. Update status to PROCESSING
        3. Simulate processing with progress updates
        4. Update status to COMPLETED
        5. Handle errors with retry logic
    """
    
    # Convert string to UUID
    job_uuid = UUID(job_id)
    
    logger.info(
        f"Starting processing job",
        extra={
            "job_id": str(job_uuid),
            "task_id": self.request.id,
            "retry_count": self.request.retries
        }
    )
    
    try:
        # Run async operations
        asyncio.run(_process_job_async(job_uuid, self.request.id, self.request.retries))
        
    except Exception as e:
        logger.error(
            f"Processing job failed: {str(e)}",
            extra={
                "job_id": str(job_uuid),
                "task_id": self.request.id,
                "retry_count": self.request.retries
            },
            exc_info=True
        )
        
        # Update job status to failed
        asyncio.run(_mark_job_failed(job_uuid, str(e), self.request.retries))
        
        # Re-raise to trigger Celery retry
        raise


async def _process_job_async(job_id: UUID, task_id: str, retry_count: int):
    """
    Main async processing logic.
    
    BLOCK 6A: Real TTS integration (simplified for single-document processing).
    
    Process flow:
    1. Fetch job and document
    2. Extract text from document (placeholder for now)
    3. Call TTS service to synthesize audio
    4. Store MP3 in Spaces
    5. Update job status
    
    Future enhancements (not in Block 6A):
    - Chapter detection
    - Chunked processing
    - Audio concatenation
    - Caching
    """
    
    async with AsyncSessionLocal() as session:
        try:
            # Fetch job
            result = await session.execute(
                select(ProcessingJob).where(ProcessingJob.id == job_id)
            )
            job = result.scalar_one_or_none()
            
            if not job:
                raise ValueError(f"Job {job_id} not found")
            
            # Fetch associated document
            doc_result = await session.execute(
                select(Document).where(Document.id == job.document_id)
            )
            document = doc_result.scalar_one_or_none()
            
            if not document:
                raise ValueError(f"Document {job.document_id} not found")
            
            logger.info(
                f"Processing job {job_id} for document {document.filename}",
                extra={
                    "job_id": str(job_id),
                    "document_id": str(document.id),
                    "document_filename": document.filename,
                    "page_count": document.page_count
                }
            )
            
            # Update job status to PROCESSING
            job.status = JobStatus.PROCESSING
            job.started_at = datetime.utcnow()
            job.celery_task_id = task_id
            job.retry_count = retry_count
            job.progress_percentage = 0
            
            # Update document status
            document.processing_status = ProcessingStatus.PROCESSING
            document.processing_started_at = datetime.utcnow()
            
            await session.commit()
            
            # ============================================
            # STEP 1: Analyze Document Structure (BLOCK 6B)
            # ============================================
            logger.info(f"Step 1: Analyzing document structure")
            job.progress_percentage = 5
            await session.commit()
            
            # Get PDF path from storage (assuming local path or download)
            # For now, use storage_path as-is (adjust based on your storage setup)
            pdf_path = f"/tmp/{document.id}.pdf"  # Temporary path
            
            # TODO: Download PDF from Spaces if not local
            # For now, assume PDF is accessible at storage_path
            
            structure_start = time.time()
            
            try:
                # Initialize structure engine
                structure_engine = DocumentStructureEngine()
                
                # Analyze document and detect chapters
                structure = await structure_engine.analyze_document(
                    document_id=document.id,
                    pdf_path=document.storage_path,  # May need adjustment
                    db=session
                )
                
                structure_duration = time.time() - structure_start
                
                # Emit metrics
                for chapter in structure.chapters:
                    chapters_detected_total.labels(
                        detection_method=chapter.detection_method
                    ).inc()
                    
                    chapter_detection_confidence.labels(
                        detection_method=chapter.detection_method
                    ).observe(chapter.confidence)
                
                document_structure_analysis_duration.observe(structure_duration)
                
                logger.info(
                    f"Document structure analyzed: {structure.chapter_count} chapters detected "
                    f"(avg confidence: {structure.average_confidence:.2f}, duration: {structure_duration:.2f}s)"
                )
                
            except Exception as e:
                logger.error(f"Document structure analysis failed: {str(e)}", exc_info=True)
                # Fall back to single chapter
                structure = None
            
            job.progress_percentage = 20
            await session.commit()
            
            # ============================================
            # STEP 2: Generate TTS for each chapter (BLOCK 6B)
            # ============================================
            logger.info(f"Step 2: Generating TTS audio for chapters")
            job.progress_percentage = 30
            await session.commit()
            
            tts_service = TTSService()
            storage_service = get_storage_service()
            
            # Track chapter audio paths for assembly
            chapter_audio_paths = []
            
            if structure and structure.chapters:
                # Process each chapter
                total_chapters = len(structure.chapters)
                
                for i, chapter in enumerate(structure.chapters):
                    logger.info(
                        f"Processing chapter {i+1}/{total_chapters}: '{chapter.title}'"
                    )
                    
                    # Use chapter text if available, otherwise placeholder
                    chapter_text = chapter.text_content if chapter.text_content else (
                        f"Chapter {i+1}: {chapter.title}. "
                        f"This chapter spans pages {chapter.start_page} to {chapter.end_page}."
                    )
                    
                    try:
                        # Synthesize audio for chapter
                        audio_bytes = await tts_service.synthesize_text(
                            db=session,
                            user_id=document.user_id,
                            text=chapter_text,
                            voice_id=settings.google_tts_default_voice,
                            language_code=settings.google_tts_default_language,
                        )
                        
                        # Store chapter audio
                        audio_path = await storage_service.upload_audio(
                            audio_data=audio_bytes,
                            user_id=document.user_id,
                            document_id=document.id,
                            filename=f"chapter_{i+1}.mp3",
                            metadata={
                                "chapter_title": chapter.title,
                                "chapter_order": str(i),
                                "character_count": str(len(chapter_text)),
                            }
                        )
                        
                        # Track path for later assembly
                        chapter_audio_paths.append(audio_path)
                        
                        logger.info(
                            f"Chapter {i+1} audio generated and stored: {audio_path}"
                        )
                        
                    except Exception as e:
                        logger.error(f"Failed to process chapter {i+1}: {str(e)}")
                        # Continue with next chapter
                        continue
                    
                    # Update progress
                    progress = 30 + int((i + 1) / total_chapters * 60)
                    job.progress_percentage = min(progress, 90)
                    await session.commit()
                
            else:
                # Fallback: Process as single document (BLOCK 6A behavior)
                logger.warning("No chapter structure, processing as single document")
                
                sample_text = f"This is a test audio file for document {document.original_filename}. "
                sample_text += "This demonstrates the Text-to-Speech integration in Sonoro. "
                sample_text += f"The document has {document.page_count or 0} pages."
                
                try:
                    audio_bytes = await tts_service.synthesize_text(
                        db=session,
                        user_id=document.user_id,
                        text=sample_text,
                        voice_id=settings.google_tts_default_voice,
                        language_code=settings.google_tts_default_language,
                    )
                    
                    audio_path = await storage_service.upload_audio(
                        audio_data=audio_bytes,
                        user_id=document.user_id,
                        document_id=document.id,
                        filename="full.mp3",
                        metadata={
                            "character_count": str(len(sample_text)),
                            "voice_id": settings.google_tts_default_voice,
                            "language_code": settings.google_tts_default_language,
                        }
                    )
                    
                    logger.info(
                        f"Audio uploaded to storage",
                        extra={"audio_path": audio_path}
                    )
                    
                except Exception as e:
                    logger.error(f"Audio processing failed: {str(e)}", exc_info=True)
                    raise
            
            job.progress_percentage = 90
            await session.commit()
            
            # ============================================
            # STEP 3: Audio Assembly (BLOCK 6C)
            # ============================================
            if chapter_audio_paths:
                logger.info(
                    f"Step 3: Assembling {len(chapter_audio_paths)} chapter audio files"
                )
                
                # Update status to ASSEMBLING
                document.processing_status = ProcessingStatus.ASSEMBLING
                job.progress_percentage = 91
                await session.commit()
                
                try:
                    # Create temporary directory for assembly
                    with tempfile.TemporaryDirectory() as temp_dir:
                        temp_dir_path = Path(temp_dir)
                        
                        # Download chapter files from storage
                        local_chapter_paths = []
                        for i, remote_path in enumerate(chapter_audio_paths):
                            local_path = temp_dir_path / f"chapter_{i+1}.mp3"
                            
                            # Download from storage
                            # Note: This assumes storage service provides download method
                            # In production, implement storage_service.download_audio()
                            logger.debug(f"Downloading chapter {i+1} from {remote_path}")
                            # TODO: Implement actual download
                            # For now, assume files are accessible locally
                            local_chapter_paths.append(str(local_path))
                        
                        # Assemble chapters
                        assembly_start = time.time()
                        
                        assembler = AudioAssembler(target_bitrate=128)
                        output_path = temp_dir_path / "audiobook_assembled.mp3"
                        
                        assembled_path, assembly_metrics = await assembler.assemble_chapters(
                            chapter_paths=local_chapter_paths,
                            output_path=str(output_path),
                        )
                        
                        assembly_duration = time.time() - assembly_start
                        audio_assembly_duration_seconds.observe(assembly_duration)
                        
                        logger.info(
                            f"Audio assembly complete",
                            extra={
                                "duration_seconds": assembly_metrics.duration_seconds,
                                "file_size_mb": assembly_metrics.file_size_bytes / (1024 * 1024),
                                "chapter_count": assembly_metrics.chapter_count,
                            }
                        )
                        
                        job.progress_percentage = 93
                        await session.commit()
                        
                        # ============================================
                        # STEP 4: Audio Normalization (BLOCK 6C)
                        # ============================================
                        logger.info("Step 4: Normalizing audio")
                        
                        document.processing_status = ProcessingStatus.FINALIZING
                        job.progress_percentage = 94
                        await session.commit()
                        
                        normalization_start = time.time()
                        
                        normalizer = AudioNormalizer(target_dbfs=-20.0)
                        normalized_path = temp_dir_path / "audiobook_normalized.mp3"
                        
                        normalized_path_str, norm_metrics = await normalizer.normalize(
                            input_path=assembled_path,
                            output_path=str(normalized_path),
                            trim_silence=True,
                        )
                        
                        normalization_duration = time.time() - normalization_start
                        audio_normalization_duration_seconds.observe(normalization_duration)
                        
                        logger.info(
                            f"Audio normalization complete",
                            extra={
                                "original_dbfs": norm_metrics.original_dbfs,
                                "normalized_dbfs": norm_metrics.normalized_dbfs,
                                "trim_start_ms": norm_metrics.trim_start_ms,
                                "trim_end_ms": norm_metrics.trim_end_ms,
                            }
                        )
                        
                        job.progress_percentage = 96
                        await session.commit()
                        
                        # ============================================
                        # STEP 5: Add Metadata (BLOCK 6C)
                        # ============================================
                        logger.info("Step 5: Adding metadata tags")
                        
                        metadata_start = time.time()
                        
                        metadata_writer = AudioMetadataWriter()
                        metadata = AudioMetadata(
                            title=document.original_filename.replace(".pdf", ""),
                            author="Unknown Author",  # TODO: Extract from document
                            language=document.language_detected or "en",
                            processing_date=datetime.utcnow(),
                            comment=f"Generated by Sonoro - {structure.chapter_count} chapters",
                        )
                        
                        final_path = temp_dir_path / "audiobook_final.mp3"
                        
                        # Copy normalized to final
                        import shutil
                        shutil.copy2(normalized_path_str, str(final_path))
                        
                        # Write metadata
                        await metadata_writer.write_metadata(
                            audio_path=str(final_path),
                            metadata=metadata,
                        )
                        
                        metadata_duration = time.time() - metadata_start
                        audio_metadata_write_duration_seconds.observe(metadata_duration)
                        
                        logger.info("Metadata tags written successfully")
                        
                        job.progress_percentage = 98
                        await session.commit()
                        
                        # ============================================
                        # STEP 6: Upload Final Audiobook
                        # ============================================
                        logger.info("Step 6: Uploading final audiobook")
                        
                        # Upload final audiobook
                        with open(final_path, "rb") as f:
                            final_audio_data = f.read()
                        
                        final_audio_path = await storage_service.upload_audio(
                            audio_data=final_audio_data,
                            user_id=document.user_id,
                            document_id=document.id,
                            filename="audiobook.mp3",
                            metadata={
                                "chapter_count": str(structure.chapter_count),
                                "duration_seconds": str(int(assembly_metrics.duration_seconds)),
                                "file_size_bytes": str(assembly_metrics.file_size_bytes),
                                "bitrate_kbps": str(assembly_metrics.bitrate_kbps),
                            }
                        )
                        
                        # Update document with final audio info
                        document.final_audio_path = final_audio_path
                        document.audio_duration_seconds = int(assembly_metrics.duration_seconds)
                        document.audio_file_size_bytes = assembly_metrics.file_size_bytes
                        
                        # Emit metrics
                        audio_file_size_bytes.observe(assembly_metrics.file_size_bytes)
                        full_audiobook_generated_total.inc()
                        
                        logger.info(
                            f"Final audiobook uploaded",
                            extra={
                                "path": final_audio_path,
                                "duration_seconds": document.audio_duration_seconds,
                                "file_size_mb": document.audio_file_size_bytes / (1024 * 1024),
                            }
                        )
                        
                except Exception as e:
                    logger.error(f"Audio assembly failed: {str(e)}", exc_info=True)
                    raise
            
            # ============================================
            # STEP 7: Mark complete
            # ============================================
            
            job.status = JobStatus.COMPLETED
            job.progress_percentage = 100
            job.completed_at = datetime.utcnow()
            
            document.processing_status = ProcessingStatus.COMPLETED
            document.processing_completed_at = datetime.utcnow()
            
            await session.commit()
            
            logger.info(
                f"Processing job completed successfully",
                extra={
                    "job_id": str(job_id),
                    "task_id": task_id,
                    "final_audio_path": document.final_audio_path,
                    "duration_seconds": (job.completed_at - job.started_at).total_seconds(),
                    "chapter_count": structure.chapter_count if structure else 0,
                }
            )
            
        except Exception as e:
            await session.rollback()
            raise


async def _mark_job_failed(job_id: UUID, error_message: str, retry_count: int):
    """Mark job as failed in database."""
    
    async with AsyncSessionLocal() as session:
        try:
            result = await session.execute(
                select(ProcessingJob).where(ProcessingJob.id == job_id)
            )
            job = result.scalar_one_or_none()
            
            if job:
                job.status = JobStatus.FAILED
                job.error_message = error_message
                job.retry_count = retry_count
                job.completed_at = datetime.utcnow()
                
                # Update document status
                doc_result = await session.execute(
                    select(Document).where(Document.id == job.document_id)
                )
                document = doc_result.scalar_one_or_none()
                
                if document:
                    document.processing_status = ProcessingStatus.FAILED
                
                await session.commit()
                
                logger.info(
                    f"Job marked as failed",
                    extra={
                        "job_id": str(job_id),
                        "error_message": error_message,
                        "retry_count": retry_count
                    }
                )
        except Exception as e:
            logger.error(f"Failed to mark job as failed: {str(e)}")
            await session.rollback()


# ============================================
# UTILITY TASKS
# ============================================

@celery_app.task(name="cleanup_stale_jobs")
def cleanup_stale_jobs():
    """
    Cleanup stale jobs that have been stuck in PROCESSING for too long.
    This is a scheduled task that should run periodically.
    """
    logger.info("Running cleanup_stale_jobs task")
    
    # TODO: Implement in Block 6
    # For now, this is just a placeholder
    
    return {"cleaned": 0}


@celery_app.task(name="update_queue_metrics")
def update_queue_metrics():
    """
    Update Prometheus metrics for queue depth.
    This is a scheduled task that should run frequently.
    """
    logger.info("Updating queue metrics")
    
    # TODO: Implement proper queue depth tracking
    # For now, this is just a placeholder
    
    return {"status": "ok"}
