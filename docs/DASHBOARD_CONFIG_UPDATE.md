# Dashboard Configuration Update - Required for All PRs

**Date**: May 28, 2026  
**Priority**: CRITICAL - Required for all branches and PRs

## Summary

All team members must update their local branches with the latest dashboard configuration changes pushed to main. This update fixes critical CORS and database type mismatch issues that prevent Correlation AI, Intake Inbox, and NLP Analysis Sessions from functioning correctly.

## Required Changes

### 1. Frontend API/WebSocket Configuration

All frontend API clients must be configured to use port **8002** (not 8000):

**Files to update:**
- `frontend/src/api/client.ts` - API base URL
- `frontend/src/api/websocket.ts` - WebSocket URL
- `frontend/src/api/fleetTracker.ts` - Fleet tracking WebSocket
- `frontend/src/api/fleetHealth.ts` - Fleet health WebSocket
- `frontend/src/api/geofencing.ts` - Geofencing WebSocket
- `frontend/src/components/kanban/TaskDetailModal.tsx` - User API endpoint

**Change pattern:**
```typescript
// OLD (incorrect)
http://localhost:8000
ws://localhost:8000

// NEW (correct)
http://localhost:8002
ws://localhost:8002
```

### 2. Backend Database Type Fixes

The backend API has been updated to fix PostgreSQL type mismatches. Ensure your branch includes:

**File:** `backend/app/api/analysis_sessions.py`

**Changes:**
- All UUID to String conversions for SessionDataSource and SessionMessage queries
- Removed DISTINCT clauses from queries with JSON columns
- String conversion for session_id in all queries

### 3. Local Development Setup

**Frontend must run directly (not in Docker):**

```bash
# Start backend services only
docker-compose up -d timescaledb backend

# Start frontend separately
cd frontend
npm install
npm run dev -- --port 9999
```

**Do NOT run frontend via Docker Compose** - this causes native module issues.

### 4. CORS Configuration

Backend CORS is configured to allow all origins for development. Ensure `backend/app/main.py` includes:

```python
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Allow all origins for development
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
```

## How to Update Your Branch

### Option 1: Rebase from Main (Recommended)

```bash
# Ensure your local main is up to date
git checkout main
git pull origin main

# Rebase your feature branch
git checkout your-feature-branch
git rebase main

# Resolve any conflicts if they occur
# git add <resolved-files>
# git rebase --continue

# Push your updated branch
git push origin your-feature-branch --force-with-lease
```

### Option 2: Cherry-Pick Specific Commits

```bash
# Get the commit hash from main
git log main --oneline

# Cherry-pick the configuration update commit
git cherry-pick <commit-hash>

# Push your updated branch
git push origin your-feature-branch
```

## Verification Checklist

Before submitting your PR, verify:

- [ ] Frontend runs on port 9999
- [ ] Backend runs on port 8002
- [ ] All API clients use `http://localhost:8002`
- [ ] All WebSocket clients use `ws://localhost:8002/ws`
- [ ] Correlation AI can create new analysis sessions
- [ ] Correlation AI can list sessions
- [ ] Intake Inbox can upload files
- [ ] Kanban board loads and functions
- [ ] No CORS errors in browser console
- [ ] No 500 Internal Server Errors in backend logs
- [ ] No PostgreSQL type mismatch errors in backend logs

## Impact

**Without this update:**
- Correlation AI will fail to create/list analysis sessions
- Intake Inbox will fail to upload/analyze data
- CORS errors will block all API calls from frontend
- PostgreSQL type errors will crash backend queries

**With this update:**
- All Correlation AI features work correctly
- Intake Inbox functions properly
- Frontend-backend communication works seamlessly
- Database queries execute without type errors

## Questions?

If you encounter issues updating your branch or have questions about these changes, please:
1. Check the updated README.md for detailed setup instructions
2. Review the commit `6aa62655` on main for the exact changes
3. Contact the team for assistance with merge conflicts

## Timeline

**Immediate Action Required**: All branches must be updated before submitting new PRs. Existing PRs should be updated as soon as possible to ensure compatibility with the main branch.
