import asyncio
import json
import logging
import os
from concurrent.futures import ThreadPoolExecutor

from nio import (
    AsyncClient,
    MatrixRoom,
    RoomMessageMedia,
    RoomMessageText,
    InviteMemberEvent,
    LoginResponse,
    SyncResponse,
)
from dotenv import load_dotenv
from user_interactions import dm_callback, mention_callback, invite_callback
from job_queue import JobQueue, Job
from pdf_processor import process_pdf_dual_async
from llm_factory import LLMClientFactory

# -------------------------------------------------------------------
# Load environment variables
# -------------------------------------------------------------------
load_dotenv()

MATRIX_HOMESERVER = os.getenv("MATRIX_HOMESERVER")
MATRIX_USER = os.getenv("MATRIX_USER")
MATRIX_PASSWORD = os.getenv("MATRIX_PASSWORD")
MATRIX_ROOM_ID = os.getenv("MATRIX_ROOM_ID")
SESSION_FILE = os.getenv("SESSION_FILE", "session.json")

# Default LLM Configuration
DEFAULT_LLM_PROVIDER = os.getenv("DEFAULT_LLM_PROVIDER", "openai")
DEFAULT_LLM_MODEL = os.getenv("DEFAULT_LLM_MODEL", os.getenv("LLM_MODEL", "gpt-5-mini"))
DEFAULT_LLM_BASE_URL = os.getenv("DEFAULT_LLM_BASE_URL", os.getenv("LLM_BASE_URL"))
DEFAULT_LLM_API_KEY = os.getenv("DEFAULT_LLM_API_KEY", os.getenv("OPENAI_API_KEY"))
DEFAULT_LLM_PROMPT = os.getenv("DEFAULT_LLM_PROMPT", os.getenv("PROMPT_FILE", "prompts/medical_triage.txt"))

# Dual LLM Configuration
DUAL_LLM_ENABLED = os.getenv("DUAL_LLM_ENABLED", "false").lower() == "true"
SECONDARY_LLM_PROVIDER = os.getenv("SECONDARY_LLM_PROVIDER")
SECONDARY_LLM_MODEL = os.getenv("SECONDARY_LLM_MODEL")
SECONDARY_LLM_BASE_URL = os.getenv("SECONDARY_LLM_BASE_URL")
SECONDARY_LLM_API_KEY = os.getenv("SECONDARY_LLM_API_KEY")
SECONDARY_LLM_PROMPT = os.getenv("SECONDARY_LLM_PROMPT")

# Common LLM Parameters
LLM_TEMPERATURE = (
    float(os.getenv("LLM_TEMPERATURE")) if os.getenv("LLM_TEMPERATURE") else None
)
LLM_MAX_TOKENS = (
    int(os.getenv("LLM_MAX_TOKENS")) if os.getenv("LLM_MAX_TOKENS") else None
)

# Job Queue Configuration
JOB_DB_PATH = os.getenv("JOB_DB_PATH", "jobs.db")
MAX_WORKER_THREADS = int(os.getenv("MAX_WORKER_THREADS", "3"))
JOB_CLEANUP_HOURS = int(os.getenv("JOB_CLEANUP_HOURS", "24"))
MAX_JOB_RETRIES = int(os.getenv("MAX_JOB_RETRIES", "3"))
COMPLETED_JOB_POLL_SECONDS = int(os.getenv("COMPLETED_JOB_POLL_SECONDS", "5"))

# -------------------------------------------------------------------
# Logging
# -------------------------------------------------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("matrix-pdf-bot")

# -------------------------------------------------------------------
# Globals
# -------------------------------------------------------------------
matrix_client: AsyncClient | None = None
job_queue: JobQueue | None = None
pdf_executor: ThreadPoolExecutor | None = None

# Default LLM configuration
default_llm_config = {
    "provider": DEFAULT_LLM_PROVIDER,
    "api_key": DEFAULT_LLM_API_KEY,
    "model": DEFAULT_LLM_MODEL,
    "base_url": DEFAULT_LLM_BASE_URL,
    "prompt_file": DEFAULT_LLM_PROMPT,
    "temperature": LLM_TEMPERATURE,
    "max_tokens": LLM_MAX_TOKENS,
}

