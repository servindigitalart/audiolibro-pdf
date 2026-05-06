# BLOCK 6C: Audio Assembly & Output Layer - Complete Documentation

## Overview

**BLOCK 6C** implements the final stage of the audiobook generation pipeline: assembling chapter audio files into a single high-quality audiobook with consistent loudness and proper metadata tagging.

**Version**: 0.8.0  
**Status**: ✅ Complete  
**Dependencies**: BLOCK 6A (TTS), BLOCK 6B (Chapter Detection)

---

## Architecture

### Processing Pipeline

```
┌─────────────────────────────────────────────────────────────────┐
│                    BLOCK 6C: Audio Assembly                      │
└─────────────────────────────────────────────────────────────────┘

PROCESSING (90%) → ASSEMBLING (91-93%) → FINALIZING (94-98%) → COMPLETED (100%)
                         ↓                      ↓
                   Concatenate            Normalize & Tag
                   
Step 3: Audio Assembly (91-93%)
├── Download chapter MP3 files from storage
├── Concatenate in correct order
├── Preserve bitrate consistency (128 kbps)
└── Calculate duration & file size

Step 4: Normalization (94-96%)
├── Normalize to -20.0 dBFS
├── Ensure consistent loudness
└── Trim leading/trailing silence (>1000ms)

Step 5: Metadata Tagging (96-98%)
├── Add ID3v2 tags
│   ├── Title (from filename)
│   ├── Author (from document metadata)
│   ├── Language (detected language)
│   ├── Processing date (UTC timestamp)
│   └── Comment (chapter count)
└── Preserve audio quality

Step 6: Upload Final Audiobook (98-100%)
├── Upload to DigitalOcean Spaces
├── Store path in document.final_audio_path
├── Track duration & file size
└── Emit metrics
```

---

## Components

### 1. AudioAssembler (`app/services/audio/assembler.py`)

**Purpose**: Concatenates chapter MP3 files in correct order while preserving bitrate consistency.

**Key Features**:
- Loads chapter files using pydub
- Validates bitrate consistency across chapters
- Concatenates audio segments
- Exports with optimal settings (128 kbps VBR, q:a 2)
- Calculates total duration and file size
- Async-safe operations (runs in thread pool)

**Usage**:
```python
from app.services.audio.assembler import AudioAssembler

assembler = AudioAssembler(target_bitrate=128)

output_path, metrics = await assembler.assemble_chapters(
    chapter_paths=["/tmp/chapter_1.mp3", "/tmp/chapter_2.mp3"],
    output_path="/tmp/audiobook.mp3",
)

print(f"Duration: {metrics.duration_seconds}s")
print(f"File size: {metrics.file_size_bytes / (1024**2):.2f} MB")
print(f"Bitrate: {metrics.bitrate_kbps} kbps")
```

**Metrics Returned**:
```python
@dataclass
class AudioMetrics:
    duration_seconds: float
    file_size_bytes: int
    bitrate_kbps: int
    sample_rate_hz: int
    channels: int
    chapter_count: int
```

**Error Handling**:
- `AudioFileNotFoundError`: Chapter file not found
- `InvalidAudioFileError`: Chapter file corrupted
- `BitrateInconsistencyError`: Bitrate mismatch (warning only)
- `AudioAssemblyError`: General assembly failure

---

### 2. AudioNormalizer (`app/services/audio/normalizer.py`)

**Purpose**: Normalizes audio loudness to consistent dBFS levels and optionally trims silence.

**Key Features**:
- Normalizes to target dBFS (default: -20.0)
- Ensures consistent loudness across audiobooks
- Detects and trims leading/trailing silence
- Minimum silence threshold: 1000ms (configurable)
- Silence detection threshold: -40 dB (configurable)
- Preserves audio quality
- Async-safe operations

