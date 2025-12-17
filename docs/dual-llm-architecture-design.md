# Dual-LLM Architecture Design

## Overview

This document describes the technical architecture and design decisions for implementing dual-LLM functionality in the Matrix PDF Summarizer Bot. It covers system architecture, data flow, component interactions, and technical implementation details.

## Current Architecture Analysis

### Existing Components

```
┌─────────────────┐    ┌──────────────────┐    ┌─────────────────┐
│   Matrix Room   │    │   Job Queue      │    │  PDF Processor  │
│   (Events)      │───▶│   (SQLite)       │───▶│   (Thread Pool) │
└─────────────────┘    └──────────────────┘    └─────────────────┘
                                │                        │
                                │                        ▼
                                │               ┌─────────────────┐
                                │               │   LLM Client    │
                                │               │   (OpenAI)      │
                                │               └─────────────────┘
                                ▼                        │
                        ┌──────────────────┐             │
                        │  Result Sender   │◀────────────┘
                        │   (Background)   │
                        └──────────────────┘
                                │
                                ▼
                        ┌──────────────────┐
                        │   Matrix Room    │
                        │   (Response)     │
                        └──────────────────┘
```

### Current Limitations

1. **Single LLM Client**: Hardcoded OpenAI client instantiation
2. **Single Configuration**: Fixed model/prompt per deployment
3. **Single Response**: One analysis result per PDF
4. **Provider Lock-in**: Tight coupling to OpenAI API structure

## New Architecture Design

### High-Level Architecture

```
┌─────────────────┐    ┌──────────────────┐    ┌─────────────────┐
│   Matrix Room   │    │   Job Queue      │    │  PDF Processor  │
│   (Events)      │───▶│   (SQLite)       │───▶│   (Thread Pool) │
└─────────────────┘    └──────────────────┘    └─────────────────┘
                                │                        │
                                │                        ▼
                                │               ┌─────────────────┐
                                │               │  LLM Factory    │
                                │               │  (Multi-Provider)│
                                │               └─────────────────┘
                                │                        │
                                │                        ▼
                                │               ┌─────────────────┐
                                │               │  Dual Processor │
                                │               │  (Async Calls)  │
                                │               └─────────────────┘
                                │                    │         │
                                │                    ▼         ▼
                                │           ┌─────────────┐ ┌─────────────┐
                                │           │ LLM Client  │ │ LLM Client  │
                                │           │ (Primary)   │ │ (Secondary) │
                                │           └─────────────┘ └─────────────┘
                                ▼                    │         │
                        ┌──────────────────┐         │         │
                        │  Result Sender   │◀────────┴─────────┘
                        │  (Dual Messages) │
                        └──────────────────┘
                                │
                                ▼
                        ┌──────────────────┐
                        │   Matrix Room    │
                        │  (2 Responses)   │
                        └──────────────────┘
```

## Component Design

### 1. LLM Client Factory

**Purpose**: Create provider-specific LLM clients
**Location**: `llm_factory.py`

