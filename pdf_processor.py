import io
import logging
from collections import Counter
from pypdf import PdfReader
from openai import AsyncOpenAI
from job_queue import Job
import re

logger = logging.getLogger("matrix-pdf-bot.pdf_processor")


def remove_watermark(text: str) -> str:
    """Remove repeating 5-digit watermark sequences from text."""
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


async def summarize_text(
    text: str, instructions: str, llm_client: AsyncOpenAI, llm_config: dict
) -> str:
    """Use LLM to summarize a given text with instructions."""
    # Build API call parameters
    api_params = {
        "model": llm_config["model"],
        "messages": [
            {"role": "system", "content": instructions},
            {"role": "user", "content": text},
        ],
    }

    # Add optional parameters if configured
    if llm_config.get("temperature") is not None:
        api_params["temperature"] = llm_config["temperature"]
    if llm_config.get("max_tokens") is not None:
        api_params["max_tokens"] = llm_config["max_tokens"]

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


def process_pdf_job(
    job: Job, prompt_file: str, llm_client: AsyncOpenAI, llm_config: dict
) -> str:
    """
    Synchronous PDF processing function for use in thread pool.
    This function is designed to run in a separate thread.
    """
    try:
        logger.info(f"🔄 Processing PDF job {job.id}: {job.filename}")

        # Extract text from PDF
        text = extract_pdf_text(job.file_data)
        logger.info(f"📄 Extracted {len(text)} characters from {job.filename}")

        if not text:
            logger.warning(f"⚠️ No text extracted from {job.filename}")
            return "⚠️ No text could be extracted from this PDF."

        # Remove watermark sequences
        cleaned_text = remove_watermark(text)

        # Load instructions from external prompt file
        instructions = load_prompt(prompt_file)

        logger.info(f"🤖 Sending {job.filename} to LLM for summarization...")

        # Note: This is a sync wrapper around async function for thread execution
        # The actual async call will be handled by the calling code
        return cleaned_text, instructions

    except Exception as e:
        logger.error(f"❌ Error processing PDF job {job.id}: {e}")
        raise


async def process_pdf_async(
    job: Job, prompt_file: str, llm_client: AsyncOpenAI, llm_config: dict
) -> str:
    """
    Async version of PDF processing that handles the LLM call.
    """
    try:
        logger.info(f"🔄 Processing PDF job {job.id}: {job.filename}")

        # Extract text from PDF
        text = extract_pdf_text(job.file_data)
        logger.info(f"📄 Extracted {len(text)} characters from {job.filename}")

        if not text:
            logger.warning(f"⚠️ No text extracted from {job.filename}")
            return "⚠️ No text could be extracted from this PDF."

        # Remove watermark sequences
        cleaned_text = remove_watermark(text)

        # Load instructions from external prompt file
        instructions = load_prompt(prompt_file)

        logger.info(f"🤖 Sending {job.filename} to LLM for summarization...")
        summary = await summarize_text(
            cleaned_text, instructions, llm_client, llm_config
        )
        logger.info(
            f"✅ Summary generated for {job.filename} ({len(summary)} characters)"
        )

        return summary

    except Exception as e:
        logger.error(f"❌ Error processing PDF job {job.id}: {e}")
        raise
