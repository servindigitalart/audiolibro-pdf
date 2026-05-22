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
import shutil
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

# Heavy service/audio imports are deferred to inside _process_job_async so that
# missing optional dependencies (ffmpeg, google-cloud-tts, pydub, etc.) do NOT
# prevent the worker from starting and registering tasks.  An ImportError inside
# the task body surfaces as a task failure rather than a silent startup crash.

logger = logging.getLogger(__name__)

# Google TTS hard limit is 5000 chars per request; stay safely below it.
_TTS_CHUNK_SIZE = 4500


def _chunk_text(text: str, max_chars: int = _TTS_CHUNK_SIZE) -> list:
    """Split *text* into chunks ≤ max_chars.

    Splitting priority:
    1. Paragraph boundary (blank line) in the last half of the window
    2. Sentence-ending punctuation (. ! ?) in the last half of the window
    3. Hard split at max_chars (last resort)
    """
    if len(text) <= max_chars:
        return [text]

    chunks = []
    remaining = text.strip()

    while len(remaining) > max_chars:
        window = remaining[:max_chars]

        pos = window.rfind("\n\n")
        if pos < max_chars // 4:
            pos = -1

        if pos == -1:
            for sep in (". ", "! ", "? ", ".\n", "!\n", "?\n"):
                candidate = window.rfind(sep)
                if candidate >= max_chars // 4:
                    pos = candidate + len(sep)
                    break

        if pos <= 0:
            pos = max_chars

        chunks.append(remaining[:pos].strip())
        remaining = remaining[pos:].strip()

    if remaining:
        chunks.append(remaining)

    return [c for c in chunks if c]


