# BLOCK 5A: Quick Start Guide

## 🚀 Getting Started

### 1. Run Database Migration

```bash
cd /Users/servinemilio/audiolibro-pdf
make migrate
```

Or manually:
```bash
docker-compose exec api alembic upgrade head
```

### 2. Install New Dependencies

The following packages were added to `requirements.txt`:
- `boto3==1.34.34` - S3-compatible storage
- `python-magic==0.4.27` - MIME type detection
- `PyMuPDF==1.23.26` - PDF metadata extraction
- `langdetect==1.0.9` - Language detection

**Install via Docker** (automatic on rebuild):
```bash
make build
make restart
```

**Or install locally** (if using venv):
```bash
pip install boto3 python-magic PyMuPDF langdetect
```

### 3. Configure DigitalOcean Spaces

Add to your `.env` file:

```bash
# DigitalOcean Spaces Configuration
SPACES_REGION=nyc3
SPACES_BUCKET=sonoro-documents
SPACES_ACCESS_KEY=your_access_key_here
SPACES_SECRET_KEY=your_secret_key_here
MAX_UPLOAD_SIZE_MB=50
```

**To get credentials**:
1. Go to https://cloud.digitalocean.com/spaces
2. Create a new Space (PRIVATE, not public)
3. Go to https://cloud.digitalocean.com/account/api/tokens
4. Generate Spaces access keys

### 4. Start Services

```bash
make dev
```

Check logs:
```bash
make logs-api
```

### 5. Test Upload

```bash
# 1. Register/login
TOKEN=$(curl -s -X POST http://localhost:8000/api/v1/auth/login \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -d "username=test@sonoro.com&password=TestPass123!" \
  | jq -r '.access_token')

# 2. Upload a PDF
curl -X POST http://localhost:8000/api/v1/documents/upload \
  -H "Authorization: Bearer $TOKEN" \
  -F "file=@/path/to/your/document.pdf" \
  | jq

# 3. List documents
curl http://localhost:8000/api/v1/documents/ \
  -H "Authorization: Bearer $TOKEN" \
  | jq

# 4. Check metrics
curl -s http://localhost:8000/metrics | grep sonoro_documents
```

---

## 📋 New Endpoints

All under `/api/v1/documents/`:

1. `POST /upload` - Upload PDF
2. `GET /` - List documents (paginated)
3. `GET /{id}` - Get document details
4. `GET /{id}/download-url` - Generate secure download link
5. `DELETE /{id}` - Delete document
6. `GET /info/limits` - Get upload limits

---

## 🔍 Verification Checklist

- [ ] Database migration ran successfully
- [ ] New `documents` table exists
- [ ] Dependencies installed (boto3, python-magic, PyMuPDF, langdetect)
- [ ] DigitalOcean Spaces configured
- [ ] Can upload a PDF file
- [ ] Can list uploaded documents
- [ ] Can generate download URL
- [ ] Can delete document
- [ ] Metrics appear in `/metrics` endpoint
- [ ] Activity logged in `user_activity_log` table

---

## 🐛 Troubleshooting

### "Import could not be resolved" errors
These are expected until dependencies are installed. Run:
```bash
make build && make restart
```

### "Storage service unavailable"
Check your `.env` file has correct `SPACES_*` variables.

### "libmagic not found"
Install system dependency:
```bash
# macOS
brew install libmagic

# Ubuntu/Debian (in Dockerfile)
apt-get install libmagic1
```

### Upload fails with 413
File exceeds 50MB limit. Adjust `MAX_UPLOAD_SIZE_MB` in `.env`.

### Pre-signed URL doesn't work
- Verify bucket is PRIVATE (not public)
- Check SPACES_ACCESS_KEY and SPACES_SECRET_KEY are correct
- Ensure bucket name matches SPACES_BUCKET

---

## 📚 Documentation

- **Full Documentation**: `docs/BLOCK_5A_COMPLETE.md`
- **API Docs**: http://localhost:8000/docs
- **Metrics**: http://localhost:8000/metrics

---

## ✅ Success Criteria

You've successfully completed Block 5A when:

1. ✅ You can upload a PDF via API
2. ✅ File appears in DigitalOcean Spaces
3. ✅ Document record exists in database
4. ✅ Metadata extracted (page count, language)
5. ✅ Can generate download URL
6. ✅ Can delete document
7. ✅ Metrics show in Prometheus

---

## 🎯 What's Next?

**Block 5B** (Processing Pipeline):
- Celery task queuing
- Status updates
- Progress tracking
- Error handling

**Block 6** (TTS Engine):
- Chapter detection
- Audio generation
- Voice selection
- Format conversion

---

*For detailed implementation details, see `docs/BLOCK_5A_COMPLETE.md`*
