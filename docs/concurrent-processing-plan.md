# Concurrent PDF Processing Implementation Plan

## Overview

Transform the bot from sequential PDF processing to concurrent processing using `asyncio.Queue` with worker tasks. This enables multiple PDFs to be processed simultaneously while maintaining control over resource usage.

## Current Architecture Problems

1. **Sequential Processing**: Each PDF blocks the callback until complete (download → extract → LLM → reply)
2. **No Concurrency Control**: Single-threaded execution means queued PDFs wait unnecessarily
3. **Poor Resource Utilization**: I/O-bound operations (LLM API calls) don't run in parallel

## Proposed Architecture

### Component Overview

```
┌─────────────────┐
│  Matrix Events  │
└────────┬────────┘
         │
         ▼
┌─────────────────────┐
│ message_callback()  │  ← Lightweight: validate, download, enqueue
└────────┬────────────┘
         │
         ▼
┌─────────────────────┐
│  asyncio.Queue      │  ← Job queue with metadata
└────────┬────────────┘
         │
         ▼
┌─────────────────────┐
│  Worker Pool (N)    │  ← Process jobs concurrently
│  - Worker 1         │
│  - Worker 2         │
│  - Worker 3         │
└─────────────────────┘
```

## Implementation Steps

### Step 1: Add Configuration Variables

**File**: `.env.example` and documentation

**New variables to add:**

- `MAX_CONCURRENT_WORKERS=3` - Number of concurrent PDF processing workers (default: 3)
- `QUEUE_MAX_SIZE=100` - Maximum queue size before backpressure (default: 100)

**Rationale**:

- 3 workers balances throughput vs API rate limits
- Queue size prevents memory issues if PDFs arrive faster than processing

### Step 2: Define Job Structure

**File**: `bot.py` (near top, after imports)

**Create a job dataclass/dict structure:**

```python
@dataclass
class PDFJob:
    room: MatrixRoom
    event: RoomMessageMedia
    file_data: bytes
    filename: str
    enqueued_at: float  # timestamp for monitoring
```

**Rationale**: Type-safe job structure makes worker implementation cleaner

### Step 3: Create Global Queue

**File**: `bot.py` (globals section)

**Add after llm_client initialization:**

```python
pdf_queue: asyncio.Queue = None  # Initialized in main()
worker_tasks: list[asyncio.Task] = []  # Track worker tasks
```

**Rationale**: Global access needed for callback and workers

### Step 4: Implement Worker Function

**File**: `bot.py` (new function after `process_pdf()`)

**Function signature:**

```python
async def pdf_worker(worker_id: int, queue: asyncio.Queue):
    """Worker that processes PDFs from the queue."""
```

**Worker logic flow:**

1. Infinite loop: `while True`
2. Get job from queue: `job = await queue.get()`
3. Log start: `logger.info(f"Worker {worker_id} processing {job.filename}")`
4. Send "processing" message to Matrix (reuse existing code)
5. Call `process_pdf(job.file_data, job.filename)`
6. Send summary or error message to Matrix
7. Mark task done: `queue.task_done()`
8. Exception handling: catch all, log, still mark done
9. Log completion with timing

**Key considerations:**

- Each worker needs unique ID for logging
- Must call `task_done()` even on exception (use try/finally)
- Should track processing time for monitoring
- Graceful handling of Matrix API errors

### Step 5: Modify message_callback

**File**: `bot.py` (lines 227-284)

**Transform from:**

- Await download → Await process → Send reply

**To:**

- Validate event (keep existing checks)
- Download PDF (keep existing download logic)
- Create PDFJob object
- Enqueue: `await pdf_queue.put(job)`
- Return immediately (non-blocking)
- Optional: Send "queued" acknowledgment message

**Key changes:**

