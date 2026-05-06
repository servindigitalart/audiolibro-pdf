# BLOCK 6A: TTS Provider Abstraction + First Provider

**Status**: ✅ COMPLETE  
**Date**: February 11, 2026  
**Version**: 0.6.0

## 📋 Overview

Block 6A implements a modular Text-to-Speech (TTS) engine with:
- Abstract provider interface for multi-provider support
- Google Cloud TTS integration (first provider)
- Full cost tracking and Prometheus metrics
- Integration with existing Celery processing pipeline
- Audio storage in DigitalOcean Spaces

**What Block 6A Does**:
- ✅ Provider abstraction layer
- ✅ Google Cloud TTS integration
- ✅ Character counting and cost estimation
- ✅ Audio file storage (MP3)
- ✅ Job progress tracking
- ✅ Cost event recording
- ✅ Prometheus metrics

**What Block 6A Does NOT Do** (future blocks):
- ❌ Chapter detection
- ❌ Audio concatenation/chunking
- ❌ Response caching
- ❌ Multi-provider routing
- ❌ Advanced audio processing

---

## 🏗️ Architecture

### Layer Structure

```
┌─────────────────────────────────────────────────────────┐
│                   Celery Task Layer                      │
│              (process_document_job)                      │
└────────────────────┬────────────────────────────────────┘
                     │
                     ▼
┌─────────────────────────────────────────────────────────┐
│                   TTS Service Layer                      │
│              (TTSService)                                │
│  • Character counting                                    │
│  • Cost estimation                                       │
│  • Metrics emission                                      │
│  • Cost tracking                                         │
└────────────────────┬────────────────────────────────────┘
                     │
                     ▼
┌─────────────────────────────────────────────────────────┐
│              Provider Abstraction Layer                  │
│              (TTSProvider ABC)                           │
└────────────────────┬────────────────────────────────────┘
                     │
                     ▼
┌─────────────────────────────────────────────────────────┐
│              Concrete Provider                           │
│           (GoogleTTSProvider)                            │
│  • Google Cloud TTS API                                  │
│  • Neural2 voices                                        │
│  • MP3 output                                            │
│  • Async-safe execution                                  │
└─────────────────────────────────────────────────────────┘
```

### Data Flow

```
1. User uploads document
   └─> Document stored in Spaces

2. User creates processing job
   └─> Job queued in Celery

3. Worker picks up job
   └─> process_document_job() task

4. Extract text (placeholder in 6A)
   └─> Sample text generated

5. TTS Service synthesizes
   ├─> Count characters
   ├─> Estimate cost
   ├─> Call GoogleTTSProvider
   ├─> Receive MP3 bytes
   ├─> Record cost event
   └─> Emit metrics

6. Store audio in Spaces
   └─> Path: audio/{user_id}/{document_id}/full.mp3

7. Update job status
   └─> Status: COMPLETED
```

---

## 📁 Files Created

### TTS Provider System

1. **`app/services/tts/base.py`** (96 lines)
   - Abstract `TTSProvider` class
   - Exception classes: `TTSProviderError`, `TTSQuotaExceededError`, etc.
   - Provider interface definition

2. **`app/services/tts/google_provider.py`** (244 lines)
   - `GoogleTTSProvider` implementation
   - Google Cloud TTS API integration
   - Neural2 voice support
   - Async-safe execution with `run_in_executor`
   - Error handling for quota, network, invalid input

3. **`app/services/tts/tts_service.py`** (285 lines)
   - `TTSService` orchestration layer
   - Character counting
   - Cost tracking via `CostTracker`
   - Prometheus metrics emission
   - Provider-agnostic interface

4. **`app/services/tts/__init__.py`** (19 lines)
   - Module exports

---

## 📝 Files Modified

### Configuration

1. **`app/core/config.py`**
   - Added Google TTS configuration:
     - `google_tts_credentials_json`: Service account path
     - `google_tts_api_key`: API key (alternative)
     - `google_tts_project_id`: GCP project ID
     - `google_tts_default_voice`: Default voice (en-US-Neural2-A)
     - `google_tts_default_language`: Default language (en-US)