**Usage**:
```python
from app.services.audio.normalizer import AudioNormalizer

normalizer = AudioNormalizer(
    target_dbfs=-20.0,
    silence_threshold_db=-40,
    min_silence_len_ms=1000,
)

output_path, metrics = await normalizer.normalize(
    input_path="/tmp/audiobook.mp3",
    output_path="/tmp/audiobook_normalized.mp3",
    trim_silence=True,
)

print(f"Original: {metrics.original_dbfs:.2f} dBFS")
print(f"Normalized: {metrics.normalized_dbfs:.2f} dBFS")
print(f"Trimmed: {metrics.trim_start_ms}ms start, {metrics.trim_end_ms}ms end")
```

**Metrics Returned**:
```python
@dataclass
class NormalizationMetrics:
    original_dbfs: float
    normalized_dbfs: float
    trim_start_ms: int
    trim_end_ms: int
    duration_before_seconds: float
    duration_after_seconds: float
```

**Why -20.0 dBFS?**
- Industry standard for audiobooks
- Leaves headroom for dynamic range
- Consistent with streaming platforms
- Prevents clipping and distortion

---

### 3. AudioMetadataWriter (`app/services/audio/metadata.py`)

**Purpose**: Writes ID3v2 metadata tags to MP3 audiobook files.

**Key Features**:
- ID3v2.3 and ID3v2.4 support
- Standard audiobook tags
- Processing date tracking
- Optional album art embedding
- Async-safe operations
- Uses mutagen library

**Usage**:
```python
from app.services.audio.metadata import AudioMetadataWriter, AudioMetadata
from datetime import datetime

writer = AudioMetadataWriter()
metadata = AudioMetadata(
    title="My Audiobook",
    author="John Doe",
    language="en",
    processing_date=datetime.utcnow(),
    comment="Generated by Sonoro - 15 chapters",
)

tags = await writer.write_metadata(
    audio_path="/tmp/audiobook.mp3",
    metadata=metadata,
)

print(f"Tags written: {tags}")
```

**Metadata Fields**:

| ID3 Tag | Field | Example |
|---------|-------|---------|
| TIT2 | Title | "Getting Started with Python" |
| TPE1 | Author/Artist | "John Smith" |
| TALB | Album | "Getting Started with Python" |
| TLAN | Language | "en" |
| TDRC | Processing Date | "2026-02-11" |
| COMM | Comment | "Processed by Sonoro on 2026-02-11" |
| APIC | Album Art | (optional cover image) |

**ID3 Tag Format**:
- Encoding: UTF-8 (encoding=3)
- Version: ID3v2.4 (default)
- Language: "eng" for comments

---

## Database Changes

### Updated Document Model

**New Fields**:
```python
# Audio output (BLOCK 6C)
final_audio_path = Column(
    String(1024),
    nullable=True,
    comment="Path to final assembled audiobook MP3"
)
audio_duration_seconds = Column(
    Integer,
    nullable=True,
    comment="Total audiobook duration in seconds"
)
audio_file_size_bytes = Column(
    BigInteger,
    nullable=True,
    comment="Final audiobook file size in bytes"
)
```

**New Processing Statuses**:
```python
class ProcessingStatus(str, enum.Enum):
    NOT_STARTED = "not_started"
    QUEUED = "queued"
    PROCESSING = "processing"
    ASSEMBLING = "assembling"      # BLOCK 6C: Concatenating chapters
    FINALIZING = "finalizing"      # BLOCK 6C: Normalizing and adding metadata
    COMPLETED = "completed"
    FAILED = "failed"
```

### Migration

**File**: `alembic/versions/008_audio_assembly.py`

**Adds**:
- 3 new columns to `documents` table
- 2 new enum values to `ProcessingStatus`

**Run Migration**:
```bash
make migrate
# or
docker-compose exec api alembic upgrade head
```

---

## Prometheus Metrics

### 5 New Metrics

#### 1. `sonoro_audio_assembly_seconds`
**Type**: Histogram  
**Description**: Audio assembly (concatenation) duration in seconds  
**Buckets**: [1, 5, 10, 30, 60, 120, 300, 600]  

```promql
# Average assembly time
avg(sonoro_audio_assembly_seconds)

# P95 assembly time
histogram_quantile(0.95, sonoro_audio_assembly_seconds_bucket)
```