```python
from typing import Optional, Any, Dict
from enum import Enum
import logging

logger = logging.getLogger("matrix-pdf-bot.llm_factory")

class LLMProvider(Enum):
    OPENAI = "openai"
    ANTHROPIC = "anthropic"
    AZURE = "azure"
    OLLAMA = "ollama"
    GENERIC = "generic"

class LLMClientFactory:
    """Factory for creating LLM clients across different providers."""
    
    @staticmethod
    def create_client(
        provider: str,
        api_key: str,
        base_url: Optional[str] = None,
        **kwargs
    ) -> Any:
        """
        Create an LLM client for the specified provider.
        
        Args:
            provider: LLM provider name (openai, anthropic, azure, generic)
            api_key: API authentication key
            base_url: Custom endpoint URL (optional)
            **kwargs: Additional provider-specific parameters
            
        Returns:
            Configured LLM client instance
            
        Raises:
            ValueError: If provider is not supported
            ImportError: If required provider library is not available
        """
        provider = provider.lower()
        
        if provider == LLMProvider.OPENAI.value:
            return LLMClientFactory._create_openai_client(api_key, base_url, **kwargs)
        elif provider == LLMProvider.ANTHROPIC.value:
            return LLMClientFactory._create_anthropic_client(api_key, base_url, **kwargs)
        elif provider == LLMProvider.AZURE.value:
            return LLMClientFactory._create_azure_client(api_key, base_url, **kwargs)
        elif provider == LLMProvider.GENERIC.value:
            return LLMClientFactory._create_generic_client(api_key, base_url, **kwargs)
        else:
            raise ValueError(f"Unsupported LLM provider: {provider}")
    
    @staticmethod
    def _create_openai_client(api_key: str, base_url: Optional[str], **kwargs):
        """Create OpenAI client."""
        try:
            from openai import AsyncOpenAI
            
            client_kwargs = {"api_key": api_key}
            if base_url:
                client_kwargs["base_url"] = base_url
            
            client = AsyncOpenAI(**client_kwargs)
            logger.info(f"✅ OpenAI client created (endpoint: {base_url or 'default'})")
            return client
            
        except ImportError:
            raise ImportError("openai library not installed. Run: pip install openai")
    
    @staticmethod
    def _create_anthropic_client(api_key: str, base_url: Optional[str], **kwargs):
        """Create Anthropic client."""
        try:
            from anthropic import AsyncAnthropic
            
            client_kwargs = {"api_key": api_key}
            if base_url:
                client_kwargs["base_url"] = base_url
            
            client = AsyncAnthropic(**client_kwargs)
            logger.info(f"✅ Anthropic client created (endpoint: {base_url or 'default'})")
            return client
            
        except ImportError:
            raise ImportError("anthropic library not installed. Run: pip install anthropic")
    
    @staticmethod
    def _create_azure_client(api_key: str, base_url: Optional[str], **kwargs):
        """Create Azure OpenAI client."""
        try:
            from openai import AsyncAzureOpenAI
            
            if not base_url:
                raise ValueError("base_url is required for Azure OpenAI")
            
            client = AsyncAzureOpenAI(
                api_key=api_key,
                azure_endpoint=base_url,
                api_version="2024-02-01"
            )
            logger.info(f"✅ Azure OpenAI client created (endpoint: {base_url})")
            return client
            
        except ImportError:
            raise ImportError("openai library not installed. Run: pip install openai")
    
    @staticmethod
    def _create_generic_client(api_key: str, base_url: Optional[str], **kwargs):
        """Create generic OpenAI-compatible client."""
        try:
            from openai import AsyncOpenAI
            
            if not base_url:
                raise ValueError("base_url is required for generic OpenAI-compatible APIs")
            
            client = AsyncOpenAI(
                api_key=api_key or "not-required",  # Some local APIs don't need keys
                base_url=base_url
            )
            logger.info(f"✅ Generic OpenAI-compatible client created (endpoint: {base_url})")
            return client
            
        except ImportError:
            raise ImportError("openai library not installed. Run: pip install openai")

    @staticmethod
    def validate_provider(provider: str) -> bool:
        """Validate if provider is supported."""
        return provider.lower() in [p.value for p in LLMProvider]
```

### 2. Enhanced PDF Processor

**Purpose**: Handle dual LLM processing within single job
**Location**: Modified `pdf_processor.py`

```python
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
        provider = config.get("provider", "unknown")
        model = config.get("model", "unknown")
        
        logger.info(f"🧠 {provider_name} analysis starting ({provider}/{model})")
        
        # Build API parameters
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
            # Anthropic API uses different parameter names
            response = await client.messages.create(
                model=model,
                max_tokens=config.get("max_tokens", 4000),
                temperature=config.get("temperature", 0.7),
                messages=[{"role": "user", "content": f"{instructions}\n\n{text}"}]
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
```

### 3. Configuration Management

**Purpose**: Centralized configuration loading and validation
**Location**: Modified `bot.py`