### Processing Integration

2. **`app/tasks/processing.py`**
   - Replaced simulation with real TTS integration
   - Text extraction (placeholder)
   - TTS synthesis via `TTSService`
   - Audio upload via `StorageService`
   - Progress tracking: 0% → 10% → 30% → 40% → 70% → 80% → 90% → 100%

### Storage Layer

3. **`app/services/storage_service.py`**
   - Added `upload_audio()` method
   - Stores MP3 files in `audio/{user_id}/{document_id}/` path
   - Audio-specific metadata handling
   - Content-Type: audio/mpeg

### Cost Governance

4. **`app/financial/cost/cost_enums.py`**
   - Added `CostProvider.GOOGLE` enum value

### Dependencies

5. **`services/api/requirements.txt`**
   - Added `google-cloud-texttospeech==2.16.3`

6. **`services/worker/requirements.txt`**
   - Added `google-cloud-texttospeech==2.16.3`
   - Added `boto3==1.34.34` (for storage access)

---

## 📊 Prometheus Metrics

Block 6A adds 5 new metrics for TTS monitoring:

### 1. `sonoro_tts_requests_total`
**Type**: Counter  
**Labels**: `provider`, `status`  
**Description**: Total TTS synthesis requests

```promql
# Success rate
rate(sonoro_tts_requests_total{status="success"}[5m])
/ rate(sonoro_tts_requests_total[5m])

# Requests by provider
sum by (provider) (rate(sonoro_tts_requests_total[5m]))
```

### 2. `sonoro_tts_characters_total`
**Type**: Counter  
**Labels**: `provider`  
**Description**: Total characters synthesized

```promql
# Characters per minute
rate(sonoro_tts_characters_total[1m]) * 60

# Total characters by provider
sum by (provider) (sonoro_tts_characters_total)
```

### 3. `sonoro_tts_cost_usd_total`
**Type**: Counter  
**Labels**: `provider`  
**Description**: Total TTS cost in USD

```promql
# Cost per hour
rate(sonoro_tts_cost_usd_total[1h]) * 3600

# Cost breakdown
sum by (provider) (sonoro_tts_cost_usd_total)
```

### 4. `sonoro_tts_failures_total`
**Type**: Counter  
**Labels**: `provider`, `failure_reason`  
**Description**: Total TTS failures

```promql
# Failure rate
rate(sonoro_tts_failures_total[5m])

# Failures by reason
sum by (failure_reason) (sonoro_tts_failures_total)
```

### 5. `sonoro_tts_latency_seconds`
**Type**: Histogram  
**Labels**: `provider`  
**Description**: TTS synthesis latency

```promql
# P95 latency
histogram_quantile(0.95, 
  rate(sonoro_tts_latency_seconds_bucket[5m])
)

# Average latency
rate(sonoro_tts_latency_seconds_sum[5m])
/ rate(sonoro_tts_latency_seconds_count[5m])
```

---

## 🔧 Configuration

### Environment Variables

Add to `.env`:

```bash
# Google Cloud TTS Configuration (BLOCK 6A)

# Option 1: Service Account (Recommended for production)
GOOGLE_TTS_CREDENTIALS_JSON=/path/to/service-account.json
GOOGLE_TTS_PROJECT_ID=your-gcp-project-id

# Option 2: API Key (Simpler but less secure)
# GOOGLE_TTS_API_KEY=your-api-key

# Voice Configuration
GOOGLE_TTS_DEFAULT_VOICE=en-US-Neural2-A
GOOGLE_TTS_DEFAULT_LANGUAGE=en-US
```

### Google Cloud Setup

#### 1. Enable Text-to-Speech API

```bash
gcloud services enable texttospeech.googleapis.com
```

#### 2. Create Service Account