#### 2. `sonoro_audio_file_size_bytes`
**Type**: Histogram  
**Description**: Final audiobook file size in bytes  
**Buckets**: [1MB, 5MB, 10MB, 50MB, 100MB, 500MB, 1GB]  

```promql
# Average file size
avg(sonoro_audio_file_size_bytes) / 1024 / 1024

# Files larger than 100MB
sum(rate(sonoro_audio_file_size_bytes_bucket{le="100000000"}[5m]))
```

#### 3. `sonoro_full_audiobook_generated_total`
**Type**: Counter  
**Description**: Total full audiobooks generated successfully  

```promql
# Total audiobooks generated
sonoro_full_audiobook_generated_total

# Audiobooks per hour
rate(sonoro_full_audiobook_generated_total[1h])
```

#### 4. `sonoro_audio_normalization_seconds`
**Type**: Histogram  
**Description**: Audio normalization duration in seconds  
**Buckets**: [1, 5, 10, 30, 60, 120, 300]  

```promql
# Average normalization time
avg(sonoro_audio_normalization_seconds)

# Normalization rate
rate(sonoro_audio_normalization_seconds_count[5m])
```

#### 5. `sonoro_audio_metadata_write_seconds`
**Type**: Histogram  
**Description**: Audio metadata writing duration in seconds  
**Buckets**: [0.1, 0.5, 1.0, 2.0, 5.0, 10.0]  

```promql
# Average metadata write time
avg(sonoro_audio_metadata_write_seconds)

# Slow metadata writes (>2s)
histogram_quantile(0.95, sonoro_audio_metadata_write_seconds_bucket{le="2.0"})
```

---

## Updated Processing Flow

### Complete Pipeline (0-100%)

```
QUEUED (0%)
  ↓
PROCESSING (5-90%)
  │
  ├─ Step 1 (5-20%): Analyze Document Structure
  │    ├─ Extract pages with fonts
  │    ├─ Run TOC extractor
  │    ├─ Run heuristic detector
  │    ├─ Run structural analyzer
  │    ├─ Fuse detections
  │    └─ Persist chapters to DB
  │
  └─ Step 2 (30-90%): Generate TTS per Chapter
       ├─ Loop through detected chapters
       ├─ Synthesize audio for each
       ├─ Store as separate MP3 files
       └─ Track paths for assembly
  ↓
ASSEMBLING (91-93%)
  │
  └─ Step 3: Audio Assembly
       ├─ Download chapter MP3s
       ├─ Concatenate in order
       ├─ Preserve bitrate (128 kbps)
       └─ Calculate duration & size
  ↓
FINALIZING (94-98%)
  │
  ├─ Step 4 (94-96%): Normalize Audio
  │    ├─ Normalize to -20.0 dBFS
  │    ├─ Trim silence (>1000ms)
  │    └─ Preserve quality
  │
  └─ Step 5 (96-98%): Add Metadata
       ├─ Write ID3v2 tags
       ├─ Title, author, language
       ├─ Processing date
       └─ Comment with chapter count
  ↓
Step 6 (98-100%): Upload Final Audiobook
  ├─ Upload to storage
  ├─ Store final_audio_path
  ├─ Track duration & file size
  └─ Emit metrics
  ↓
COMPLETED (100%)
```

---

## Dependencies

### Python Packages

**Required**:
```txt
pydub==0.25.1          # Audio manipulation
mutagen==1.47.0        # ID3 metadata tagging
ffmpeg-python==0.2.0   # Audio encoding/decoding
```

**System**:
- FFmpeg (required by pydub)

**Docker Installation**:
```dockerfile
# In api.Dockerfile
RUN apt-get update && apt-get install -y ffmpeg
RUN pip install pydub mutagen ffmpeg-python
```

---

## Error Handling

### Exception Hierarchy

```python
AudioProcessingError (base)
├── AudioAssemblyError
│   ├── AudioFileNotFoundError
│   ├── InvalidAudioFileError
│   └── BitrateInconsistencyError
├── AudioNormalizationError
└── AudioMetadataError
```

### Error Recovery

**Assembly Failures**:
- Validate all chapter files exist before assembly
- Log detailed error with chapter index
- Mark job as FAILED
- Store error message in job.error_message

