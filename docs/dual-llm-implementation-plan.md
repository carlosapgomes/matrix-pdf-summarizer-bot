# Dual-LLM Implementation Plan

## Overview

This document outlines the step-by-step implementation plan for adding dual-LLM capability to the Matrix PDF Summarizer Bot. The feature will allow processing each PDF with two different LLMs/prompts and posting separate analysis responses, enabling model comparison and evaluation workflows.

## Goals

- **Primary**: Enable dual-LLM processing with separate prompts for model evaluation
- **Secondary**: Make default LLM endpoint fully configurable
- **Tertiary**: Maintain backward compatibility and performance when feature is disabled

## Implementation Phases

### Phase 1: Configuration Infrastructure (Estimated: 2-3 hours)

#### Step 1.1: Update Environment Variable Structure

**File**: `.env.example`
**Action**: Add new configuration variables

```bash
# === Default LLM Configuration ===
DEFAULT_LLM_PROVIDER=openai          # openai, anthropic, ollama, azure, generic
DEFAULT_LLM_MODEL=gpt-5-mini         # Model identifier
DEFAULT_LLM_BASE_URL=                # Optional: Custom endpoint URL
DEFAULT_LLM_API_KEY=your_api_key     # API key for default LLM
DEFAULT_LLM_PROMPT=prompts/medical_triage.txt

# === Dual LLM Feature ===
DUAL_LLM_ENABLED=false               # Enable/disable dual processing

# === Secondary LLM Configuration (when dual enabled) ===
SECONDARY_LLM_PROVIDER=anthropic     # Provider for second analysis
SECONDARY_LLM_MODEL=claude-3-5-sonnet
SECONDARY_LLM_BASE_URL=              # Optional: Custom endpoint for secondary
SECONDARY_LLM_API_KEY=               # API key for secondary LLM
SECONDARY_LLM_PROMPT=prompts/medical_triage_secondary.txt

# === LLM Parameters (apply to both) ===
LLM_TEMPERATURE=0.7                  # Optional: Response creativity
LLM_MAX_TOKENS=                      # Optional: Maximum response length

# === Backward Compatibility (deprecated but supported) ===
# OPENAI_API_KEY=                    # Falls back to DEFAULT_LLM_API_KEY
# LLM_MODEL=                         # Falls back to DEFAULT_LLM_MODEL
# LLM_BASE_URL=                      # Falls back to DEFAULT_LLM_BASE_URL
# PROMPT_FILE=                       # Falls back to DEFAULT_LLM_PROMPT
```

#### Step 1.2: Create LLM Client Factory

**File**: New `llm_factory.py`
**Action**: Implement provider-agnostic LLM client creation

```python
from enum import Enum
from typing import Optional, Dict, Any
from openai import AsyncOpenAI
import logging

class LLMProvider(Enum):
    OPENAI = "openai"
    ANTHROPIC = "anthropic"
    AZURE = "azure"
    OLLAMA = "ollama"
    GENERIC = "generic"  # OpenAI-compatible APIs

class LLMClientFactory:
    @staticmethod
    def create_client(
        provider: str,
        api_key: str,
        base_url: Optional[str] = None,
        **kwargs
    ) -> Any:
        """Create appropriate LLM client based on provider."""
        # Implementation details in separate document
```

#### Step 1.3: Update Configuration Loading

**File**: `bot.py`
**Action**: Replace hardcoded configuration with new structure

```python
# Load new configuration variables
DEFAULT_LLM_PROVIDER = os.getenv("DEFAULT_LLM_PROVIDER", "openai")
DEFAULT_LLM_API_KEY = os.getenv("DEFAULT_LLM_API_KEY", os.getenv("OPENAI_API_KEY"))
DEFAULT_LLM_MODEL = os.getenv("DEFAULT_LLM_MODEL", os.getenv("LLM_MODEL", "gpt-5-mini"))
# ... additional variables

# Dual LLM configuration
DUAL_LLM_ENABLED = os.getenv("DUAL_LLM_ENABLED", "false").lower() == "true"
# ... dual LLM variables
```

### Phase 2: Dual-LLM Core Implementation (Estimated: 3-4 hours)

#### Step 2.1: Extend LLM Configuration Structure

**File**: `bot.py`
**Action**: Create configuration objects for both LLMs

```python
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
```

#### Step 2.2: Initialize LLM Clients

**File**: `bot.py`
**Action**: Create client instances using factory

```python
from llm_factory import LLMClientFactory

# Create default LLM client
default_llm_client = LLMClientFactory.create_client(
    provider=default_llm_config["provider"],
    api_key=default_llm_config["api_key"],
    base_url=default_llm_config["base_url"]
)

# Create secondary LLM client (if dual enabled)
secondary_llm_client = None
if DUAL_LLM_ENABLED:
    secondary_llm_client = LLMClientFactory.create_client(
        provider=secondary_llm_config["provider"],
        api_key=secondary_llm_config["api_key"],
        base_url=secondary_llm_config["base_url"]
    )
```

#### Step 2.3: Modify PDF Processor for Dual Analysis

**File**: `pdf_processor.py`
**Action**: Add dual processing capability

