# Concurrent PDF Processing Implementation Plan

## Overview

This document outlines the step-by-step implementation of a concurrent PDF processing system for the Matrix PDF Summarizer Bot. The solution uses SQLite for job persistence and asyncio.run_in_executor() for CPU-bound work, maintaining Matrix client safety while providing immediate user feedback and crash resilience.

## Architecture

### Current State

- Single-threaded synchronous PDF processing
- User waits until entire PDF is processed before getting any feedback
- No resilience to crashes during processing

### Target State

- Immediate user feedback when PDF is uploaded ("Processing...")
- Concurrent processing of multiple PDFs using thread pool
- SQLite-backed job queue for crash resilience
- Background monitoring for completed jobs
- All Matrix operations remain in main async event loop (thread-safe)

## Implementation Steps

### Phase 1: Core Infrastructure

#### Step 1: Create Job Queue System

**File**: `job_queue.py`
**Duration**: 45 minutes

Create a SQLite-backed job queue manager with:

- Job model with states: PENDING, PROCESSING, COMPLETED, FAILED
- Thread-safe operations using locks
- Database schema with proper indexing
- Job persistence across restarts
- Retry logic for failed jobs
- Cleanup of old completed jobs

**Key Components**:

```python
class JobStatus(Enum):
    PENDING = "pending"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"

class Job:
    # Job data structure with metadata

class JobQueue:
    # SQLite operations with thread safety
```

#### Step 2: PDF Processing Module

**File**: `pdf_processor.py`
**Duration**: 30 minutes

Extract PDF processing logic from `bot.py` into a separate module:

- Move `extract_pdf_text()`, `remove_watermark()`, `summarize_text()` functions
- Make functions work with job objects
- Add proper error handling and logging
- Ensure all operations are synchronous (for thread pool execution)

#### Step 3: Database Configuration

**File**: Update `.env.example` and documentation
**Duration**: 10 minutes

Add configuration options:

```bash
# Job Queue Configuration
JOB_DB_PATH=jobs.db
MAX_WORKER_THREADS=3
JOB_CLEANUP_HOURS=24
MAX_JOB_RETRIES=3
COMPLETED_JOB_POLL_SECONDS=5
```

### Phase 2: Core Implementation

#### Step 4: Modify Main Bot Logic

**File**: `bot.py`
**Duration**: 60 minutes

Transform the message callback to use the job queue:

**Current Flow**:

```python
PDF uploaded → Download → Process → Send result
```

**New Flow**:

```python
PDF uploaded → Download → Queue job → Send "processing..." → Continue monitoring
```

**Key Changes**:

1. Modify `message_callback()` to:

   - Download PDF immediately
   - Save to temporary file or memory
   - Add job to queue with file data
   - Send immediate "processing..." reply
   - Return immediately

2. Add ThreadPoolExecutor for PDF processing
3. Add background async task to monitor completed jobs

#### Step 5: Background Job Processor

**File**: `bot.py` (add new async function)
**Duration**: 45 minutes

Create async background task that:

1. Polls job queue for PENDING jobs
2. Uses `asyncio.run_in_executor()` to process PDFs in thread pool
3. Updates job status appropriately
4. Handles errors and retries

```python
async def process_jobs_background():
    while True:
        job = job_queue.get_next_job()
        if job:
            # Process in thread pool
            await asyncio.run_in_executor(
                pdf_executor,
                process_pdf_job,
                job
            )
        await asyncio.sleep(1)
```

#### Step 6: Result Sender

**File**: `bot.py` (add new async function)
**Duration**: 30 minutes

Create async background task that:

1. Polls for COMPLETED jobs
2. Sends results back to Matrix room
3. Removes completed jobs from queue
4. Handles failed jobs appropriately

```python
async def send_results_background():
    while True:
        completed_jobs = job_queue.get_completed_jobs()
        for job in completed_jobs:
            await send_job_result(job)
            job_queue.remove_job(job.id)
        await asyncio.sleep(COMPLETED_JOB_POLL_SECONDS)
```

### Phase 3: Integration and Testing

#### Step 7: Main Function Integration

**File**: `bot.py`
**Duration**: 30 minutes

Update main() function to:

1. Initialize ThreadPoolExecutor
2. Start background tasks using `asyncio.create_task()`
3. Ensure proper cleanup on shutdown

```python
async def main():
    # Initialize executor and background tasks
    pdf_executor = ThreadPoolExecutor(max_workers=MAX_WORKER_THREADS)

    # Start background tasks
    job_processor_task = asyncio.create_task(process_jobs_background())
    result_sender_task = asyncio.create_task(send_results_background())

    # Existing Matrix sync logic...

    # Cleanup on exit
```

#### Step 8: Error Handling and Logging

**File**: Multiple files
**Duration**: 30 minutes

Add comprehensive error handling:

1. Network failures during PDF download
2. PDF processing errors (corrupt files, extraction failures)
3. LLM API failures (rate limits, timeouts)
4. Database errors
5. Matrix API errors when sending results

