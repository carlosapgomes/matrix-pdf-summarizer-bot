import asyncio
import io
import json
import logging
import os
import time
from dataclasses import dataclass
from pypdf import PdfReader
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


# -------------------------------------------------------------------
# PDF Job Structure
# -------------------------------------------------------------------
@dataclass
class PDFJob:
    room: MatrixRoom
    event: RoomMessageMedia
    file_data: bytes
    filename: str
    enqueued_at: float


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

# Initialize OpenAI client with optional base_url for compatible APIs
llm_client_kwargs = {"api_key": OPENAI_API_KEY}
if LLM_BASE_URL:
    llm_client_kwargs["base_url"] = LLM_BASE_URL
llm_client = AsyncOpenAI(**llm_client_kwargs)

# PDF Processing Queue and Workers
pdf_queue: asyncio.Queue = None  # Initialized in main()
worker_tasks: list[asyncio.Task] = []  # Track worker tasks


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
# PDF → Text → LLM summary pipeline
# -------------------------------------------------------------------
def remove_watermark(text: str) -> str:
    """Remove repeating 5-digit watermark sequences from text."""
    import re
    from collections import Counter

    # Find all 5-digit sequences in the text
    five_digit_pattern = re.compile(r"\b\d{5}\b")
    matches = five_digit_pattern.findall(text)

    if not matches:
        return text

    # Count occurrences of each 5-digit sequence
    counter = Counter(matches)

    # Find the most common sequence (likely the watermark)
    if counter:
        most_common_seq, count = counter.most_common(1)[0]

        # Only remove if it appears multiple times (likely a watermark)
        if count >= 3:
            logger.info(
                f"🧹 Removing watermark '{most_common_seq}' ({count} occurrences)"
            )

            # Remove all instances of the watermark sequence
            # Use word boundary to avoid removing legitimate numbers
            watermark_pattern = re.compile(
                r"\b" + re.escape(most_common_seq) + r"\b\s*"
            )
            cleaned_text = watermark_pattern.sub("", text)
            return cleaned_text

    return text


def extract_pdf_text(file_bytes: bytes) -> str:
    """Extract text from a pure (non-scanned) PDF."""
    try:
        reader = PdfReader(io.BytesIO(file_bytes))
        text = "\n".join(page.extract_text() or "" for page in reader.pages)
        return text.strip()
    except Exception as e:
        logger.error(f"❌ Error extracting PDF text: {e}")
        raise


async def summarize_text(text: str, instructions: str) -> str:
    """Use LLM to summarize a given text with instructions."""
    # Build API call parameters
    api_params = {
        "model": LLM_MODEL,
        "messages": [
            {"role": "system", "content": instructions},
            {"role": "user", "content": text},  # GPT-5-mini can handle large inputs
        ],
    }

    # Add optional parameters if configured
    if LLM_TEMPERATURE is not None:
        api_params["temperature"] = LLM_TEMPERATURE
    if LLM_MAX_TOKENS is not None:
        api_params["max_tokens"] = LLM_MAX_TOKENS

    response = await llm_client.chat.completions.create(**api_params)
    return response.choices[0].message.content.strip()


def load_prompt(prompt_file_path: str) -> str:
    """Load prompt instructions from a file."""
    try:
        with open(prompt_file_path, "r", encoding="utf-8") as f:
            prompt = f.read().strip()
        logger.info(f"📝 Loaded prompt from {prompt_file_path}")
        return prompt
    except FileNotFoundError:
        logger.error(f"❌ Prompt file not found: {prompt_file_path}")
        raise
    except Exception as e:
        logger.error(f"❌ Error loading prompt file: {e}")
        raise


async def process_pdf(file_bytes: bytes, filename: str) -> str:
    """Full pipeline: extract → clean → summarize → return summary text."""
    text = extract_pdf_text(file_bytes)
    logger.info(f"📄 Extracted {len(text)} characters from PDF")

    if not text:
        logger.warning(f"⚠️ No text extracted from {filename}")

    # Remove watermark sequences
    cleaned_text = remove_watermark(text)

    # Load instructions from external prompt file
    instructions = load_prompt(PROMPT_FILE)

    logger.info("🤖 Sending to LLM for summarization...")
    summary = await summarize_text(cleaned_text, instructions)
    logger.info(f"✅ Summary generated ({len(summary)} characters)")

    return summary


