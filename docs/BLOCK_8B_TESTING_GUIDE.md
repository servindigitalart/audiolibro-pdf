# BLOCK 8B: Testing Guide

**Manual Testing Checklist for Document Management UI**

---

## 🧪 Pre-Testing Setup

### 1. Environment Check
```bash
cd frontend
npm run dev
# Server should be running on http://localhost:3001
```

### 2. Authentication
- Navigate to http://localhost:3001/login
- Login with test account or register new user
- Should redirect to dashboard

---

## 📋 Test Scenarios

### SCENARIO 1: Upload Valid PDF

**Steps:**
1. Navigate to `/documents`
2. Drag a PDF file (<50MB) onto the upload zone
3. Click "Upload & Process"

**Expected Results:**
- ✅ Upload progress bar appears
- ✅ Progress percentage updates in real-time
- ✅ Success message appears after upload
- ✅ Document appears in list with "Pending" or "Processing" status
- ✅ List refreshes automatically

**Test Files:**
- Small PDF (1-5 MB)
- Medium PDF (10-20 MB)
- Large PDF (30-50 MB)

---

### SCENARIO 2: Upload Invalid File

**Steps:**
1. Try to upload a non-PDF file (e.g., .txt, .docx, .jpg)
2. Try to upload a file >50MB

**Expected Results:**
- ✅ Error message: "Only PDF files are supported"
- ✅ Error message: "File is too large. Maximum size is 50MB"
- ✅ Upload does not proceed
- ✅ Can try again with valid file

---

### SCENARIO 3: Documents List View

**Steps:**
1. Navigate to `/documents` with existing documents
2. Observe the list

**Expected Results:**
- ✅ All documents displayed in grid layout
- ✅ Each card shows:
  - Document title
  - Filename
  - Upload date
  - File size
  - Status badge
  - Action buttons
- ✅ Status badges use appropriate colors:
  - Blue/Gray for Pending/Queued
  - Yellow for Processing
  - Green for Completed
  - Red for Failed
- ✅ Processing documents show progress bar
- ✅ Completed documents show "Download" button

---

### SCENARIO 4: Auto-Refresh During Processing

**Steps:**
1. Upload a document
2. Keep the documents list page open
3. Watch for 15-30 seconds

**Expected Results:**
- ✅ Status updates automatically every 5 seconds
- ✅ Progress bar updates in real-time
- ✅ No manual refresh needed
- ✅ Status changes reflect: Pending → Processing → Completed

**Debug:**
- Open browser DevTools → Network tab
- Should see API calls every 5 seconds when processing
- Calls stop when no documents are processing

---

### SCENARIO 5: Document Detail View

**Steps:**
1. Click "View Details" on any document
2. Navigate to `/documents/[id]`

**Expected Results:**
- ✅ Document title and filename displayed
- ✅ Status badge shown
- ✅ Document information card shows:
  - Upload date
  - File size
  - Number of pages (if available)
  - Number of chapters (if available)
  - Duration (if completed)
- ✅ Back button navigates to list
- ✅ Breadcrumb navigation works

---

### SCENARIO 6: Processing Progress (Detail View)

**Steps:**
1. View details of a document that's processing
2. Observe the progress section

**Expected Results:**
- ✅ Progress card appears
- ✅ Current stage displayed (e.g., "Analyzing", "Detecting Chapters")
- ✅ Progress bar updates every 3 seconds
- ✅ Progress percentage shown
- ✅ Stage description displayed
- ✅ Metadata shows (if available):
  - Current chapter
  - Pages processed / Total pages
  - Chapters processed / Total chapters

---

### SCENARIO 7: Completed Document

**Steps:**
1. View a completed document in detail view
2. Check chapters section

**Expected Results:**
- ✅ "Download Audiobook" button appears
- ✅ Chapters card appears
- ✅ All chapters listed with:
  - Chapter number
  - Chapter title
  - Page range
  - Confidence score (with color coding)
  - Status badge
  - Duration (if available)
- ✅ High confidence (>80%) = Green
- ✅ Medium confidence (60-80%) = Yellow
- ✅ Low confidence (<60%) = Red
- ✅ Preview button shown for completed chapters

---

### SCENARIO 8: Download Audiobook

**Steps:**
1. Click "Download" button on completed document

**Expected Results:**
- ✅ Download starts immediately
- ✅ File downloads as .mp3
- ✅ Filename matches document title
- ✅ No errors in console
- ✅ Audio file is playable

---

### SCENARIO 9: Failed Document

**Steps:**
1. View a document with "Failed" status

**Expected Results:**
- ✅ Status badge shows "Failed" in red
- ✅ Error message displayed
- ✅ "Retry Processing" button appears
- ✅ Clicking retry:
  - Shows loading spinner
  - Starts new processing job
  - Status changes back to "Processing"

---

### SCENARIO 10: Empty State

**Steps:**
1. Login with new account (no documents)
2. Navigate to `/documents`

**Expected Results:**
- ✅ Empty state message displayed
- ✅ Helpful text: "No documents yet"
- ✅ Upload component still visible
- ✅ Call to action: "Upload your first PDF above"

---

### SCENARIO 11: Responsive Design

**Steps:**
1. Open documents page
2. Resize browser window or use device emulator

**Expected Results:**

