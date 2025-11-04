import asyncio
import io
import json
import logging
import os
from pypdf import PdfReader
from openai import AsyncOpenAI
from nio import (
    AsyncClient,
    MatrixRoom,
    RoomMessageMedia,
    LoginResponse,
    SyncResponse,
)
from dotenv import load_dotenv

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
llm_client = AsyncOpenAI(api_key=OPENAI_API_KEY)


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
        logger.info(f"💾 Session saved")


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
    response = await llm_client.chat.completions.create(
        model="gpt-5-mini",
        messages=[
            {"role": "system", "content": instructions},
            {"role": "user", "content": text[:15000]},  # truncate if huge
        ],
    )
    return response.choices[0].message.content.strip()


async def process_pdf(file_bytes: bytes, filename: str) -> str:
    """Full pipeline: extract → clean → summarize → return summary text."""
    text = extract_pdf_text(file_bytes)
    logger.info(f"📄 Extracted {len(text)} characters from PDF")

    if not text:
        logger.warning(f"⚠️ No text extracted from {filename}")

    # Remove watermark sequences
    cleaned_text = remove_watermark(text)

    instructions = (
        "It is a medical reference report in brazilian portuguese for a patient with vascular disease."
        "You are a medical vascular specialist whose job is to summarize the patient's clinical status and the main reasons for referencing him/her AND set a triage opinion for the patient to be accepted or not in your current hospital."
        "Your current hospital have the following acceptance criteria:"
        "- patients that have infected ulcers that need debridement and or infection treatment"
        "- patients that need minor or major amputations"
        "- patients that have, at least, a palpable femural pulse on the affected limb"
        "- patients that have a creatinine level below or equal to 1.4 mg/dL."
        "- patients that do not need dialysis"
        "- patients that do not need major vascular surgery"
        "- patients that do not need limb revascularization"
        "- patients that do not need carotid or aneurysm surgery"
        "- patients that do not need endovascular procedures"
        "The output should be a in markdown format written in Brazilian Portuguese, but without triple backticks fencing, just the markdown formatted text."
        "Put your acceptance recommendation in the top of the text, followed by your acceptance/denying reason, followed by the patient's clinical summary. Use the following text for the acceptance: 'Recomendação:  ✅ *Aceitar*' and the following text for the denying recommendation: 'Recomendação: ❌ *Recusar*'"
        "Do not use utf emoticons in the clinical summary."
        "Do your best to not include any sensitive information in the output that could identify the patient."
    )
    # instructions = (
    #     "You are a medical doctor especialized in vascular surgery."
    #     "Your job here is to analyse and summarize patients report transfer requests."
    #     "You should summarize the report and organize its content cronologically, identifying the most important reason for the request."
    #     "Summarize the content of the document clearly and concisely. "
    #     "Ignore watermarks, headers, or footers."
    #     "All your output should be written in Brazilian Portuguese"
    # )

    logger.info(f"🤖 Sending to LLM for summarization...")
    summary = await summarize_text(cleaned_text, instructions)
    logger.info(f"✅ Summary generated ({len(summary)} characters)")

    return summary


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

    download_response = await matrix_client.download(event.url)

    if not download_response or not hasattr(download_response, "body"):
        logger.warning(f"⚠️ Failed to download PDF")
        return

    file_data = download_response.body
    logger.info(f"✅ Downloaded PDF ({len(file_data)} bytes)")

    await matrix_client.room_send(
        room_id=MATRIX_ROOM_ID,
        message_type="m.room.message",
        content={
            "msgtype": "m.text",
            "body": f"🧠 Processing `{event.body}`...",
            "m.relates_to": {"m.in_reply_to": {"event_id": event.event_id}},
        },
    )

    try:
        summary = await process_pdf(file_data, event.body)
        await matrix_client.room_send(
            room_id=MATRIX_ROOM_ID,
            message_type="m.room.message",
            content={
                "msgtype": "m.text",
                "body": f"📘 **Summary of `{event.body}`:**\n\n{summary}",
                "m.relates_to": {"m.in_reply_to": {"event_id": event.event_id}},
            },
        )
        logger.info(f"✅ Summary for {event.body} sent to Matrix room.")
    except Exception as e:
        logger.exception("Error summarizing PDF")
        await matrix_client.room_send(
            room_id=MATRIX_ROOM_ID,
            message_type="m.room.message",
            content={
                "msgtype": "m.text",
                "body": f"❌ Failed to summarize `{event.body}`: {e}",
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

    # Set the sync token if we have one
    if next_batch:
        matrix_client.next_batch = next_batch
        logger.info("✅ Resuming from last sync position")
    else:
        logger.info("⚠️ No sync token found, processing from beginning")

    # Register callbacks
    matrix_client.add_event_callback(message_callback, RoomMessageMedia)
    matrix_client.add_response_callback(sync_callback, SyncResponse)

    logger.info(f"👀 Listening for PDF uploads...")

    try:
        await matrix_client.sync_forever(timeout=30000, since=next_batch)
    except (KeyboardInterrupt, asyncio.CancelledError):
        logger.info("👋 Shutting down...")
    except Exception as e:
        logger.error(f"❌ Unexpected error: {e}")
        logger.exception(e)
    finally:
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