# -------------------------------------------------------------------
# PDF Worker Function
# -------------------------------------------------------------------
async def pdf_worker(worker_id: int, queue: asyncio.Queue):
    """Worker that processes PDFs from the queue."""
    logger.info(f"👷 Worker {worker_id} started")

    while True:
        try:
            job = await queue.get()
            start_time = time.time()
            wait_time = start_time - job.enqueued_at

            logger.info(
                f"👷 Worker {worker_id} processing {job.filename} (waited {wait_time:.1f}s)"
            )

            # Send "processing" message to Matrix
            await matrix_client.room_send(
                room_id=job.room.room_id,
                message_type="m.room.message",
                content={
                    "msgtype": "m.text",
                    "body": f"🧠 Processando `{job.filename}`...",
                    "m.relates_to": {"m.in_reply_to": {"event_id": job.event.event_id}},
                },
            )

            try:
                # Process the PDF
                summary = await process_pdf(job.file_data, job.filename)

                # Send summary to Matrix
                await matrix_client.room_send(
                    room_id=job.room.room_id,
                    message_type="m.room.message",
                    content={
                        "msgtype": "m.text",
                        "body": f"{summary}",
                        "m.relates_to": {
                            "m.in_reply_to": {"event_id": job.event.event_id}
                        },
                    },
                )

                processing_time = time.time() - start_time
                logger.info(
                    f"✅ Worker {worker_id} completed {job.filename} in {processing_time:.1f}s"
                )

            except Exception as e:
                logger.exception(
                    f"❌ Worker {worker_id} failed to process {job.filename}: {e}"
                )
                # Send error message to Matrix
                await matrix_client.room_send(
                    room_id=job.room.room_id,
                    message_type="m.room.message",
                    content={
                        "msgtype": "m.text",
                        "body": f"❌ Falha ao analisar `{job.filename}`: {e}",
                        "m.relates_to": {
                            "m.in_reply_to": {"event_id": job.event.event_id}
                        },
                    },
                )

        except asyncio.CancelledError:
            logger.info(f"👷 Worker {worker_id} cancelled")
            break
        except Exception as e:
            logger.exception(f"❌ Worker {worker_id} unexpected error: {e}")
        finally:
            queue.task_done()


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

    try:
        download_response = await matrix_client.download(event.url)

        if not download_response or not hasattr(download_response, "body"):
            logger.warning("⚠️ Failed to download PDF")
            return

        file_data = download_response.body
        logger.info(f"✅ Downloaded PDF ({len(file_data)} bytes)")

        # Create job and enqueue
        job = PDFJob(
            room=room,
            event=event,
            file_data=file_data,
            filename=event.body,
            enqueued_at=time.time(),
        )

        await pdf_queue.put(job)
        logger.info(f"📥 Queued {event.body} (queue size: {pdf_queue.qsize()})")

        # Optional: acknowledge receipt
        await matrix_client.room_send(
            room_id=MATRIX_ROOM_ID,
            message_type="m.room.message",
            content={
                "msgtype": "m.text",
                "body": f"📋 `{event.body}` adicionado à fila de processamento",
                "m.relates_to": {"m.in_reply_to": {"event_id": event.event_id}},
            },
        )
    except Exception as e:
        logger.exception(f"❌ Error handling PDF upload {event.body}: {e}")
        await matrix_client.room_send(
            room_id=MATRIX_ROOM_ID,
            message_type="m.room.message",
            content={
                "msgtype": "m.text",
                "body": f"❌ Erro ao processar `{event.body}`: {e}",
                "m.relates_to": {"m.in_reply_to": {"event_id": event.event_id}},
            },
        )


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
    global matrix_client

    logger.info("🚀 Starting Matrix PDF Summarizer Bot")
    logger.info(f"🏠 Homeserver: {MATRIX_HOMESERVER}")
    logger.info(f"👤 User: {MATRIX_USER}")
    logger.info(f"📍 Room ID: {MATRIX_ROOM_ID}")

    matrix_client, next_batch = await load_client()
    await login_if_needed(matrix_client)

    # Initialize PDF processing queue and workers
    global pdf_queue, worker_tasks
    max_workers = int(os.getenv("MAX_CONCURRENT_WORKERS", "3"))
    queue_max_size = int(os.getenv("QUEUE_MAX_SIZE", "100"))

    pdf_queue = asyncio.Queue(maxsize=queue_max_size)
    logger.info(f"📦 Created job queue (max size: {queue_max_size})")

    # Spawn worker tasks
    worker_tasks = [
        asyncio.create_task(pdf_worker(i, pdf_queue)) for i in range(max_workers)
    ]
    logger.info(f"👷 Spawned {max_workers} PDF processing workers")

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

    logger.info("👀 Listening for PDF uploads...")

    try:
        await matrix_client.sync_forever(timeout=30000, since=next_batch)
    except (KeyboardInterrupt, asyncio.CancelledError):
        logger.info("👋 Shutting down...")
    except Exception as e:
        logger.error(f"❌ Unexpected error: {e}")
        logger.exception(e)
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