```bash
# Create service account
gcloud iam service-accounts create sonoro-tts \
  --display-name="Sonoro TTS Service Account"

# Grant TTS permissions
gcloud projects add-iam-policy-binding YOUR_PROJECT_ID \
  --member="serviceAccount:sonoro-tts@YOUR_PROJECT_ID.iam.gserviceaccount.com" \
  --role="roles/cloudtexttospeech.user"

# Create and download key
gcloud iam service-accounts keys create service-account.json \
  --iam-account=sonoro-tts@YOUR_PROJECT_ID.iam.gserviceaccount.com
```

#### 3. Mount Service Account in Docker

Update `docker-compose.yml`:

```yaml
services:
  api:
    volumes:
      - ./service-account.json:/app/service-account.json:ro
    environment:
      - GOOGLE_TTS_CREDENTIALS_JSON=/app/service-account.json
  
  worker:
    volumes:
      - ./service-account.json:/app/service-account.json:ro
    environment:
      - GOOGLE_TTS_CREDENTIALS_JSON=/app/service-account.json
```

---

## 🧪 Testing

### Manual Testing

#### 1. Test TTS Provider Directly

```python
import asyncio
from app.services.tts.google_provider import GoogleTTSProvider

async def test_provider():
    provider = GoogleTTSProvider()
    
    # Synthesize text
    audio = await provider.synthesize(
        text="Hello, this is a test.",
        voice_id="en-US-Neural2-A",
        language_code="en-US"
    )
    
    # Save to file
    with open("test.mp3", "wb") as f:
        f.write(audio)
    
    print(f"Generated {len(audio)} bytes of audio")

asyncio.run(test_provider())
```

#### 2. Test via API

```bash
# 1. Get auth token
TOKEN=$(curl -s -X POST http://localhost:8000/api/v1/auth/login \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -d "username=test@example.com&password=password" | jq -r .access_token)

# 2. Upload document
DOC_ID=$(curl -s -X POST http://localhost:8000/api/v1/documents/upload \
  -H "Authorization: Bearer $TOKEN" \
  -F "file=@test.pdf" | jq -r .id)

# 3. Create processing job
JOB_ID=$(curl -s -X POST http://localhost:8000/api/v1/processing/documents/$DOC_ID/process \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"priority": 5}' | jq -r .id)

# 4. Monitor progress
watch -n 2 "curl -s http://localhost:8000/api/v1/processing/jobs/$JOB_ID \
  -H 'Authorization: Bearer $TOKEN' | jq '.progress_percentage, .status'"

# 5. Check metrics
curl -s http://localhost:8000/metrics | grep sonoro_tts
```

#### 3. Verify Audio Storage

```bash
# Check Spaces for audio file
aws s3 ls s3://sonoro-documents/audio/ --recursive \
  --endpoint-url https://nyc3.digitaloceanspaces.com
```

---

## 💰 Cost Tracking

### Cost Calculation

```python
# Google Cloud TTS Neural2 pricing
COST_PER_CHARACTER = $16 / 1,000,000 characters
                   = $0.000016 per character

# Example: 10,000 character document
cost = 10,000 * 0.000016 = $0.16
```

### Cost Events

Each TTS synthesis creates a `CostEvent`:

```json
{
  "user_id": "uuid",
  "event_type": "tts_characters",
  "provider": "google",
  "quantity": 10000,
  "unit_cost": 0.000016,
  "total_cost": 0.16,
  "metadata": {
    "provider": "google",
    "voice_id": "en-US-Neural2-A",
    "language_code": "en-US",
    "audio_size_bytes": 45320,
    "duration_seconds": 2.45
  }
}
```

### Query Costs

```bash
# Get user's TTS costs
curl -X GET "http://localhost:8000/api/v1/cost/summary?user_id=USER_ID" \
  -H "Authorization: Bearer $TOKEN"

# Get cost breakdown
curl -X GET "http://localhost:8000/api/v1/cost/events?event_type=tts_characters" \
  -H "Authorization: Bearer $TOKEN"
```

