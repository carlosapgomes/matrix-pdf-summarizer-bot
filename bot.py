import asyncio
import json
import logging
import os
from concurrent.futures import ThreadPoolExecutor
from openai import AsyncOpenAI
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
from pdf_processor import process_pdf_async

# -------------------------------------------------------------------
# Load environment variables
# -------------------------------------------------------------------
load_dotenv()

MATRIX_HOMESERVER = os.getenv("MATRIX_HOMESERVER")
MATRIX_USER = os.getenv("MATRIX_USER")
MATRIX_PASSWORD = os.getenv("MATRIX_PASSWORD")
MATRIX_ROOM_ID = os.getenv("MATRIX_ROOM_ID")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
SESSION_FILE = os.getenv("SESSION_FILE", "session.json")
PROMPT_FILE = os.getenv("PROMPT_FILE", "prompts/medical_triage.txt")

# LLM Configuration
LLM_MODEL = os.getenv("LLM_MODEL", "gpt-5-mini")
LLM_BASE_URL = os.getenv("LLM_BASE_URL", None)  # Optional: for OpenAI-compatible APIs
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

# Initialize OpenAI client with optional base_url for compatible APIs
llm_client_kwargs = {"api_key": OPENAI_API_KEY}
if LLM_BASE_URL:
    llm_client_kwargs["base_url"] = LLM_BASE_URL
llm_client = AsyncOpenAI(**llm_client_kwargs)

# LLM configuration for PDF processor
llm_config = {
    "model": LLM_MODEL,
    "temperature": LLM_TEMPERATURE,
    "max_tokens": LLM_MAX_TOKENS,
}

# In-memory storage for job file data (since SQLite doesn't store blobs efficiently)
job_file_data = {}


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
    while True:
        try:
            job = job_queue.get_next_job()
            if job:
                # Get file data from memory
                file_data = job_file_data.get(job.id)
                if file_data is None:
                    logger.error(f"❌ File data not found for job {job.id}")
                    job_queue.fail_job(job.id, "File data not found")
                    continue

                job.file_data = file_data

                try:
                    # Process PDF using thread pool
                    summary = await process_pdf_async(
                        job, PROMPT_FILE, llm_client, llm_config
                    )

                    # Mark job as completed
                    job_queue.complete_job(job.id, summary)

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
                # No jobs to process, wait a bit
                await asyncio.sleep(1)

        except Exception as e:
            logger.error(f"❌ Error in job processor: {e}")
            await asyncio.sleep(5)  # Wait longer on error


async def send_results_background():
    """Background task that sends results for completed jobs."""
    while True:
        try:
            completed_jobs = job_queue.get_completed_jobs()
            for job in completed_jobs:
                try:
                    await send_job_result(job)
                    job_queue.remove_job(job.id)
                except Exception as e:
                    logger.error(f"❌ Error sending result for job {job.id}: {e}")

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

            await asyncio.sleep(COMPLETED_JOB_POLL_SECONDS)

        except Exception as e:
            logger.error(f"❌ Error in result sender: {e}")
            await asyncio.sleep(5)  # Wait longer on error


async def send_job_result(job: Job):
    """Send the job result back to the Matrix room."""
    await matrix_client.room_send(
        room_id=job.room_id,
        message_type="m.room.message",
        content={
            "msgtype": "m.text",
            "body": f"{job.result}",
            "m.relates_to": {"m.in_reply_to": {"event_id": job.event_id}},
        },
    )
    logger.info(f"✅ Summary for {job.filename} sent to Matrix room")


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
        except Exception as e:
            logger.error(f"❌ Error in periodic cleanup: {e}")


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

    # Start background tasks
    logger.info("🔄 Starting background tasks...")
    job_processor_task = asyncio.create_task(process_jobs_background())
    result_sender_task = asyncio.create_task(send_results_background())
    cleanup_task = asyncio.create_task(cleanup_jobs_periodic())

    logger.info("👀 Listening for PDF uploads...")

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

        # Wait for tasks to finish with timeout
        try:
            await asyncio.wait_for(
                asyncio.gather(
                    job_processor_task,
                    result_sender_task,
                    cleanup_task,
                    return_exceptions=True,
                ),
                timeout=5.0,
            )
        except asyncio.TimeoutError:
            logger.warning("⚠️ Background tasks didn't stop within timeout")

        # Shutdown thread pool
        if pdf_executor:
            logger.info("🔧 Shutting down thread pool executor...")
            pdf_executor.shutdown(wait=True, cancel_futures=False)

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