Enhance logging for:

- Job lifecycle tracking
- Performance metrics (processing times)
- Error diagnostics
- Queue status monitoring

#### Step 9: Configuration and Environment

**File**: `.env.example`, `CLAUDE.md`
**Duration**: 15 minutes

Update documentation:

1. Add new environment variables to `.env.example`
2. Update `CLAUDE.md` with new architecture explanation
3. Add troubleshooting section for common issues
4. Document new dependencies (none needed - using stdlib)

### Phase 4: Testing and Validation

#### Step 10: Unit Testing

**Duration**: 45 minutes

Create test scenarios:

1. Job queue operations (add, process, complete, fail)
2. PDF processing with various file types
3. Database persistence across "restarts"
4. Concurrent processing with multiple files
5. Error handling and retry logic

#### Step 11: Integration Testing

**Duration**: 30 minutes

Test complete workflow:

1. Upload multiple PDFs simultaneously
2. Verify immediate feedback messages
3. Confirm concurrent processing
4. Test crash recovery (stop/start bot during processing)
5. Verify all results are delivered correctly

#### Step 12: Performance Testing

**Duration**: 30 minutes

Measure and validate:

1. Response time for initial feedback (should be <2 seconds)
2. Concurrent processing performance vs sequential
3. Memory usage with multiple jobs
4. Database performance under load

## Implementation Details

### Database Schema

```sql
CREATE TABLE jobs (
    id TEXT PRIMARY KEY,
    filename TEXT NOT NULL,
    file_url TEXT NOT NULL,
    event_id TEXT NOT NULL,
    room_id TEXT NOT NULL,
    status TEXT NOT NULL,
    created_at REAL NOT NULL,
    started_at REAL,
    completed_at REAL,
    result TEXT,
    error_message TEXT,
    retry_count INTEGER DEFAULT 0
);

CREATE INDEX idx_status ON jobs(status);
CREATE INDEX idx_created_at ON jobs(created_at);
```

### Thread Safety Strategy

- **Main Thread**: All Matrix operations, SQLite reads/writes, asyncio event loop
- **Worker Threads**: PDF processing only (CPU-bound work)
- **Communication**: SQLite database acts as thread-safe message passing
- **No Shared State**: Workers don't share memory with main thread

### Error Recovery

1. **Network Errors**: Retry with exponential backoff
2. **PDF Errors**: Mark job as failed after max retries
3. **LLM Errors**: Retry with different parameters or model
4. **Database Errors**: Log and continue (SQLite is robust)
5. **Crash Recovery**: Jobs persist in database, resume on restart

### Performance Considerations

- **Thread Pool Size**: Configurable, default 3 workers
- **Memory Management**: Clean up old jobs periodically
- **Rate Limiting**: Respect OpenAI API limits
- **Resource Usage**: Monitor and limit concurrent operations

## Risk Mitigation

### Potential Issues

1. **SQLite Locking**: Use proper connection management and timeouts
2. **Memory Usage**: Large PDFs in memory - could implement file caching
3. **API Rate Limits**: Implement backoff for OpenAI API
4. **Thread Pool Exhaustion**: Monitor and configure appropriate limits

### Rollback Plan

If issues arise:

1. Feature flag to disable concurrent processing
2. Fallback to original synchronous processing
3. Database migration path to clean state
4. Configuration to adjust worker counts

## Success Metrics

### Functional Requirements

- ✅ Immediate feedback on PDF upload (<2 seconds)
- ✅ Multiple PDFs process concurrently
- ✅ All results delivered correctly
- ✅ Crash resilience (jobs resume after restart)

### Performance Requirements

- ✅ 2-3x faster overall throughput with multiple files
- ✅ Memory usage stays reasonable (<100MB per worker)
- ✅ No Matrix client instability
- ✅ Reliable job persistence

### User Experience

- ✅ Clear status messages ("Processing...", "Summary:", "Error:")
- ✅ Responsive bot that doesn't appear "stuck"
- ✅ Consistent behavior under load
- ✅ Graceful error handling with user-friendly messages

## Timeline

**Total Estimated Time**: 6-7 hours
**Recommended Approach**: Implement in phases, test each phase before proceeding
**Critical Path**: Job Queue → Bot Integration → Background Tasks → Testing

## Files to be Created/Modified

### New Files

- `job_queue.py` - Job queue management
- `pdf_processor.py` - Extracted PDF processing logic
- `docs/concurrent-processing-plan.md` - This document

### Modified Files

- `bot.py` - Main application logic updates
- `.env.example` - New configuration options
- `CLAUDE.md` - Architecture documentation update
- `pyproject.toml` - If any new dependencies needed (unlikely)

### Testing Files (Optional)

- `test_job_queue.py` - Unit tests for job queue
- `test_concurrent_processing.py` - Integration tests

This plan provides a robust, maintainable solution that achieves the goal of concurrent processing while maintaining system reliability and user experience.