---

## 🎯 Success Criteria

### ✅ Completed Requirements

- [x] **Abstract provider interface**: `TTSProvider` ABC created
- [x] **Google Cloud TTS integration**: `GoogleTTSProvider` implemented
- [x] **Cost estimation**: `estimate_cost()` method
- [x] **Audio synthesis**: `synthesize()` returns MP3 bytes
- [x] **Cost tracking**: Integrated with `CostTracker`
- [x] **Storage integration**: Audio saved to Spaces
- [x] **Progress tracking**: 0% → 100% with milestones
- [x] **Prometheus metrics**: 5 new metrics added
- [x] **Error handling**: Custom exceptions with retries
- [x] **Celery integration**: Real TTS in processing task

### ✅ Integration Points

- **Block 2 (Auth)**: Uses user authentication
- **Block 3B (Observability)**: Emits Prometheus metrics
- **Block 3C (Cost Governance)**: Records cost events
- **Block 5A (Documents)**: Processes uploaded documents
- **Block 5B (Processing)**: Integrates into Celery tasks

---

## 🚨 Error Handling

### Exception Hierarchy

```
TTSProviderError (base)
├── TTSQuotaExceededError
├── TTSInvalidInputError
└── TTSNetworkError
```

### Retry Logic

Errors trigger Celery retry with exponential backoff:

```python
@celery_app.task(
    bind=True,
    base=ProcessingTask,
    max_retries=3,
    default_retry_delay=60,  # 1 minute
)
```

Retry sequence:
1. **Attempt 1**: Immediate
2. **Attempt 2**: After 1 minute
3. **Attempt 3**: After 2 minutes
4. **Attempt 4**: After 4 minutes
5. **Failed**: Job marked as FAILED

---

## 🔍 Monitoring

### Health Checks

```bash
# Check TTS provider initialization
curl http://localhost:8000/health

# Check worker logs
docker-compose logs -f worker | grep TTS

# Check for errors
docker-compose logs worker | grep -i error
```

### Metrics Queries

```bash
# Total TTS requests
curl -s http://localhost:8000/metrics | grep sonoro_tts_requests_total

# Character usage
curl -s http://localhost:8000/metrics | grep sonoro_tts_characters_total

# Cost tracking
curl -s http://localhost:8000/metrics | grep sonoro_tts_cost_usd_total

# Failure rate
curl -s http://localhost:8000/metrics | grep sonoro_tts_failures_total

# Latency
curl -s http://localhost:8000/metrics | grep sonoro_tts_latency_seconds
```

---

## 🐛 Troubleshooting

### Issue: "Failed to initialize Google TTS"

**Cause**: Missing or invalid credentials

**Solution**:
```bash
# Check environment variable
echo $GOOGLE_TTS_CREDENTIALS_JSON

# Verify file exists
ls -la /path/to/service-account.json

# Test credentials
gcloud auth activate-service-account \
  --key-file=/path/to/service-account.json

gcloud projects list
```

### Issue: "InvalidArgument: Invalid voice"

**Cause**: Voice ID doesn't exist or not available for language

**Solution**:
```bash
# List available voices
gcloud ml speech voices list --language-code=en-US

# Common Neural2 voices:
# - en-US-Neural2-A (Male)
# - en-US-Neural2-C (Female)
# - en-US-Neural2-D (Male)
# - en-US-Neural2-F (Female)
```

### Issue: "ResourceExhausted: Quota exceeded"

**Cause**: Google Cloud quota limits reached

**Solution**:
```bash
# Check quotas
gcloud services list --enabled | grep texttospeech

# Request quota increase in GCP Console:
# APIs & Services → Quotas → Text-to-Speech API
```

### Issue: Audio file not in Spaces

**Cause**: Storage credentials missing or path incorrect

**Solution**:
```bash
# Test Spaces access
aws s3 ls s3://sonoro-documents/ \
  --endpoint-url https://nyc3.digitaloceanspaces.com

# Check environment variables
echo $SPACES_ACCESS_KEY
echo $SPACES_SECRET_KEY
```

