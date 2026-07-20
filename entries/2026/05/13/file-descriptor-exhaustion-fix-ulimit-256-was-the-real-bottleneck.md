# File Descriptor Exhaustion Fix — ulimit 256 Was the Real Bottleneck

**Date:** 2026-05-13
**Time:** 06:10

## Summary

Expert-service was throwing DNS resolution failures and connection errors under eval load. The errors looked like Vertex AI rate limiting or network issues, but the root cause was macOS's default 256 file descriptor limit per process being exhausted.

## Symptoms

- `OSError: [Errno 24] Too many open files` when reading gcloud credentials
- `NameResolutionError: Failed to resolve 'oauth2.googleapis.com'` — DNS sockets couldn't be created
- `500 Internal Server Error` on `/ask` endpoint during eval runs
- Errors appeared random — sometimes during OAuth refresh, sometimes during DNS, sometimes during API calls

## Root Cause

macOS `launchctl` sets a soft limit of **256 file descriptors per process**. A single `dual_ask` call opens ~10+ FDs:

- 3 LLM calls via Vertex AI (each with HTTP connection + TLS)
- 3 gcloud credential file reads for OAuth token refresh
- 3 langfuse callback HTTP connections
- 2+ database sessions (sync pool checkouts)
- DNS sockets for each connection

With eval runs doing 50-4000 questions, concurrent requests quickly exceeded 256 FDs. The OS then refused to open new sockets or files, causing failures at whichever stage happened to need a new FD next — making it look like DNS issues or rate limiting.

## Fix

Two changes:

### 1. Raise FD limit in start script (`scripts/start.local.sh`)
```bash
ulimit -n 10240
```

### 2. Cap database connection pools (`db/connection.py`)
```python
engine = create_async_engine(url, pool_size=5, max_overflow=5)  # was unbounded overflow
_sync_engine = create_engine(url, pool_size=5, max_overflow=5)
```

### 3. Error handling on /ask endpoint (`api/chat.py`)
Added try/except around `dual_ask`/`single_ask` to return a clean 502 JSON response instead of crashing with a 500 and a wall of traceback.

## Results

- 7 errors during restart (in-flight requests), clean after that
- Now running 4000-question eval runs without errors
- The `ulimit` was the real fix; pool caps are defense in depth

## Key Insight

Connection errors under load are often FD exhaustion, not rate limiting or network problems. The error manifests at whatever syscall happens to need a new FD — DNS resolution, file reads, socket creation — which makes it look like unrelated issues. Always check `ulimit -n` and `launchctl limit maxfiles` on macOS.