async def _ffmpeg_concat(input_paths: list, output_path: str) -> int:
    """Concatenate MP3 files via ffmpeg concat demuxer — no audio data in RAM."""
    concat_list = output_path + ".txt"
    with open(concat_list, "w") as fh:
        for p in input_paths:
            fh.write(f"file '{p}'\n")
    logger.info("[SONORO] ffmpeg_concat_list_ready files=%d", len(input_paths))

    async def _run(cmd):
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        try:
            _, stderr = await asyncio.wait_for(proc.communicate(), timeout=3600)
        except asyncio.TimeoutError:
            proc.kill()
            raise RuntimeError("ffmpeg timed out after 3600 seconds")
        return proc.returncode, stderr.decode(errors="replace")

    cmd_copy = [
        "ffmpeg", "-y", "-f", "concat", "-safe", "0",
        "-i", concat_list, "-c", "copy", output_path,
    ]
    rc, stderr = await _run(cmd_copy)
    if rc != 0:
        logger.warning(
            "[SONORO] ffmpeg_copy_failed rc=%d stderr=%s — retrying with reencode",
            rc, stderr[:200],
        )
        cmd_encode = [
            "ffmpeg", "-y", "-f", "concat", "-safe", "0",
            "-i", concat_list, "-codec:a", "libmp3lame", "-q:a", "4", output_path,
        ]
        rc, stderr = await _run(cmd_encode)
        if rc != 0:
            raise RuntimeError(f"ffmpeg reencode failed rc={rc}: {stderr[:500]}")

    try:
        os.unlink(concat_list)
    except OSError:
        pass
    return os.path.getsize(output_path)


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
        "[SONORO] worker_task_received task=process_document_job job_id=%s task_id=%s retry=%s",
        job_id, self.request.id, self.request.retries,
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

    Imports are deferred here rather than at module level so that missing
    optional packages (google-cloud-tts, pydub, ffmpeg-python, etc.) surface
    as task failures rather than silent worker startup crashes.
    """
    # Deferred heavy imports
    from app.services.tts.tts_service import TTSService
    from app.services.storage_service import get_storage_service
    from app.services.document_structure.engine import DocumentStructureEngine
    from app.services.audio.metadata import AudioMetadataWriter, AudioMetadata
    from app.db.models.chapter import Chapter as ChapterModel
    from mutagen.mp3 import MP3 as MutagenMP3
    from app.financial.financial_metrics import (
        chapters_detected_total,
        chapter_detection_confidence,
        document_structure_analysis_duration,
        audio_file_size_bytes,
        full_audiobook_generated_total,
    )

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
            
            # Initialize storage early — needed to download the PDF before Step 1.
            # Both API and worker share the same S3 bucket; the API writes the PDF
            # and the worker reads it.  With STORAGE_BACKEND=local the two containers
            # have separate filesystems, so the file would not be found.
            storage_service = get_storage_service()

            # ============================================
            # STEP 1: Analyze Document Structure (BLOCK 6B)
            # ============================================
            logger.info("[SONORO] step=1 action=analyze_document_structure")
            job.progress_percentage = 5
            await session.commit()

            # Download PDF from shared object storage to a local temp file.
            # document.storage_path is an S3 key (e.g. "documents/<uid>/<id>.pdf"),
            # not a filesystem path — fitz.open() needs a real local path.
            pdf_path = f"/tmp/sonoro_{document.id}.pdf"
            await storage_service.download_document(document.storage_path, pdf_path)
            logger.info(
                "[SONORO] pdf_downloaded storage_path=%s local_path=%s",
                document.storage_path, pdf_path,
            )

            structure_start = time.time()

            try:
                structure_engine = DocumentStructureEngine()
                structure = await structure_engine.analyze_document(
                    document_id=document.id,
                    pdf_path=pdf_path,
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
            # STEPS 2–6: TTS → chapter MP3s → final audiobook
            # Single temp directory: all audio files stay on disk.
            # No audio PCM data is loaded into Python memory.
            # ============================================
            logger.info("[SONORO] step=2 action=tts_synthesis")
            job.progress_percentage = 30
            await session.commit()

            tts_service = TTSService()
            chapter_count = structure.chapter_count if structure else 1
            chapters_to_process = structure.chapters if (structure and structure.chapters) else []
            total_chapters = len(chapters_to_process)
            chapter_audio_paths = []  # S3 keys (durability / per-chapter playback)

            with tempfile.TemporaryDirectory(prefix=f"sonoro_{job_id}_") as _tmp:
                tmp = Path(_tmp)
                local_chapter_paths = []  # local disk paths reused for final assembly

                # ---- TTS synthesis ----
                if not chapters_to_process:
                    logger.warning(
                        "[SONORO] no_chapters_detected doc_id=%s — using fallback text",
                        document.id,
                    )
                    fallback_text = (
                        f"{document.original_filename.replace('.pdf', '')}. "
                        f"This document has {document.page_count or 0} pages."
                    )
                    chunks = _chunk_text(fallback_text)
                    chunk_paths = []
                    for j, chunk in enumerate(chunks):
                        audio_bytes = await tts_service.synthesize_text(
                            db=session,
                            user_id=document.user_id,
                            text=chunk,
                            voice_id=settings.google_tts_default_voice,
                            language_code=settings.google_tts_default_language,
                        )
                        p = str(tmp / f"ch1_chunk{j + 1}.mp3")
                        with open(p, "wb") as fh:
                            fh.write(audio_bytes)
                        chunk_paths.append(p)

                    chapter_path = str(tmp / "chapter_1.mp3")
                    if len(chunk_paths) == 1:
                        shutil.copy2(chunk_paths[0], chapter_path)
                    else:
                        await _ffmpeg_concat(chunk_paths, chapter_path)
                    for cp in chunk_paths:
                        try:
                            os.unlink(cp)
                        except OSError:
                            pass

                    s3_path = await storage_service.upload_audio_file(
                        file_path=chapter_path,
                        user_id=document.user_id,
                        document_id=document.id,
                        filename="chapter_1.mp3",
                        metadata={"character_count": str(len(fallback_text))},
                    )
                    chapter_audio_paths.append(s3_path)
                    local_chapter_paths.append(chapter_path)
                    logger.info("[SONORO] chapter_audio_ready path=%s", s3_path)
                else:
                    for i, chapter in enumerate(chapters_to_process):
                        chapter_label = f"chapter_{i + 1}"
                        chapter_text = chapter.text_content if chapter.text_content else (
                            f"Chapter {i + 1}: {chapter.title}. "
                            f"This chapter spans pages {chapter.start_page} to {chapter.end_page}."
                        )
                        chunks = _chunk_text(chapter_text)
                        logger.info(
                            "[SONORO] tts_chunking chapter_id=%s chunks=%d total_chars=%d",
                            chapter_label, len(chunks), len(chapter_text),
                        )

                        chunk_paths = []
                        for j, chunk in enumerate(chunks):
                            audio_bytes = await tts_service.synthesize_text(
                                db=session,
                                user_id=document.user_id,
                                text=chunk,
                                voice_id=settings.google_tts_default_voice,
                                language_code=settings.google_tts_default_language,
                            )
                            p = str(tmp / f"ch{i + 1}_chunk{j + 1}.mp3")
                            with open(p, "wb") as fh:
                                fh.write(audio_bytes)
                            chunk_paths.append(p)
                            logger.info(
                                "[SONORO] tts_chunk_done index=%d/%d chapter_id=%s",
                                j + 1, len(chunks), chapter_label,
                            )

                        chapter_path = str(tmp / f"chapter_{i + 1}.mp3")
                        if len(chunk_paths) == 1:
                            shutil.copy2(chunk_paths[0], chapter_path)
                        else:
                            await _ffmpeg_concat(chunk_paths, chapter_path)
                        for cp in chunk_paths:
                            try:
                                os.unlink(cp)
                            except OSError:
                                pass

                        s3_path = await storage_service.upload_audio_file(
                            file_path=chapter_path,
                            user_id=document.user_id,
                            document_id=document.id,
                            filename=f"chapter_{i + 1}.mp3",
                            metadata={
                                "chapter_title": chapter.title,
                                "chapter_order": str(i),
                                "character_count": str(len(chapter_text)),
                                "chunk_count": str(len(chunks)),
                            },
                        )
                        chapter_audio_paths.append(s3_path)
                        local_chapter_paths.append(chapter_path)
                        logger.info(
                            "[SONORO] chapter_audio_ready chapter_id=%s path=%s",
                            chapter_label, s3_path,
                        )

                        # Persist audio S3 key to Chapter row so the frontend can play it
                        ch_result = await session.execute(
                            select(ChapterModel).where(
                                ChapterModel.document_id == document.id,
                                ChapterModel.order_index == i,
                            )
                        )
                        db_ch = ch_result.scalar_one_or_none()
                        if db_ch:
                            db_ch.audio_url = s3_path
                            logger.info(
                                "[SONORO] chapter_audio_path_persisted order=%d chapter_db_id=%s",
                                i, db_ch.id,
                            )

                        progress = 30 + int((i + 1) / total_chapters * 60)
                        job.progress_percentage = min(progress, 90)
                        await session.commit()

                job.progress_percentage = 90
                await session.commit()

                # ---- Final assembly (ffmpeg concat demuxer — zero PCM in RAM) ----
                logger.info(
                    "[SONORO] final_assembly_start chapters=%d", len(local_chapter_paths)
                )
                document.processing_status = ProcessingStatus.ASSEMBLING
                job.progress_percentage = 91
                await session.commit()

                assembled_path = str(tmp / "audiobook_assembled.mp3")
                if len(local_chapter_paths) == 1:
                    shutil.copy2(local_chapter_paths[0], assembled_path)
                else:
                    await _ffmpeg_concat(local_chapter_paths, assembled_path)
                logger.info("[SONORO] final_assembly_ffmpeg_done")

                job.progress_percentage = 94
                await session.commit()

                # ---- Metadata (mutagen reads ID3 only — no PCM load) ----
                document.processing_status = ProcessingStatus.FINALIZING
                metadata_writer = AudioMetadataWriter()
                meta = AudioMetadata(
                    title=document.original_filename.replace(".pdf", ""),
                    author="Unknown Author",
                    language=document.language_detected or "en",
                    processing_date=datetime.utcnow(),
                    comment=f"Generated by Sonoro - {chapter_count} chapters",
                )
                await metadata_writer.write_metadata(audio_path=assembled_path, metadata=meta)

                job.progress_percentage = 96
                await session.commit()

                # ---- Upload from disk (boto3 upload_file streams — no in-memory read) ----
                final_size = os.path.getsize(assembled_path)
                duration_s = int(MutagenMP3(assembled_path).info.length)

                logger.info(
                    "[SONORO] final_audio_upload_start size_bytes=%d duration_s=%d",
                    final_size, duration_s,
                )
                final_audio_path = await storage_service.upload_audio_file(
                    file_path=assembled_path,
                    user_id=document.user_id,
                    document_id=document.id,
                    filename="audiobook.mp3",
                    metadata={
                        "chapter_count": str(chapter_count),
                        "duration_seconds": str(duration_s),
                        "file_size_bytes": str(final_size),
                    },
                )
                logger.info(
                    "[SONORO] final_audio_uploaded path=%s size_bytes=%d duration_s=%d",
                    final_audio_path, final_size, duration_s,
                )

                document.final_audio_path = final_audio_path
                document.audio_duration_seconds = duration_s
                document.audio_file_size_bytes = final_size

                audio_file_size_bytes.observe(final_size)
                full_audiobook_generated_total.inc()

                job.progress_percentage = 98
                await session.commit()
            
            # ============================================
            # STEP 7: Mark complete
            # ============================================

            # Refuse to mark success if no final audio was produced — this prevents
            # the frontend from showing a "ready" state with a broken audio player.
            if not document.final_audio_path:
                raise RuntimeError(
                    "Pipeline finished but final_audio_path was never set. "
                    "Assembly step may have been skipped (empty chapter_audio_paths)."
                )

            job.status = JobStatus.COMPLETED
            job.progress_percentage = 100
            job.completed_at = datetime.utcnow()

            document.processing_status = ProcessingStatus.COMPLETED
            document.processing_completed_at = datetime.utcnow()

            await session.commit()

            logger.info(
                "[SONORO] job_completed job_id=%s audio_path=%s duration_s=%.1f chapters=%d",
                job_id,
                document.final_audio_path,
                (job.completed_at - job.started_at).total_seconds(),
                structure.chapter_count if structure else 1,
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
                
                logger.error(
                    "[SONORO] job_failed job_id=%s retry_count=%d error=%s",
                    job_id, retry_count, error_message,
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