# Secondary LLM configuration (when dual enabled)
secondary_llm_config = None
if DUAL_LLM_ENABLED:
    secondary_llm_config = {
        "provider": SECONDARY_LLM_PROVIDER,
        "api_key": SECONDARY_LLM_API_KEY,
        "model": SECONDARY_LLM_MODEL,
        "base_url": SECONDARY_LLM_BASE_URL,
        "prompt_file": SECONDARY_LLM_PROMPT,
        "temperature": LLM_TEMPERATURE,
        "max_tokens": LLM_MAX_TOKENS,
    }

# Initialize LLM clients (will be set after configuration validation)
default_llm_client = None
secondary_llm_client = None

# In-memory storage for job file data (since SQLite doesn't store blobs efficiently)
job_file_data = {}


# -------------------------------------------------------------------
# Configuration validation and LLM client initialization
# -------------------------------------------------------------------
def validate_configuration():
    """Validate LLM configuration at startup."""
    errors = []

    # Validate default LLM config
    if not DEFAULT_LLM_API_KEY:
        errors.append("DEFAULT_LLM_API_KEY is required")
    if not DEFAULT_LLM_MODEL:
        errors.append("DEFAULT_LLM_MODEL is required")
    if not os.path.exists(DEFAULT_LLM_PROMPT):
        errors.append(f"Default prompt file not found: {DEFAULT_LLM_PROMPT}")

    # Validate dual LLM config (if enabled)
    if DUAL_LLM_ENABLED:
        if not SECONDARY_LLM_API_KEY:
            errors.append("SECONDARY_LLM_API_KEY required when DUAL_LLM_ENABLED=true")
        if not SECONDARY_LLM_MODEL:
            errors.append("SECONDARY_LLM_MODEL required when DUAL_LLM_ENABLED=true")
        if not SECONDARY_LLM_PROVIDER:
            errors.append("SECONDARY_LLM_PROVIDER required when DUAL_LLM_ENABLED=true")
        if not SECONDARY_LLM_PROMPT:
            errors.append("SECONDARY_LLM_PROMPT required when DUAL_LLM_ENABLED=true")
        elif not os.path.exists(SECONDARY_LLM_PROMPT):
            errors.append(f"Secondary prompt file not found: {SECONDARY_LLM_PROMPT}")

    # Validate providers
    if not LLMClientFactory.validate_provider(DEFAULT_LLM_PROVIDER):
        errors.append(f"Unsupported primary LLM provider: {DEFAULT_LLM_PROVIDER}")

    if DUAL_LLM_ENABLED and SECONDARY_LLM_PROVIDER and not LLMClientFactory.validate_provider(SECONDARY_LLM_PROVIDER):
        errors.append(f"Unsupported secondary LLM provider: {SECONDARY_LLM_PROVIDER}")

    # Validate base_url requirements for providers that need it
    primary_provider = DEFAULT_LLM_PROVIDER.lower()
    if primary_provider in ("azure", "generic") and not DEFAULT_LLM_BASE_URL:
        errors.append(f"DEFAULT_LLM_BASE_URL is required for provider {DEFAULT_LLM_PROVIDER}")

    if DUAL_LLM_ENABLED and SECONDARY_LLM_PROVIDER:
        secondary_provider = SECONDARY_LLM_PROVIDER.lower()
        if secondary_provider in ("azure", "generic") and not SECONDARY_LLM_BASE_URL:
            errors.append(f"SECONDARY_LLM_BASE_URL is required for provider {SECONDARY_LLM_PROVIDER}")

    if errors:
        for error in errors:
            logger.error(f"❌ Configuration error: {error}")
        raise SystemExit(1)

    logger.info("✅ Configuration validation passed")
    if DUAL_LLM_ENABLED:
        logger.info(f"🔄 Dual LLM mode enabled: {DEFAULT_LLM_PROVIDER}/{DEFAULT_LLM_MODEL} + {SECONDARY_LLM_PROVIDER}/{SECONDARY_LLM_MODEL}")
    else:
        logger.info(f"🤖 Single LLM mode: {DEFAULT_LLM_PROVIDER}/{DEFAULT_LLM_MODEL}")


def initialize_llm_clients():
    """Initialize LLM clients after configuration validation."""
    global default_llm_client, secondary_llm_client

    # Create default LLM client
    default_llm_client = LLMClientFactory.create_client(
        provider=default_llm_config["provider"],
        api_key=default_llm_config["api_key"],
        base_url=default_llm_config["base_url"]
    )

    # Create secondary LLM client (if dual enabled)
    if DUAL_LLM_ENABLED and secondary_llm_config:
        secondary_llm_client = LLMClientFactory.create_client(
            provider=secondary_llm_config["provider"],
            api_key=secondary_llm_config["api_key"],
            base_url=secondary_llm_config["base_url"]
        )