```python
async def message_callback(room: MatrixRoom, event: RoomMessageMedia):
    # ... existing validation ...

    # Download (keep existing)
    download_response = await matrix_client.download(event.url)
    file_data = download_response.body

    # Create job and enqueue
    job = PDFJob(
        room=room,
        event=event,
        file_data=file_data,
        filename=event.body,
        enqueued_at=time.time()
    )

    await pdf_queue.put(job)
    logger.info(f"📥 Queued {event.body} (queue size: {pdf_queue.qsize()})")

    # Optional: acknowledge receipt
    await matrix_client.room_send(...)  # "Queued for processing"
```

**Rationale**: Callback becomes lightweight and non-blocking

### Step 6: Initialize Queue and Workers in main()

**File**: `bot.py` (`main()` function, lines 299-351)

**Add after login, before callback registration:**

```python
# Initialize PDF processing queue
global pdf_queue, worker_tasks
max_workers = int(os.getenv("MAX_CONCURRENT_WORKERS", "3"))
queue_max_size = int(os.getenv("QUEUE_MAX_SIZE", "100"))

pdf_queue = asyncio.Queue(maxsize=queue_max_size)
logger.info(f"📦 Created job queue (max size: {queue_max_size})")

# Spawn worker tasks
worker_tasks = [
    asyncio.create_task(pdf_worker(i, pdf_queue))
    for i in range(max_workers)
]
logger.info(f"👷 Spawned {max_workers} PDF processing workers")
```

**Rationale**: Workers start before listening for events

### Step 7: Graceful Shutdown Handling

**File**: `bot.py` (`main()` function, finally block)

**Add before client close:**

```python
finally:
    # Stop accepting new jobs
    logger.info("🛑 Stopping job queue...")

    # Wait for pending jobs to complete (with timeout)
    if pdf_queue:
        try:
            await asyncio.wait_for(pdf_queue.join(), timeout=60.0)
            logger.info("✅ All queued jobs completed")
        except asyncio.TimeoutError:
            logger.warning(f"⚠️ Timeout: {pdf_queue.qsize()} jobs still pending")

    # Cancel workers
    for task in worker_tasks:
        task.cancel()

    # Wait for worker cancellation
    await asyncio.gather(*worker_tasks, return_exceptions=True)
    logger.info("✅ Workers stopped")

    # ... existing session save and client close ...
```

**Rationale**:

- `queue.join()` waits for in-progress jobs
- Timeout prevents infinite hang
- Explicit worker cancellation ensures clean shutdown

### Step 8: Add Queue Monitoring (Optional Enhancement)

**File**: `bot.py` (new function)

**Optional periodic status logger:**

```python
async def queue_monitor(queue: asyncio.Queue, interval: int = 60):
    """Periodically log queue statistics."""
    while True:
        await asyncio.sleep(interval)
        logger.info(f"📊 Queue status: {queue.qsize()} pending jobs")
```

**Add to main():**

```python
# Optional: spawn monitoring task
if os.getenv("QUEUE_MONITORING", "false").lower() == "true":
    asyncio.create_task(queue_monitor(pdf_queue, interval=60))
```

**Rationale**: Useful for debugging queue buildup in production

## Testing Strategy

### Unit Testing

1. **Test worker processes jobs correctly**
   - Mock queue with test jobs
   - Verify process_pdf is called
   - Verify Matrix messages sent

2. **Test queue full behavior**
   - Fill queue to max_size
   - Verify put() blocks appropriately

3. **Test graceful shutdown**
   - Enqueue jobs
   - Trigger shutdown
   - Verify jobs complete

### Integration Testing

1. **Single PDF**: Verify end-to-end still works
2. **Multiple PDFs**: Upload 5 PDFs simultaneously, verify all processed
3. **Error handling**: Upload corrupt PDF, verify error message sent
4. **Queue saturation**: Upload 100 PDFs, verify queue doesn't OOM

### Load Testing

1. Upload 10 concurrent PDFs, measure total time
2. Compare sequential vs concurrent processing time
3. Monitor memory usage during concurrent processing

## Migration Considerations

### Backwards Compatibility

- ✅ No breaking changes to environment variables
- ✅ Default behavior maintains single-worker (sequential) if not configured
- ✅ Existing session/prompt file handling unchanged