```python
from dataclasses import dataclass
from typing import Optional, Dict, Any
import os

@dataclass
class LLMConfig:
    """Configuration for a single LLM instance."""
    provider: str
    model: str
    api_key: str
    base_url: Optional[str] = None
    prompt_file: str = "prompts/medical_triage.txt"
    temperature: Optional[float] = None
    max_tokens: Optional[int] = None
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for compatibility."""
        return {
            "provider": self.provider,
            "model": self.model,
            "api_key": self.api_key,
            "base_url": self.base_url,
            "prompt_file": self.prompt_file,
            "temperature": self.temperature,
            "max_tokens": self.max_tokens,
        }

class ConfigurationManager:
    """Manages bot configuration including LLM settings."""
    
    def __init__(self):
        self.primary_llm = self._load_primary_config()
        self.secondary_llm = self._load_secondary_config() if self.is_dual_enabled() else None
        self._validate_configuration()
    
    def _load_primary_config(self) -> LLMConfig:
        """Load primary LLM configuration."""
        return LLMConfig(
            provider=os.getenv("DEFAULT_LLM_PROVIDER", "openai"),
            model=os.getenv("DEFAULT_LLM_MODEL", os.getenv("LLM_MODEL", "gpt-5-mini")),
            api_key=os.getenv("DEFAULT_LLM_API_KEY", os.getenv("OPENAI_API_KEY")),
            base_url=os.getenv("DEFAULT_LLM_BASE_URL", os.getenv("LLM_BASE_URL")),
            prompt_file=os.getenv("DEFAULT_LLM_PROMPT", os.getenv("PROMPT_FILE", "prompts/medical_triage.txt")),
            temperature=float(os.getenv("LLM_TEMPERATURE")) if os.getenv("LLM_TEMPERATURE") else None,
            max_tokens=int(os.getenv("LLM_MAX_TOKENS")) if os.getenv("LLM_MAX_TOKENS") else None,
        )
    
    def _load_secondary_config(self) -> Optional[LLMConfig]:
        """Load secondary LLM configuration."""
        if not self.is_dual_enabled():
            return None
        
        return LLMConfig(
            provider=os.getenv("SECONDARY_LLM_PROVIDER"),
            model=os.getenv("SECONDARY_LLM_MODEL"),
            api_key=os.getenv("SECONDARY_LLM_API_KEY"),
            base_url=os.getenv("SECONDARY_LLM_BASE_URL"),
            prompt_file=os.getenv("SECONDARY_LLM_PROMPT"),
            temperature=float(os.getenv("LLM_TEMPERATURE")) if os.getenv("LLM_TEMPERATURE") else None,
            max_tokens=int(os.getenv("LLM_MAX_TOKENS")) if os.getenv("LLM_MAX_TOKENS") else None,
        )
    
    def is_dual_enabled(self) -> bool:
        """Check if dual LLM mode is enabled."""
        return os.getenv("DUAL_LLM_ENABLED", "false").lower() == "true"
    
    def _validate_configuration(self):
        """Validate configuration completeness."""
        errors = []
        
        # Validate primary LLM
        if not self.primary_llm.api_key:
            errors.append("DEFAULT_LLM_API_KEY is required")
        if not self.primary_llm.model:
            errors.append("DEFAULT_LLM_MODEL is required")
        if not os.path.exists(self.primary_llm.prompt_file):
            errors.append(f"Primary prompt file not found: {self.primary_llm.prompt_file}")
        
        # Validate secondary LLM (if enabled)
        if self.is_dual_enabled():
            if not self.secondary_llm:
                errors.append("Secondary LLM configuration incomplete")
            else:
                if not self.secondary_llm.api_key:
                    errors.append("SECONDARY_LLM_API_KEY required when DUAL_LLM_ENABLED=true")
                if not self.secondary_llm.model:
                    errors.append("SECONDARY_LLM_MODEL required when DUAL_LLM_ENABLED=true")
                if not self.secondary_llm.prompt_file:
                    errors.append("SECONDARY_LLM_PROMPT required when DUAL_LLM_ENABLED=true")
                elif not os.path.exists(self.secondary_llm.prompt_file):
                    errors.append(f"Secondary prompt file not found: {self.secondary_llm.prompt_file}")
        
        # Validate providers
        from llm_factory import LLMClientFactory
        if not LLMClientFactory.validate_provider(self.primary_llm.provider):
            errors.append(f"Unsupported primary LLM provider: {self.primary_llm.provider}")
        
        if self.secondary_llm and not LLMClientFactory.validate_provider(self.secondary_llm.provider):
            errors.append(f"Unsupported secondary LLM provider: {self.secondary_llm.provider}")
        
        if errors:
            for error in errors:
                logger.error(f"❌ Configuration error: {error}")
            raise SystemExit(1)
        
        logger.info("✅ Configuration validation passed")
        if self.is_dual_enabled():
            logger.info(f"🔄 Dual LLM mode enabled: {self.primary_llm.provider}/{self.primary_llm.model} + {self.secondary_llm.provider}/{self.secondary_llm.model}")
        else:
            logger.info(f"🤖 Single LLM mode: {self.primary_llm.provider}/{self.primary_llm.model}")
```