**Normalization Failures**:
- Analyze loudness before normalization
- Use fallback settings if normalization fails
- Continue with unnormalized audio if critical

**Metadata Failures**:
- Non-critical: log warning and continue
- Upload audiobook without metadata
- Retry metadata write separately

---

## Performance Benchmarks

### Expected Performance

| Operation | Target | Typical | Max |
|-----------|--------|---------|-----|
| Assembly (10 chapters) | < 30s | 10-20s | 60s |
| Assembly (50 chapters) | < 120s | 60-90s | 300s |
| Normalization | < 30s | 10-20s | 60s |
| Metadata write | < 2s | 0.5-1s | 5s |
| **Total (assembly+finalize)** | **< 120s** | **30-60s** | **300s** |

### File Size Estimates

| Duration | Bitrate | File Size |
|----------|---------|-----------|
| 1 hour | 128 kbps | ~56 MB |
| 3 hours | 128 kbps | ~168 MB |
| 10 hours | 128 kbps | ~560 MB |
| 20 hours | 128 kbps | ~1.1 GB |

### Resource Usage

**CPU**: High during assembly/normalization  
**Memory**: ~100-500 MB per operation  
**Disk**: 3x audio file size (temp files)  
**Network**: Upload bandwidth dependent  

---

## Testing

### Unit Tests

```python
import pytest
from app.services.audio.assembler import AudioAssembler
from app.services.audio.normalizer import AudioNormalizer
from app.services.audio.metadata import AudioMetadataWriter, AudioMetadata

@pytest.mark.asyncio
async def test_audio_assembly():
    """Test chapter concatenation."""
    assembler = AudioAssembler(target_bitrate=128)
    
    output, metrics = await assembler.assemble_chapters(
        chapter_paths=["test_chapter_1.mp3", "test_chapter_2.mp3"],
        output_path="/tmp/test_audiobook.mp3",
    )
    
    assert metrics.chapter_count == 2
    assert metrics.duration_seconds > 0
    assert metrics.bitrate_kbps == 128

@pytest.mark.asyncio
async def test_audio_normalization():
    """Test audio normalization."""
    normalizer = AudioNormalizer(target_dbfs=-20.0)
    
    output, metrics = await normalizer.normalize(
        input_path="/tmp/test_audiobook.mp3",
        output_path="/tmp/test_normalized.mp3",
        trim_silence=True,
    )
    
    assert abs(metrics.normalized_dbfs - (-20.0)) < 1.0
    assert metrics.duration_after_seconds > 0

@pytest.mark.asyncio
async def test_metadata_writing():
    """Test ID3 metadata writing."""
    writer = AudioMetadataWriter()
    metadata = AudioMetadata(
        title="Test Audiobook",
        author="Test Author",
        language="en",
    )
    
    tags = await writer.write_metadata(
        audio_path="/tmp/test_normalized.mp3",
        metadata=metadata,
    )
    
    assert "title" in tags
    assert "author" in tags
    assert tags["title"] == "Test Audiobook"
```

### Integration Tests

```bash
# Test complete pipeline
curl -X POST http://localhost:8000/api/v1/documents/upload \
  -H "Authorization: Bearer $TOKEN" \
  -F "file=@test_book.pdf"

# Monitor processing
docker-compose logs -f worker | grep -E "assembling|finalizing"

# Check metrics
curl http://localhost:8000/metrics | grep sonoro_audio
```

---

## Configuration

### Audio Quality Settings

```python
# In app/services/audio/assembler.py
class AudioAssembler:
    def __init__(self, target_bitrate: int = 128):
        self.target_bitrate = target_bitrate  # 128 kbps recommended
        
# In app/services/audio/normalizer.py
class AudioNormalizer:
    def __init__(
        self,
        target_dbfs: float = -20.0,        # Loudness target
        silence_threshold_db: int = -40,   # Silence detection
        min_silence_len_ms: int = 1000,    # Minimum trim length
    ):
        ...
```

### Environment Variables