# -------------------------------------------------------------------
# Matrix session helpers
# -------------------------------------------------------------------
async def store_session(client: AsyncClient, next_batch: str = None, log: bool = False):
    data = {
        "access_token": client.access_token,
        "device_id": client.device_id,
        "user_id": client.user_id,
    }
    if next_batch:
        data["next_batch"] = next_batch
    with open(SESSION_FILE, "w") as f:
        json.dump(data, f)
    if log:
        logger.info("💾 Session saved")


async def load_client() -> tuple[AsyncClient, str | None]:
    client = AsyncClient(MATRIX_HOMESERVER, MATRIX_USER)
    next_batch = None
    if os.path.exists(SESSION_FILE):
        try:
            with open(SESSION_FILE, "r") as f:
                session = json.load(f)
            client.access_token = session["access_token"]
            client.user_id = session["user_id"]
            client.device_id = session["device_id"]
            next_batch = session.get("next_batch")
            logger.info(f"🔑 Loaded existing session for {client.user_id}")
            if next_batch:
                logger.info(f"📍 Resuming from sync token: {next_batch[:20]}...")
        except Exception as e:
            logger.warning(f"⚠️ Failed to load session file: {e}")
    else:
        logger.info("🆕 No session found, logging in fresh.")
    return client, next_batch


async def login_if_needed(client: AsyncClient):
    if not client.access_token:
        logger.info("🔐 Logging in...")
        response = await client.login(MATRIX_PASSWORD)
        if isinstance(response, LoginResponse):
            await store_session(client, log=True)
            logger.info("✅ Logged in successfully")
        else:
            logger.error(f"❌ Login failed: {response}")
            raise SystemExit(1)
    else:
        logger.info("✅ Using existing session")


# -------------------------------------------------------------------
# Background job processing
# -------------------------------------------------------------------
async def process_jobs_background():
    """Background task that processes pending jobs."""
    consecutive_empty_polls = 0
    max_empty_polls = 10  # Increase sleep time after multiple empty polls
    
    logger.info("🔄 Job processor started")
    while True:
        try:
            # Quick check for pending jobs before expensive get_next_job call
            if not job_queue.has_pending_jobs():
                consecutive_empty_polls += 1
                if consecutive_empty_polls >= max_empty_polls:
                    await asyncio.sleep(10)
                else:
                    await asyncio.sleep(2)
                continue
                
            job = job_queue.get_next_job()
            if job:
                consecutive_empty_polls = 0  # Reset counter when we find work
                
                # Get file data from memory
                file_data = job_file_data.get(job.id)
                if file_data is None:
                    logger.error(f"❌ File data not found for job {job.id}")
                    job_queue.fail_job(job.id, "File data not found")
                    continue

                job.file_data = file_data

                try:
                    # Process PDF using new dual function
                    results = await process_pdf_dual_async(
                        job,
                        default_llm_config,
                        default_llm_client,
                        secondary_llm_config if DUAL_LLM_ENABLED else None,
                        secondary_llm_client if DUAL_LLM_ENABLED else None
                    )

                    # Mark job as completed (serialize dict to JSON)
                    job_queue.complete_job(job.id, json.dumps(results))

                    # Clean up file data from memory
                    if job.id in job_file_data:
                        del job_file_data[job.id]

                except Exception as e:
                    logger.error(f"❌ Error processing job {job.id}: {e}")
                    job_queue.fail_job(job.id, str(e))

                    # Clean up file data on failure too
                    if job.id in job_file_data:
                        del job_file_data[job.id]
            else:
                # No jobs to process - implement adaptive sleep
                consecutive_empty_polls += 1
                if consecutive_empty_polls >= max_empty_polls:
                    # After many empty polls, sleep longer to reduce CPU usage
                    await asyncio.sleep(10)
                else:
                    await asyncio.sleep(2)  # Increased from 1 to 2 seconds

        except Exception as e:
            logger.error(f"❌ Error in job processor: {e}")
            consecutive_empty_polls = 0
            await asyncio.sleep(10)  # Wait longer on error