### 4. Enhanced Result Handling

**Purpose**: Send dual responses to Matrix room
**Location**: Modified `bot.py`

```python
async def send_job_result(job: Job):
    """Send job results - single or dual based on configuration."""
    results = job.result
    
    try:
        if isinstance(results, dict) and len(results) > 1:
            # Dual LLM results
            logger.info(f"📤 Sending dual results for {job.filename}")
            
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
```

## Data Flow Design

### Single LLM Mode (Existing)

```
PDF Upload → Job Queue → PDF Processor → LLM Client → Result → Matrix Response
```

### Dual LLM Mode (New)

```
PDF Upload → Job Queue → PDF Processor → ┌─ Primary LLM Client ─┐ → Results → ┌─ Primary Response
                                        │                      │           │
                                        └─ Secondary LLM Client ┘          └─ Secondary Response
```

### Detailed Flow

1. **PDF Upload Detection** (`message_callback`)
   - Matrix event triggers job creation
   - PDF file downloaded and stored in memory
   - Job added to SQLite queue

2. **Job Processing** (`process_jobs_background`)
   - Job retrieved from queue
   - Configuration determines single/dual mode
   - PDF processor called with appropriate clients

3. **PDF Analysis** (`process_pdf_dual_async`)
   - Text extraction and cleaning (common step)
   - Prompt loading for each configured LLM
   - Concurrent LLM API calls using `asyncio.gather`
   - Results collection and error handling

4. **Result Delivery** (`send_results_background`)
   - Results retrieved from completed jobs
   - Single or dual Matrix messages sent
   - Job cleanup and memory management

## Error Handling Strategy

### Failure Scenarios

1. **Configuration Errors**
   - Missing API keys → Startup validation failure
   - Invalid providers → Factory creation error
   - Missing prompt files → File validation error

2. **Network/API Errors**
   - Primary LLM failure → Partial result with error message
   - Secondary LLM failure → Primary result only, log secondary error
   - Both LLM failures → Job marked as failed

3. **Processing Errors**
   - PDF extraction failure → Standard error handling (existing)
   - Prompt loading failure → Job failure with specific error
   - Concurrent processing error → Individual LLM error handling

### Error Recovery

```python
# Example error handling in dual processing
try:
    task_results = await asyncio.gather(
        primary_task,
        secondary_task,
        return_exceptions=True
    )
    
    # Handle individual failures
    for i, result in enumerate(task_results):
        if isinstance(result, Exception):
            task_name = ["primary", "secondary"][i]
            logger.error(f"❌ {task_name} analysis failed: {result}")
            results[task_name] = f"❌ Erro na análise {task_name}: {str(result)}"
        else:
            results[task_name] = result
            
except Exception as e:
    # Catastrophic failure - mark entire job as failed
    logger.error(f"❌ Dual processing failed completely: {e}")
    raise
```

## Performance Considerations

### Memory Usage

- **Single Mode**: Baseline memory usage
- **Dual Mode**: ~20% increase (additional client + concurrent processing)
- **Optimization**: File data cleanup after processing

### Processing Time

- **Single Mode**: ~30-60 seconds per PDF
- **Dual Mode**: ~45-90 seconds per PDF (concurrent execution ~80% of sequential time)
- **Bottleneck**: LLM API response times, not local processing