```bash
# Optional: Override defaults in .env
AUDIO_TARGET_BITRATE=128
AUDIO_TARGET_DBFS=-20.0
AUDIO_SILENCE_THRESHOLD=-40
AUDIO_MIN_SILENCE_MS=1000
```

---

## Troubleshooting

### Issue: FFmpeg not found

**Symptom**: `FileNotFoundError: ffmpeg`

**Solution**:
```bash
# Install FFmpeg
brew install ffmpeg  # macOS
apt-get install ffmpeg  # Linux

# Or rebuild Docker container
make build
```

### Issue: Assembly fails with bitrate mismatch

**Symptom**: `BitrateInconsistencyError`

**Solution**:
- Check TTS service output bitrate
- Verify all chapters use same bitrate
- Use `preserve_bitrate=False` to force target bitrate

### Issue: Normalization produces clipping

**Symptom**: Audio distortion after normalization

**Solution**:
- Lower target_dbfs (e.g., -22.0 instead of -20.0)
- Check original audio quality
- Verify headroom setting

### Issue: Metadata not visible in player

**Symptom**: Tags not showing in audio player

**Solution**:
- Verify ID3v2 compatibility
- Try ID3v2.3 instead of ID3v2.4
- Clear existing tags first

### Issue: Large file upload fails

**Symptom**: Upload timeout for >500MB files

**Solution**:
- Increase Nginx upload limits
- Use multipart upload for large files
- Consider streaming upload

---

## Best Practices

### 1. Audio Quality
- Use 128 kbps bitrate for balance of quality/size
- Normalize to -20.0 dBFS for consistency
- Trim silence to improve listening experience
- Preserve original audio codec when possible

### 2. Performance
- Process assembly in background worker
- Use temporary local storage for assembly
- Clean up temporary files after upload
- Monitor memory usage for large files

### 3. Error Handling
- Validate all chapter files before assembly
- Implement retry logic for transient failures
- Log detailed error context
- Provide fallback for non-critical operations

### 4. Monitoring
- Track assembly duration per chapter count
- Monitor file size distribution
- Alert on abnormal processing times
- Track success/failure rates

---

## Future Enhancements

### Planned Features
1. **Variable Bitrate (VBR)**: Better quality/size ratio
2. **Multiple Quality Levels**: 64/128/256 kbps options
3. **Chapter Markers**: Add chapter navigation to MP3
4. **Album Art**: Automatic cover generation
5. **Streaming Optimization**: Progressive upload during assembly
6. **Format Support**: AAC, Opus, M4B formats

### Optimization Opportunities
1. **Parallel Processing**: Normalize while assembling
2. **Streaming Assembly**: Concatenate without temp files
3. **Smart Caching**: Cache normalized chapters
4. **Incremental Upload**: Upload chunks as ready

---

## API Integration (Future)

### Endpoints to Add

```python
# Get audiobook download URL
GET /api/v1/documents/{id}/audiobook
Response: {
    "download_url": "https://...",
    "duration_seconds": 3600,
    "file_size_bytes": 56000000,
    "bitrate_kbps": 128
}

# Get audiobook metadata
GET /api/v1/documents/{id}/audiobook/metadata
Response: {
    "title": "My Audiobook",
    "author": "John Doe",
    "language": "en",
    "chapter_count": 15
}

# Re-process audio (normalize/metadata only)
POST /api/v1/documents/{id}/audiobook/reprocess
Body: {
    "target_dbfs": -20.0,
    "trim_silence": true
}
```

---

## Summary

**BLOCK 6C** completes the audiobook generation pipeline by:

✅ **Assembling** chapter audio files into single MP3  
✅ **Normalizing** loudness to -20.0 dBFS  
✅ **Trimming** leading/trailing silence  
✅ **Adding** ID3v2 metadata tags  
✅ **Uploading** final audiobook to storage  
✅ **Tracking** duration and file size  
✅ **Emitting** 5 Prometheus metrics  

**Result**: Production-ready, high-quality audiobooks with consistent loudness and proper metadata.

---

**Version**: 0.8.0  
**Status**: ✅ Production Ready  
**Last Updated**: 2026-02-11