async def send_results_background():
    """Background task that sends results for completed jobs."""
    while True:
        try:
            # Process completed jobs
            completed_jobs = job_queue.get_completed_jobs()
            for job in completed_jobs:
                try:
                    await send_job_result(job)
                    job_queue.remove_job(job.id)
                except Exception as e:
                    logger.error(f"❌ Error sending result for job {job.id}: {e}")
                    # Don't remove job on send failure - it will be retried

            # Also handle failed jobs
            failed_jobs = job_queue.get_failed_jobs()
            for job in failed_jobs:
                try:
                    await send_job_failure(job)
                    job_queue.remove_job(job.id)
                except Exception as e:
                    logger.error(
                        f"❌ Error sending failure message for job {job.id}: {e}"
                    )
                    # Don't remove job on send failure - it will be retried

            # Sleep longer if no jobs were processed to reduce resource usage
            if not completed_jobs and not failed_jobs:
                await asyncio.sleep(COMPLETED_JOB_POLL_SECONDS * 2)  # Double the sleep time
            else:
                await asyncio.sleep(COMPLETED_JOB_POLL_SECONDS)

        except Exception as e:
            logger.error(f"❌ Error in result sender: {e}")
            await asyncio.sleep(10)  # Wait longer on error


async def send_job_result(job: Job):
    """Send job results - single or dual based on configuration."""
    # Deserialize JSON result back to dict if needed
    if isinstance(job.result, str):
        try:
            results = json.loads(job.result)
        except json.JSONDecodeError:
            # Fallback for legacy string results
            results = job.result
    else:
        results = job.result
    
    try:
        if isinstance(results, dict) and "primary" in results:
            # Dict-based results (single or dual LLM)
            has_secondary = "secondary" in results
            logger.info(f"📤 Sending {'dual' if has_secondary else 'single'} results for {job.filename}")
            
            # Send primary analysis
            if "primary" in results:
                await matrix_client.room_send(
                    room_id=job.room_id,
                    message_type="m.room.message",
                    content={
                        "msgtype": "m.text",
                        "body": f"🤖 **Análise Primária**\n\n{results['primary']}",
                        "format": "org.matrix.custom.html",
                        "formatted_body": f"🤖 <strong>Análise Primária</strong><br/><br/>{results['primary'].replace(chr(10), '<br/>')}",
                        "m.relates_to": {"m.in_reply_to": {"event_id": job.event_id}},
                    },
                )
                logger.info(f"✅ Primary analysis sent for {job.filename}")
            
            # Small delay between messages
            await asyncio.sleep(0.5)
            
            # Send secondary analysis
            if "secondary" in results:
                await matrix_client.room_send(
                    room_id=job.room_id,
                    message_type="m.room.message",
                    content={
                        "msgtype": "m.text",
                        "body": f"🔍 **Análise Secundária**\n\n{results['secondary']}",
                        "format": "org.matrix.custom.html",
                        "formatted_body": f"🔍 <strong>Análise Secundária</strong><br/><br/>{results['secondary'].replace(chr(10), '<br/>')}",
                        "m.relates_to": {"m.in_reply_to": {"event_id": job.event_id}},
                    },
                )
                logger.info(f"✅ Secondary analysis sent for {job.filename}")
            
        else:
            # Single result or legacy format
            result_text = results.get("primary", results) if isinstance(results, dict) else results
            
            await matrix_client.room_send(
                room_id=job.room_id,
                message_type="m.room.message",
                content={
                    "msgtype": "m.text",
                    "body": f"{result_text}",
                    "m.relates_to": {"m.in_reply_to": {"event_id": job.event_id}},
                },
            )
            logger.info(f"✅ Single analysis sent for {job.filename}")
    
    except Exception as e:
        logger.error(f"❌ Error sending result for {job.filename}: {e}")
        raise


async def send_job_failure(job: Job):
    """Send a failure message back to the Matrix room."""
    await matrix_client.room_send(
        room_id=job.room_id,
        message_type="m.room.message",
        content={
            "msgtype": "m.text",
            "body": f"❌ Falha ao analisar `{job.filename}`: {job.error_message}",
            "m.relates_to": {"m.in_reply_to": {"event_id": job.event_id}},
        },
    )
    logger.error(f"💥 Failure message for {job.filename} sent to Matrix room")