```python
async def process_pdf_dual_async(
    job: Job,
    default_config: dict,
    default_client: Any,
    secondary_config: dict = None,
    secondary_client: Any = None
) -> dict:
    """
    Process PDF with one or two LLMs based on configuration.
    Returns: {"default": summary1, "secondary": summary2} or {"default": summary1}
    """
    # Extract and clean text (common for both)
    text = extract_pdf_text(job.file_data)
    cleaned_text = remove_watermark(text)

    results = {}

    # Process with default LLM
    default_prompt = load_prompt(default_config["prompt_file"])
    results["default"] = await summarize_text(
        cleaned_text, default_prompt, default_client, default_config
    )

    # Process with secondary LLM (if configured)
    if secondary_config and secondary_client:
        secondary_prompt = load_prompt(secondary_config["prompt_file"])
        results["secondary"] = await summarize_text(
            cleaned_text, secondary_prompt, secondary_client, secondary_config
        )

    return results
```

### Phase 3: Matrix Integration (Estimated: 2 hours)

#### Step 3.1: Update Job Processing

**File**: `bot.py`
**Action**: Modify background job processor

```python
async def process_jobs_background():
    # ... existing code ...

    try:
        # Process PDF using new dual function
        results = await process_pdf_dual_async(
            job,
            default_llm_config,
            default_llm_client,
            secondary_llm_config if DUAL_LLM_ENABLED else None,
            secondary_llm_client if DUAL_LLM_ENABLED else None
        )

        # Store results in job
        job_queue.complete_job(job.id, results)

    except Exception as e:
        logger.error(f"❌ Error processing job {job.id}: {e}")
        job_queue.fail_job(job.id, str(e))
```

#### Step 3.2: Implement Dual Response Sending

**File**: `bot.py`
**Action**: Modify result sending for multiple responses

```python
async def send_job_result(job: Job):
    """Send job results - single or dual based on configuration."""
    results = job.result

    if isinstance(results, dict):
        # Dual LLM results
        if "default" in results:
            await matrix_client.room_send(
                room_id=job.room_id,
                message_type="m.room.message",
                content={
                    "msgtype": "m.text",
                    "body": f"🤖 **Análise Primária**\n\n{results['default']}",
                    "m.relates_to": {"m.in_reply_to": {"event_id": job.event_id}},
                },
            )

        if "secondary" in results:
            await matrix_client.room_send(
                room_id=job.room_id,
                message_type="m.room.message",
                content={
                    "msgtype": "m.text",
                    "body": f"🔍 **Análise Secundária**\n\n{results['secondary']}",
                    "m.relates_to": {"m.in_reply_to": {"event_id": job.event_id}},
                },
            )
    else:
        # Backward compatibility - single result
        await matrix_client.room_send(
            room_id=job.room_id,
            message_type="m.room.message",
            content={
                "msgtype": "m.text",
                "body": f"{results}",
                "m.relates_to": {"m.in_reply_to": {"event_id": job.event_id}},
            },
        )

    logger.info(f"✅ Summary for {job.filename} sent to Matrix room")
```

### Phase 4: Testing & Finalization (Estimated: 1-2 hours)

#### Step 4.1: Configuration Validation

**File**: `bot.py`
**Action**: Add startup validation

```python
def validate_configuration():
    """Validate LLM configuration at startup."""
    errors = []

    # Validate default LLM config
    if not DEFAULT_LLM_API_KEY:
        errors.append("DEFAULT_LLM_API_KEY is required")

    # Validate dual LLM config (if enabled)
    if DUAL_LLM_ENABLED:
        if not SECONDARY_LLM_API_KEY:
            errors.append("SECONDARY_LLM_API_KEY required when DUAL_LLM_ENABLED=true")
        if not SECONDARY_LLM_PROMPT or not os.path.exists(SECONDARY_LLM_PROMPT):
            errors.append("SECONDARY_LLM_PROMPT file not found")

    if errors:
        for error in errors:
            logger.error(f"❌ Configuration error: {error}")
        raise SystemExit(1)

    logger.info("✅ Configuration validation passed")
```

#### Step 4.2: Update Documentation

**Files**: `README.md`, `CLAUDE.md`
**Action**: Document new configuration options

#### Step 4.3: Create Example Prompt Files

**File**: `prompts/medical_triage_secondary.txt`
**Action**: Create example secondary prompt for testing

#### Step 4.4: Test Migration Path

**Action**: Verify existing installations work without changes

## Migration Strategy

### Backward Compatibility

- Existing environment variables continue to work
- Single-LLM behavior unchanged when `DUAL_LLM_ENABLED=false`
- Existing prompt files and session data preserved

### Upgrade Path

1. Update `.env` with new variables
2. Create secondary prompt file (if using dual mode)
3. Enable dual mode: `DUAL_LLM_ENABLED=true`
4. Restart bot

## Risk Assessment

### Low Risk

- Configuration changes (environment variables)
- Adding new optional functionality
- Backward compatibility preservation

### Medium Risk

- PDF processor modifications (core functionality)
- Matrix message sending changes
- LLM client factory implementation

### Mitigation Strategies

- Comprehensive testing before deployment
- Feature flag for easy rollback (`DUAL_LLM_ENABLED=false`)
- Preserve existing code paths for single-LLM operation
- Gradual rollout with monitoring

## Success Criteria

1. **Functional**: Bot processes PDFs with two different LLMs when enabled
2. **Performance**: Single-LLM performance unchanged when dual mode disabled
3. **Reliability**: Error handling maintains bot stability
4. **Usability**: Configuration is intuitive and well-documented
5. **Compatibility**: Existing installations work without modification

## Post-Implementation

### Monitoring

- Track processing times for dual vs single mode
- Monitor API usage and costs
- Collect user feedback on analysis quality

### Future Enhancements

- Support for more than two LLMs
- Custom response formatting per LLM
- Automated model comparison scoring
- Cost optimization features