---

## 📈 Performance

### Expected Latency

| Characters | Expected Time | Cost    |
|-----------|---------------|---------|
| 1,000     | 1-2 seconds   | $0.016  |
| 5,000     | 2-4 seconds   | $0.080  |
| 10,000    | 4-8 seconds   | $0.160  |
| 50,000    | 20-40 seconds | $0.800  |

**Note**: Times include network latency and API processing.

### Optimization Tips

1. **Batch processing**: Process multiple chunks in parallel (future)
2. **Voice caching**: Cache voice selection per user (future)
3. **Result caching**: Cache audio for identical text (future)
4. **Regional endpoints**: Use closest GCP region

---

## 🔮 Future Enhancements

### Not Included in Block 6A (Future Blocks)

1. **Chapter Detection** (Block 6B)
   - Parse document structure
   - Detect chapters/sections
   - Generate chapter markers

2. **Chunked Processing** (Block 6B)
   - Split large documents
   - Process chunks in parallel
   - Concatenate audio files

3. **Multi-Provider Support** (Block 6C)
   - Amazon Polly integration
   - Azure TTS integration
   - Provider fallback/routing

4. **Audio Post-Processing** (Block 6D)
   - Silence trimming
   - Volume normalization
   - Format conversion (MP3, M4B, etc.)

5. **Response Caching** (Block 6E)
   - Cache identical text synthesis
   - Reduce API costs
   - Faster response times

---

## 📚 API Reference

### TTSProvider Interface

```python
class TTSProvider(ABC):
    @abstractmethod
    async def synthesize(
        self,
        text: str,
        voice_id: str,
        language_code: str,
    ) -> bytes:
        """Convert text to MP3 audio."""
        pass
    
    @abstractmethod
    def estimate_cost(self, character_count: int) -> float:
        """Estimate cost in USD."""
        pass
    
    @abstractmethod
    def get_provider_name(self) -> str:
        """Get provider name."""
        pass
```

### TTSService Usage

```python
from app.services.tts.tts_service import TTSService

service = TTSService()

# Synthesize text
audio_bytes = await service.synthesize_text(
    db=session,
    user_id=user.id,
    text="Hello world",
    voice_id="en-US-Neural2-A",  # Optional
    language_code="en-US",        # Optional
)

# Estimate cost
cost = service.estimate_cost(character_count=10000)
```

---

## ✅ Deployment Checklist

- [ ] Google Cloud project created
- [ ] Text-to-Speech API enabled
- [ ] Service account created with TTS permissions
- [ ] Service account JSON downloaded
- [ ] Environment variables configured
- [ ] Docker volumes mounted
- [ ] Dependencies installed (`make build`)
- [ ] Services restarted (`make up`)
- [ ] Worker logs show TTS initialization
- [ ] Test document processed successfully
- [ ] Audio file appears in Spaces
- [ ] Metrics visible in Prometheus
- [ ] Cost events recorded in database

---

## 📞 Support

### Logs to Check

```bash
# API logs
docker-compose logs -f api | grep -i tts

# Worker logs
docker-compose logs -f worker | grep -i tts

# Processing job logs
docker-compose logs -f worker | grep "job_id"

# Error logs
docker-compose logs --tail=100 worker | grep -i error
```

### Debug Mode

Enable debug logging:

```bash
# In docker-compose.yml
environment:
  - LOG_LEVEL=DEBUG

# Restart services
docker-compose restart api worker
```

---

**BLOCK 6A STATUS**: ✅ **COMPLETE**  
**Version**: 0.6.0  
**Total Lines**: ~800 (abstraction + provider + service + integration)  
**Files Created**: 4  
**Files Modified**: 6  
**New Metrics**: 5 Prometheus metrics  
**Dependencies Added**: google-cloud-texttospeech

**Next Block**: 6B - Chapter Detection & Chunked Processing