async def cleanup_jobs_periodic():
    """Periodic cleanup of old completed jobs."""
    while True:
        try:
            await asyncio.sleep(3600)  # Run every hour
            deleted_count = job_queue.cleanup_old_jobs(JOB_CLEANUP_HOURS)
            if deleted_count > 0:
                logger.info(f"🧹 Cleaned up {deleted_count} old jobs")
            
            # Also cleanup orphaned file data that might be left in memory
            try:
                stats = job_queue.get_queue_stats()
                # If we have more file data than active jobs, clean up
                if len(job_file_data) > sum(stats.values()):
                    # Get all current job IDs from database
                    # For now, just log if we detect orphaned data
                    if len(job_file_data) > 10:  # Arbitrary threshold
                        logger.warning(f"⚠️ {len(job_file_data)} files in memory, queue has {sum(stats.values())} jobs")
            except Exception as cleanup_error:
                logger.warning(f"⚠️ Error during memory cleanup check: {cleanup_error}")
                
        except Exception as e:
            logger.error(f"❌ Error in periodic cleanup: {e}")
            await asyncio.sleep(600)  # Wait 10 minutes before retrying on error


# -------------------------------------------------------------------
# Event callback
# -------------------------------------------------------------------
async def message_callback(room: MatrixRoom, event: RoomMessageMedia):
    """Triggered when a file message event occurs in the room."""
    # Only process events from the monitored room
    if room.room_id != MATRIX_ROOM_ID:
        return

    # Only process events with file URLs
    if not hasattr(event, "url") or not event.url:
        return

    # Only process PDF files
    if not event.body.lower().endswith(".pdf"):
        return

    logger.info(f"📥 Detected PDF upload: {event.body}")

    # Download PDF immediately
    download_response = await matrix_client.download(event.url)

    if not download_response or not hasattr(download_response, "body"):
        logger.warning("⚠️ Failed to download PDF")
        await matrix_client.room_send(
            room_id=MATRIX_ROOM_ID,
            message_type="m.room.message",
            content={
                "msgtype": "m.text",
                "body": f"❌ Falha ao baixar `{event.body}`",
                "m.relates_to": {"m.in_reply_to": {"event_id": event.event_id}},
            },
        )
        return

    file_data = download_response.body
    logger.info(f"✅ Downloaded PDF ({len(file_data)} bytes)")

    # Create job and add to queue
    job = Job.create(
        filename=event.body,
        file_url=event.url,
        event_id=event.event_id,
        room_id=room.room_id,
        file_data=file_data,
    )

    # Store file data in memory (separate from database)
    job_file_data[job.id] = file_data

    # Add job to queue
    if job_queue.add_job(job):
        # Send immediate processing message
        await matrix_client.room_send(
            room_id=MATRIX_ROOM_ID,
            message_type="m.room.message",
            content={
                "msgtype": "m.text",
                "body": f"🧠 Processando `{event.body}`...",
                "m.relates_to": {"m.in_reply_to": {"event_id": event.event_id}},
            },
        )
        logger.info(f"✅ Queued job for {event.body}")
    else:
        # Failed to add job to queue
        await matrix_client.room_send(
            room_id=MATRIX_ROOM_ID,
            message_type="m.room.message",
            content={
                "msgtype": "m.text",
                "body": f"❌ Falha ao processar `{event.body}` - erro interno",
                "m.relates_to": {"m.in_reply_to": {"event_id": event.event_id}},
            },
        )
        # Clean up file data
        if job.id in job_file_data:
            del job_file_data[job.id]


# -------------------------------------------------------------------
# Sync callback to persist sync token
# -------------------------------------------------------------------
async def sync_callback(response):
    """Save the sync token after each sync."""
    if hasattr(response, "next_batch"):
        await store_session(matrix_client, response.next_batch)


