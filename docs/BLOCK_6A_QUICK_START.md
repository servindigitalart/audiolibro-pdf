# BLOCK 6A: Quick Start Guide

**TTS Provider Integration - 5 Minute Setup**

---

## 🚀 Quick Setup

### 1. Google Cloud Setup (5 minutes)

```bash
# Enable API
gcloud services enable texttospeech.googleapis.com

# Create service account
gcloud iam service-accounts create sonoro-tts \
  --display-name="Sonoro TTS"

# Grant permissions
gcloud projects add-iam-policy-binding YOUR_PROJECT_ID \
  --member="serviceAccount:sonoro-tts@YOUR_PROJECT_ID.iam.gserviceaccount.com" \
  --role="roles/cloudtexttospeech.user"

# Download credentials
gcloud iam service-accounts keys create service-account.json \
  --iam-account=sonoro-tts@YOUR_PROJECT_ID.iam.gserviceaccount.com
```

### 2. Configure Environment

```bash
# Add to .env
cat >> .env << EOF

# Google Cloud TTS (BLOCK 6A)
GOOGLE_TTS_CREDENTIALS_JSON=/app/service-account.json
GOOGLE_TTS_PROJECT_ID=your-project-id
GOOGLE_TTS_DEFAULT_VOICE=en-US-Neural2-A
GOOGLE_TTS_DEFAULT_LANGUAGE=en-US
EOF
```

### 3. Build & Deploy

```bash
cd /Users/servinemilio/audiolibro-pdf

# Rebuild containers
make build

# Start services
make up

# Check worker logs
docker-compose logs -f worker | grep "TTS"
```

---

## ✅ Test End-to-End

### Quick Test Script

```bash
#!/bin/bash
set -e

echo "🔐 Step 1: Login"
TOKEN=$(curl -s -X POST http://localhost:8000/api/v1/auth/login \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -d "username=test@example.com&password=password" | jq -r .access_token)

echo "📄 Step 2: Upload document"
DOC_ID=$(curl -s -X POST http://localhost:8000/api/v1/documents/upload \
  -H "Authorization: Bearer $TOKEN" \
  -F "file=@test.pdf" | jq -r .id)

echo "🎯 Step 3: Create processing job"
JOB_ID=$(curl -s -X POST http://localhost:8000/api/v1/processing/documents/$DOC_ID/process \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"priority": 5}' | jq -r .id)

echo "⏳ Step 4: Wait for completion"
while true; do
  STATUS=$(curl -s http://localhost:8000/api/v1/processing/jobs/$JOB_ID \
    -H "Authorization: Bearer $TOKEN" | jq -r '.status')
  PROGRESS=$(curl -s http://localhost:8000/api/v1/processing/jobs/$JOB_ID \
    -H "Authorization: Bearer $TOKEN" | jq -r '.progress_percentage')
  
  echo "Status: $STATUS | Progress: $PROGRESS%"
  
  if [ "$STATUS" = "completed" ] || [ "$STATUS" = "failed" ]; then
    break
  fi
  
  sleep 2
done

echo "📊 Step 5: Check metrics"
curl -s http://localhost:8000/metrics | grep sonoro_tts | head -10

echo "✅ Test complete!"
```

---

## 📊 Verify Success

### 1. Check Processing Job

```bash
# View job status
curl -X GET "http://localhost:8000/api/v1/processing/jobs/$JOB_ID" \
  -H "Authorization: Bearer $TOKEN" | jq

# Expected output:
{
  "id": "uuid",
  "status": "completed",
  "progress_percentage": 100,
  "created_at": "2026-02-11T...",
  "completed_at": "2026-02-11T..."
}
```

### 2. Check Storage

```bash
# List audio files in Spaces
aws s3 ls s3://sonoro-documents/audio/ --recursive \
  --endpoint-url https://nyc3.digitaloceanspaces.com

# Expected output:
# audio/USER_ID/DOC_ID/full.mp3
```

### 3. Check Metrics

```bash
curl -s http://localhost:8000/metrics | grep sonoro_tts

# Expected metrics:
# sonoro_tts_requests_total{provider="google",status="success"} 1
# sonoro_tts_characters_total{provider="google"} 234
# sonoro_tts_cost_usd_total{provider="google"} 0.003744
# sonoro_tts_latency_seconds_count{provider="google"} 1
```

### 4. Check Cost Events

```bash
# Query cost events
curl -X GET "http://localhost:8000/api/v1/cost/events?event_type=tts_characters" \
  -H "Authorization: Bearer $TOKEN" | jq

# Expected output:
[
  {
    "event_type": "tts_characters",
    "provider": "google",
    "quantity": 234,
    "total_cost": 0.003744,
    "metadata": {
      "voice_id": "en-US-Neural2-A",
      "language_code": "en-US"
    }
  }
]
```

---

## 🐛 Common Issues

### Issue: "Failed to initialize Google TTS"

```bash
# Check credentials file
ls -la service-account.json

# Verify it's mounted in Docker
docker-compose exec worker ls -la /app/service-account.json

# Test credentials
docker-compose exec worker \
  python -c "from google.cloud import texttospeech_v1; texttospeech_v1.TextToSpeechClient()"
```

### Issue: "Module not found: google.cloud"

```bash
# Rebuild with new dependencies
make build

# Verify installation
docker-compose exec worker pip list | grep google
```

### Issue: No audio in Spaces

```bash
# Check worker logs for errors
docker-compose logs worker | grep -A 10 "upload"

# Verify Spaces credentials
docker-compose exec worker env | grep SPACES
```

---

## 📈 Performance Expectations

| Operation | Time | Cost |
|-----------|------|------|
| Small doc (1K chars) | 2-3s | $0.016 |
| Medium doc (5K chars) | 3-5s | $0.080 |
| Large doc (10K chars) | 5-10s | $0.160 |

---

## 🎯 Success Checklist

- [ ] Worker logs show: "TTS Service initialized with provider: google"
- [ ] Processing job completes (status: completed)
- [ ] Audio file exists in Spaces (audio/USER_ID/DOC_ID/full.mp3)
- [ ] Metrics show tts_requests_total > 0
- [ ] Cost event recorded with type=tts_characters
- [ ] No errors in worker logs

---

## 📚 Next Steps

1. **Test different voices**: Try Neural2-C, Neural2-D, Neural2-F
2. **Test languages**: Try es-ES, fr-FR, de-DE
3. **Monitor costs**: Set up cost alerts
4. **Scale testing**: Process multiple documents

---

## 💡 Tips

- **Development**: Use smaller test documents to save costs
- **Production**: Monitor quota limits in GCP Console
- **Optimization**: Cache service account client initialization
- **Security**: Never commit service-account.json to git

---

**Need Help?** Check `docs/BLOCK_6A_COMPLETE.md` for detailed documentation.
