# BLOCK 8B: Quick Start Guide

**Document Upload & Processing UX** - Get started in 5 minutes

---

## 🚀 Quick Setup

### 1. Start the Frontend
```bash
cd frontend
npm run dev
```

Open http://localhost:3000

### 2. Login
- Navigate to `/login`
- Use your test account or register a new one
- You'll be redirected to the dashboard

### 3. Upload a Document
- Click "Documents" in the sidebar
- Drag & drop a PDF or click "Choose File"
- Watch the upload progress
- Document appears in the list

### 4. Monitor Processing
- The document card shows real-time status
- Click "View Details" to see detailed progress
- Auto-refreshes every 3-5 seconds
- Progress bar shows current stage

### 5. Download Audiobook
- Wait for "Completed" status
- Click "Download" button
- Audio file downloads automatically

---

## 📁 Key Files

### Service Layer
```
lib/
├── document-service.ts    # API calls
└── document-status.ts     # Status utilities
```

### Components
```
components/documents/
├── document-upload.tsx       # Upload UI
├── document-card.tsx         # List item
├── status-badge.tsx          # Status display
├── progress-indicator.tsx    # Progress bar
└── chapter-list.tsx          # Chapters
```

### Pages
```
app/(dashboard)/documents/
├── page.tsx           # List view
└── [id]/page.tsx      # Detail view
```

---

## 🔧 Common Tasks

### Add a New Status Type
```typescript
// lib/document-status.ts
export const statusConfig: Record<DocumentStatus, StatusConfig> = {
  // Add new status here
  new_status: {
    label: 'New Status',
    color: 'secondary',
    description: 'Description here',
    progressPercent: 50,
  },
};
```

### Change Upload Limits
```typescript
// components/documents/document-upload.tsx
const MAX_FILE_SIZE = 100 * 1024 * 1024; // Change to 100MB
const ACCEPTED_TYPES = {
  'application/pdf': ['.pdf'],
  'application/epub+zip': ['.epub'], // Add EPUB support
};
```

### Adjust Polling Intervals
```typescript
// Faster updates (every 2s)
refetchInterval: isProcessing ? 2000 : false

// Slower updates (every 10s)
refetchInterval: isProcessing ? 10000 : false
```

### Custom Progress Calculation
```typescript
// lib/document-status.ts
export function calculateProgress(job) {
  // Your custom logic here
  return customPercentage;
}
```

---

## 🎨 UI Customization

### Change Status Colors
```typescript
// components/documents/status-badge.tsx
const colorVariants = {
  success: 'bg-purple-100 text-purple-800', // Change success color
};
```

### Modify Card Layout
```typescript
// components/documents/document-card.tsx
// Change grid columns in page.tsx
<div className="grid gap-6 md:grid-cols-2 lg:grid-cols-4"> // 4 columns
```

### Custom Empty State
```typescript
// app/(dashboard)/documents/page.tsx
<div className="text-center py-12">
  <YourCustomIcon />
  <h3>Your custom message</h3>
</div>
```

---

## 🧪 Testing

### Test Upload
```typescript
// Open browser console
const file = new File(['test'], 'test.pdf', { type: 'application/pdf' });
// Use upload component to test
```

### Test API Calls
```typescript
// Browser console
import { getDocuments } from '@/lib/document-service';
const docs = await getDocuments();
console.log(docs);
```

### Check Auto-refresh
```typescript
// Documents page will show in console
refetchInterval: (query) => {
  console.log('Auto-refresh check');
  return hasProcessing ? 5000 : false;
}
```

---

## 🐛 Troubleshooting

### Upload Fails
1. Check file is PDF
2. Check file size < 50MB
3. Open Network tab in DevTools
4. Check backend is running
5. Verify JWT token in cookies

### Documents Not Loading
1. Check `/api/v1/documents` endpoint
2. Verify authentication token
3. Check browser console for errors
4. Try manual API call in DevTools

### Progress Not Updating
1. Check processing job exists
2. Verify polling is active (check Network tab)
3. Ensure document status is "processing"
4. Check backend job is actually running

### Download Fails
1. Verify document status is "completed"
2. Check audiobook_url exists
3. Verify blob download in Network tab
4. Check CORS settings on backend

---

## 📊 API Debugging

### Check Document List
```bash
curl -H "Authorization: Bearer YOUR_TOKEN" \
  http://localhost:8000/api/v1/documents
```

### Check Processing Job
```bash
curl -H "Authorization: Bearer YOUR_TOKEN" \
  http://localhost:8000/api/v1/documents/DOC_ID/job
```

### Check Chapters
```bash
curl -H "Authorization: Bearer YOUR_TOKEN" \
  http://localhost:8000/api/v1/documents/DOC_ID/chapters
```

---

## 🎯 Best Practices

### 1. Always Use Service Layer
```typescript
// ✅ Good
import { getDocuments } from '@/lib/document-service';
const docs = await getDocuments();

// ❌ Bad
const docs = await apiClient.get('/documents');
```

### 2. Use TanStack Query
```typescript
// ✅ Good
const { data } = useQuery({
  queryKey: ['documents'],
  queryFn: getDocuments
});

// ❌ Bad
const [data, setData] = useState([]);
useEffect(() => {
  getDocuments().then(setData);
}, []);
```

### 3. Handle Loading States
```typescript
if (isLoading) return <Skeleton />;
if (error) return <Alert />;
return <Content data={data} />;
```

### 4. Conditional Polling
```typescript
// Only poll when needed
refetchInterval: needsUpdate ? 3000 : false
```

---

## 🔗 Related Guides

- [BLOCK_8B_COMPLETE.md](./BLOCK_8B_COMPLETE.md) - Full documentation
- [BLOCK_8A_QUICK_START.md](./BLOCK_8A_QUICK_START.md) - Frontend setup
- [BLOCK_7_COMPLETE.md](./BLOCK_7_COMPLETE.md) - Backend APIs

---

## 💡 Tips

1. **Keep backend running** - Frontend needs API
2. **Clear cache** - Cmd+Shift+R to force reload
3. **Check Network tab** - See all API calls
4. **Use React DevTools** - Inspect query cache
5. **Test in incognito** - Avoid auth issues

---

**Happy coding! 🚀**