# -------------------------------------------------------------------
# Main
# -------------------------------------------------------------------
async def main():
    global matrix_client, job_queue, pdf_executor

    logger.info("🚀 Starting Matrix PDF Summarizer Bot with Concurrent Processing")
    logger.info(f"🏠 Homeserver: {MATRIX_HOMESERVER}")
    logger.info(f"👤 User: {MATRIX_USER}")
    logger.info(f"📍 Room ID: {MATRIX_ROOM_ID}")
    logger.info(f"⚙️ Max worker threads: {MAX_WORKER_THREADS}")

    # Validate configuration and initialize LLM clients
    validate_configuration()
    initialize_llm_clients()

    # Initialize job queue
    job_queue = JobQueue(db_path=JOB_DB_PATH, max_retries=MAX_JOB_RETRIES)
    logger.info(f"📊 Job queue initialized: {JOB_DB_PATH}")

    # Initialize thread pool for PDF processing
    pdf_executor = ThreadPoolExecutor(max_workers=MAX_WORKER_THREADS)
    logger.info(f"🔧 Thread pool executor created with {MAX_WORKER_THREADS} workers")

    matrix_client, next_batch = await load_client()
    await login_if_needed(matrix_client)

    # Set the sync token if we have one
    if next_batch:
        matrix_client.next_batch = next_batch
        logger.info("✅ Resuming from last sync position")
    else:
        logger.info("⚠️ No sync token found, processing from beginning")

    # Register callbacks
    matrix_client.add_event_callback(message_callback, RoomMessageMedia)
    matrix_client.add_response_callback(sync_callback, SyncResponse)

    # Register user interaction callbacks
    matrix_client.add_event_callback(
        lambda room, event: dm_callback(room, event, matrix_client, MATRIX_ROOM_ID),
        RoomMessageText,
    )
    matrix_client.add_event_callback(
        lambda room, event: mention_callback(
            room, event, matrix_client, MATRIX_ROOM_ID
        ),
        RoomMessageText,
    )
    matrix_client.add_event_callback(
        lambda room, event: invite_callback(room, event, matrix_client, MATRIX_ROOM_ID),
        InviteMemberEvent,
    )

    # Start background tasks with exception handling
    logger.info("🔄 Starting background tasks...")
    
    # Start background tasks directly (they have their own exception handling)
    job_processor_task = asyncio.create_task(process_jobs_background())
    result_sender_task = asyncio.create_task(send_results_background())
    cleanup_task = asyncio.create_task(cleanup_jobs_periodic())

    logger.info("👀 Listening for PDF uploads...")

    # Monitor background tasks health
    async def monitor_tasks():
        """Monitor background tasks and log their health."""
        while True:
            await asyncio.sleep(60)  # Check every minute
            
            tasks_status = {
                "job_processor": not job_processor_task.done(),
                "result_sender": not result_sender_task.done(), 
                "cleanup": not cleanup_task.done()
            }
            
            # Log if any task is done (which shouldn't happen)
            for name, is_running in tasks_status.items():
                if not is_running:
                    logger.error(f"❌ Background task {name} has stopped!")
                    if getattr(globals().get(f"{name}_task"), 'exception', None):
                        exc = getattr(globals().get(f"{name}_task"), 'exception')()
                        if exc:
                            logger.error(f"❌ {name} exception: {exc}")
            
            # Log task health every 5 minutes
            if any(not status for status in tasks_status.values()):
                logger.warning(f"⚠️ Task health: {tasks_status}")
    
    monitor_task = asyncio.create_task(monitor_tasks())
    logger.info("🔍 Background task monitor started")

    try:
        await matrix_client.sync_forever(timeout=30000, since=next_batch)
    except (KeyboardInterrupt, asyncio.CancelledError):
        logger.info("👋 Shutting down...")
    except Exception as e:
        logger.error(f"❌ Unexpected error: {e}")
        logger.exception(e)
    finally:
        # Cancel background tasks
        logger.info("⏹️ Stopping background tasks...")
        job_processor_task.cancel()
        result_sender_task.cancel()
        cleanup_task.cancel()
        monitor_task.cancel()

        # Wait for tasks to finish with timeout
        try:
            await asyncio.wait_for(
                asyncio.gather(
                    job_processor_task,
                    result_sender_task,
                    cleanup_task,
                    monitor_task,
                    return_exceptions=True,
                ),
                timeout=5.0,
            )
        except asyncio.TimeoutError:
            logger.warning("⚠️ Background tasks didn't stop within timeout")

        # Shutdown thread pool with timeout to prevent hanging
        if pdf_executor:
            logger.info("🔧 Shutting down thread pool executor...")
            try:
                pdf_executor.shutdown(wait=True, cancel_futures=False)
            except Exception as e:
                logger.warning(f"⚠️ Error shutting down thread pool: {e}")
                # Force shutdown if normal shutdown fails
                try:
                    pdf_executor.shutdown(wait=False, cancel_futures=True)
                except Exception:
                    pass

        # Save the current sync token before closing
        if matrix_client.next_batch:
            await store_session(matrix_client, matrix_client.next_batch, log=True)
        await matrix_client.close()
        logger.info("✅ Bot stopped cleanly")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        # Already handled in main(), just exit cleanly
        pass