### Configuration Defaults

- Default `MAX_CONCURRENT_WORKERS=3` maintains conservative resource usage
- Users can opt-in to higher concurrency by setting env var

### Monitoring and Observability

**Enhanced logging provides:**

- Worker ID in logs for tracing
- Queue size on enqueue
- Processing time per PDF
- Queue wait time (enqueued_at → started_at)

## Potential Issues and Solutions

### Issue 1: Matrix API Rate Limiting

**Problem**: Concurrent workers may hit Matrix API rate limits

**Solutions:**

- Add rate limiter using `asyncio.Semaphore` for Matrix API calls
- Implement exponential backoff on 429 errors
- Document recommended worker count (start with 3)

### Issue 2: LLM API Rate Limiting

**Problem**: OpenAI API has rate limits (requests/min, tokens/min)

**Solutions:**

- Worker count naturally limits concurrent LLM calls
- Document that workers should match API tier (e.g., 3 for tier 1)
- Add retry logic with exponential backoff (may already exist in SDK)

### Issue 3: Memory Usage with Large PDFs

**Problem**: Queue holding multiple large PDFs in memory

**Solutions:**

- Set reasonable `QUEUE_MAX_SIZE` (default 100)
- Consider disk-backed queue for very large deployments (future)
- Monitor memory usage in production

### Issue 4: Duplicate Processing on Restart

**Problem**: Jobs in queue lost on shutdown/crash

**Solutions:**

- Current implementation: jobs lost (acceptable for this use case)
- Future enhancement: persist queue to disk
- Matrix events are idempotent (can reprocess if needed)

### Issue 5: Worker Exceptions Crashing Workers

**Problem**: Unhandled exception in worker exits the worker permanently

**Solutions:**

- Wrap worker loop in try/except
- Log exception but continue loop
- Consider dead-letter queue for failed jobs (future)

## Performance Expectations

### Current (Sequential)

- Processing time per PDF: ~5-30 seconds (depends on LLM)
- 3 PDFs uploaded simultaneously: 15-90 seconds total
- Throughput: ~2-12 PDFs/minute

### After Implementation (Concurrent, 3 workers)

- Processing time per PDF: ~5-30 seconds (unchanged)
- 3 PDFs uploaded simultaneously: ~5-30 seconds total (3x improvement)
- Throughput: ~6-36 PDFs/minute (3x improvement)

### Scalability

- 5 workers: ~5x improvement
- 10 workers: Limited by API rate limits, not linear scaling

## Documentation Updates Needed

### CLAUDE.md

- Update architecture section with queue-based processing
- Document new environment variables
- Add performance characteristics

### README.md (if exists)

- Add section on concurrent processing configuration
- Document recommended worker counts for different API tiers

### .env.example

- Add new variables with comments

## Implementation Checklist

- [ ] Step 1: Add configuration variables to .env.example
- [ ] Step 2: Define PDFJob dataclass
- [ ] Step 3: Add global queue and worker_tasks variables
- [ ] Step 4: Implement pdf_worker() function
- [ ] Step 5: Refactor message_callback() to enqueue jobs
- [ ] Step 6: Initialize queue and spawn workers in main()
- [ ] Step 7: Add graceful shutdown logic
- [ ] Step 8: (Optional) Add queue monitoring
- [ ] Update CLAUDE.md with new architecture
- [ ] Update .env.example with new variables
- [ ] Test with single PDF
- [ ] Test with multiple concurrent PDFs
- [ ] Test graceful shutdown
- [ ] Test error handling

## Estimated Effort

- Implementation: ~30-40 lines of new code
- Refactoring existing code: ~20 lines
- Testing: ~1 hour
- Documentation: ~30 minutes
- **Total**: ~2-3 hours for complete implementation

## Rollback Plan

If issues arise:

1. Set `MAX_CONCURRENT_WORKERS=1` (simulates sequential processing)
2. Git revert to previous commit
3. Original sequential code is preserved in git history
