import io
import logging
import asyncio
from collections import Counter
from pypdf import PdfReader
from openai import AsyncOpenAI
from job_queue import Job
from typing import Dict, Any, Optional
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


async def summarize_text_with_provider(
    text: str, 
    instructions: str, 
    client: Any, 
    config: Dict[str, Any],
    provider_name: str
) -> str:
    """
    Summarize text using a specific LLM provider/client.
    
    Args:
        text: Text content to analyze
        instructions: Prompt instructions
        client: LLM client instance
        config: LLM configuration parameters
        provider_name: Provider identifier for logging
        
    Returns:
        Analysis result string
        
    Raises:
        Exception: If LLM API call fails
    """
    try:
        provider = (config.get("provider") or "unknown").lower()
        model = config.get("model", "unknown")
        
        logger.info(f"🧠 {provider_name} analysis starting ({provider}/{model})")
        
        # Build API parameters for OpenAI-compatible APIs
        api_params = {
            "model": model,
            "messages": [
                {"role": "system", "content": instructions},
                {"role": "user", "content": text},
            ],
        }
        
        # Add optional parameters
        if config.get("temperature") is not None:
            api_params["temperature"] = config["temperature"]
        if config.get("max_tokens") is not None:
            api_params["max_tokens"] = config["max_tokens"]
        
        # Provider-specific API calls
        if provider == "anthropic":
            # Anthropic API uses system parameter and different structure
            response = await client.messages.create(
                model=model,
                max_tokens=config.get("max_tokens", 4000),
                temperature=config.get("temperature", 0.7),
                system=instructions,
                messages=[{"role": "user", "content": text}]
            )
            result = response.content[0].text.strip()
        else:
            # OpenAI-compatible APIs
            response = await client.chat.completions.create(**api_params)
            result = response.choices[0].message.content.strip()
        
        logger.info(f"✅ {provider_name} analysis completed")
        return result
        
    except Exception as e:
        logger.error(f"❌ {provider_name} analysis failed: {e}")
        raise Exception(f"{provider_name} analysis error: {str(e)}")


async def process_pdf_dual_async(
    job: Job,
    primary_config: Dict[str, Any],
    primary_client: Any,
    secondary_config: Optional[Dict[str, Any]] = None,
    secondary_client: Optional[Any] = None
) -> Dict[str, str]:
    """
    Process PDF with one or two LLMs based on configuration.
    
    Args:
        job: PDF processing job
        primary_config: Primary LLM configuration
        primary_client: Primary LLM client instance
        secondary_config: Secondary LLM configuration (optional)
        secondary_client: Secondary LLM client instance (optional)
        
    Returns:
        Dictionary with analysis results:
        - Single LLM: {"primary": analysis}
        - Dual LLM: {"primary": analysis1, "secondary": analysis2}
        
    Raises:
        Exception: If PDF processing or LLM calls fail
    """
    try:
        logger.info(f"🔄 Processing PDF job {job.id}: {job.filename}")
        
        # Phase 1: Extract and preprocess text (common for both LLMs)
        text = extract_pdf_text(job.file_data)
        logger.info(f"📄 Extracted {len(text)} characters from {job.filename}")
        
        if not text:
            logger.warning(f"⚠️ No text extracted from {job.filename}")
            return {"primary": "⚠️ No text could be extracted from this PDF."}
        
        cleaned_text = remove_watermark(text)
        logger.info(f"🧹 Text cleaned for {job.filename}")
        
        # Phase 2: Prepare analysis tasks
        results = {}
        analysis_tasks = []
        
        # Primary LLM analysis
        primary_prompt = load_prompt(primary_config["prompt_file"])
        primary_task = summarize_text_with_provider(
            cleaned_text, 
            primary_prompt, 
            primary_client, 
            primary_config,
            "primary"
        )
        analysis_tasks.append(("primary", primary_task))
        
        # Secondary LLM analysis (if configured)
        if secondary_config and secondary_client:
            secondary_prompt = load_prompt(secondary_config["prompt_file"])
            secondary_task = summarize_text_with_provider(
                cleaned_text, 
                secondary_prompt, 
                secondary_client, 
                secondary_config,
                "secondary"
            )
            analysis_tasks.append(("secondary", secondary_task))
        
        # Phase 3: Execute analysis tasks concurrently
        logger.info(f"🤖 Sending {job.filename} to {len(analysis_tasks)} LLM(s) for analysis...")
        
        # Use asyncio.gather for concurrent execution
        task_results = await asyncio.gather(
            *[task for _, task in analysis_tasks],
            return_exceptions=True
        )
        
        # Phase 4: Collect results
        for i, (task_name, _) in enumerate(analysis_tasks):
            result = task_results[i]
            if isinstance(result, Exception):
                logger.error(f"❌ {task_name} analysis failed: {result}")
                results[task_name] = f"❌ Erro na análise {task_name}: {str(result)}"
            else:
                results[task_name] = result
                logger.info(f"✅ {task_name} analysis completed ({len(result)} characters)")
        
        return results
        
    except Exception as e:
        logger.error(f"❌ Error processing PDF job {job.id}: {e}")
        raise