### Resource Management

```python
# Memory-efficient concurrent processing
async def process_pdf_dual_async(job, primary_config, primary_client, secondary_config=None, secondary_client=None):
    # Extract text once, share between LLMs
    text = extract_pdf_text(job.file_data)
    cleaned_text = remove_watermark(text)
    
    # Release original file data early
    job.file_data = None
    
    # Concurrent LLM calls with shared text
    tasks = [
        analyze_with_llm(cleaned_text, primary_config, primary_client),
        analyze_with_llm(cleaned_text, secondary_config, secondary_client) if secondary_config else None
    ]
    
    # Filter None tasks and execute
    results = await asyncio.gather(*[t for t in tasks if t is not None])
    return results
```

## Security Considerations

### API Key Management

```python
# Secure configuration loading
class LLMConfig:
    def __init__(self):
        # Mask API keys in logs
        self.api_key = os.getenv("DEFAULT_LLM_API_KEY")
        if self.api_key:
            masked_key = f"{self.api_key[:8]}...{self.api_key[-4:]}" if len(self.api_key) > 12 else "***"
            logger.info(f"🔑 API key loaded: {masked_key}")
    
    def __repr__(self):
        # Never expose full API keys
        safe_dict = self.to_dict()
        if safe_dict.get("api_key"):
            safe_dict["api_key"] = "***masked***"
        return str(safe_dict)
```

### Input Validation

```python
# Validate provider inputs
def validate_provider_input(provider: str) -> str:
    """Validate and sanitize provider input."""
    if not provider:
        raise ValueError("Provider cannot be empty")
    
    provider = provider.lower().strip()
    valid_providers = ["openai", "anthropic", "azure", "ollama", "generic"]
    
    if provider not in valid_providers:
        raise ValueError(f"Invalid provider: {provider}. Must be one of: {valid_providers}")
    
    return provider
```

## Testing Strategy

### Unit Tests

- **LLMClientFactory**: Provider-specific client creation
- **ConfigurationManager**: Configuration loading and validation
- **PDF Processor**: Single and dual processing modes

### Integration Tests

- **End-to-End**: PDF upload → dual processing → dual responses
- **Error Scenarios**: API failures, configuration errors
- **Performance**: Processing time comparison

### Manual Testing

- **Single LLM Migration**: Existing setup continues working
- **Dual LLM Setup**: Two responses for single PDF
- **Provider Switching**: OpenAI → Anthropic → Ollama

## Deployment Considerations

### Backward Compatibility

```python
# Support both old and new configuration
def load_legacy_config():
    """Support existing environment variables."""
    return {
        "api_key": os.getenv("DEFAULT_LLM_API_KEY") or os.getenv("OPENAI_API_KEY"),
        "model": os.getenv("DEFAULT_LLM_MODEL") or os.getenv("LLM_MODEL", "gpt-5-mini"),
        "base_url": os.getenv("DEFAULT_LLM_BASE_URL") or os.getenv("LLM_BASE_URL"),
        "prompt_file": os.getenv("DEFAULT_LLM_PROMPT") or os.getenv("PROMPT_FILE", "prompts/medical_triage.txt"),
    }
```

### Migration Path

1. **Phase 1**: Deploy with new configuration support, dual mode disabled
2. **Phase 2**: Test single LLM with new configuration structure
3. **Phase 3**: Enable dual mode with secondary LLM configuration
4. **Phase 4**: Remove deprecated configuration variables (future release)

### Monitoring

```python
# Add metrics for dual LLM usage
class MetricsCollector:
    def __init__(self):
        self.dual_mode_usage = 0
        self.primary_success_rate = 0.0
        self.secondary_success_rate = 0.0
        self.avg_processing_time = 0.0
    
    def record_dual_processing(self, primary_success: bool, secondary_success: bool, duration: float):
        self.dual_mode_usage += 1
        # Update success rates and timing metrics
```

This architecture design provides a robust foundation for implementing dual-LLM functionality while maintaining backward compatibility and system reliability.