**Mobile (<768px):**
- ✅ Single column grid
- ✅ Sidebar collapses to hamburger menu
- ✅ Cards stack vertically
- ✅ Touch-friendly buttons
- ✅ Upload zone responsive

**Tablet (768px - 1024px):**
- ✅ Two column grid
- ✅ Sidebar visible
- ✅ Cards fit width

**Desktop (>1024px):**
- ✅ Three column grid
- ✅ Full sidebar
- ✅ Optimal spacing

---

### SCENARIO 12: Dark Mode

**Steps:**
1. Toggle dark mode using theme switcher
2. Navigate through all pages

**Expected Results:**
- ✅ All components adapt to dark theme
- ✅ Text remains readable
- ✅ Status badges have dark mode colors
- ✅ Cards have proper contrast
- ✅ Icons visible in both modes
- ✅ No white flashes during transitions

---

### SCENARIO 13: Navigation

**Steps:**
1. Navigate between pages:
   - Dashboard → Documents
   - Documents → Document Detail
   - Document Detail → Back to Documents

**Expected Results:**
- ✅ All navigation links work
- ✅ Active page highlighted in sidebar
- ✅ Back button works correctly
- ✅ Direct URL access works
- ✅ Browser back/forward buttons work

---

### SCENARIO 14: Error Handling

**Test Cases:**
1. **Network Error:**
   - Turn off backend server
   - Try to load documents
   - Expected: Error alert displayed

2. **Invalid Document ID:**
   - Navigate to `/documents/invalid-id`
   - Expected: Error message, back button works

3. **Upload Failure:**
   - Simulate network error during upload
   - Expected: Error message, can retry

4. **Download Failure:**
   - Try to download non-existent audiobook
   - Expected: Error logged in console

---

### SCENARIO 15: Loading States

**Steps:**
1. Observe loading states during:
   - Initial page load
   - Document fetch
   - Upload process
   - Status updates

**Expected Results:**
- ✅ Skeleton screens shown during loading
- ✅ Spinners shown for processing states
- ✅ Progress bars during upload
- ✅ No blank screens
- ✅ Smooth transitions

---

## 🔍 Browser Compatibility

Test in multiple browsers:

### Chrome/Edge (Chromium)
- [ ] All features work
- [ ] Drag & drop works
- [ ] Downloads work
- [ ] No console errors

### Firefox
- [ ] All features work
- [ ] Drag & drop works
- [ ] Downloads work
- [ ] No console errors

### Safari
- [ ] All features work
- [ ] Drag & drop works
- [ ] Downloads work
- [ ] No console errors

---

## 🐛 Bug Report Template

If you find issues, use this template:

```
**Bug:** [Brief description]

**Steps to Reproduce:**
1. 
2. 
3. 

**Expected Behavior:**

**Actual Behavior:**

**Environment:**
- Browser: 
- OS: 
- Screen Size: 

**Console Errors:**
[Paste any console errors]

**Screenshots:**
[If applicable]
```

---

## ✅ Final Checklist

### Functionality
- [ ] Upload works with valid PDFs
- [ ] Upload rejects invalid files
- [ ] Documents list displays correctly
- [ ] Auto-refresh works during processing
- [ ] Detail view shows all information
- [ ] Progress updates in real-time
- [ ] Chapters display correctly
- [ ] Download works for completed docs
- [ ] Retry works for failed docs
- [ ] Empty state displays properly

### UI/UX
- [ ] Responsive on mobile
- [ ] Responsive on tablet
- [ ] Responsive on desktop
- [ ] Dark mode works
- [ ] Light mode works
- [ ] Loading states appropriate
- [ ] Error states clear
- [ ] Navigation intuitive
- [ ] Animations smooth
- [ ] Icons render correctly

### Performance
- [ ] Initial load fast (<3s)
- [ ] No unnecessary re-renders
- [ ] Polling only when needed
- [ ] Downloads don't freeze UI
- [ ] No memory leaks

### Accessibility
- [ ] Keyboard navigation works
- [ ] Focus states visible
- [ ] Color contrast sufficient
- [ ] Screen reader friendly
- [ ] Error messages readable

---

## 🎯 Test Results

Record your test results:

| Scenario | Status | Notes |
|----------|--------|-------|
| 1. Upload Valid PDF | ⬜ | |
| 2. Upload Invalid File | ⬜ | |
| 3. Documents List View | ⬜ | |
| 4. Auto-Refresh | ⬜ | |
| 5. Document Detail | ⬜ | |
| 6. Processing Progress | ⬜ | |
| 7. Completed Document | ⬜ | |
| 8. Download Audiobook | ⬜ | |
| 9. Failed Document | ⬜ | |
| 10. Empty State | ⬜ | |
| 11. Responsive Design | ⬜ | |
| 12. Dark Mode | ⬜ | |
| 13. Navigation | ⬜ | |
| 14. Error Handling | ⬜ | |
| 15. Loading States | ⬜ | |

---

## 🚀 Ready for Production?

Only proceed when:
- ✅ All critical scenarios pass
- ✅ No console errors
- ✅ Responsive design verified
- ✅ Error handling tested
- ✅ Performance acceptable
- ✅ Backend integration confirmed

---

**Testing Complete!** 🎉

If all tests pass, BLOCK 8B is ready for production use.
