# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Commands

### Running the Bot
```bash
# Recommended - using uv
uv run bot.py

# Alternative - using virtual environment
source .venv/bin/activate
python bot.py
```

### Dependencies Management
```bash
# Install/sync dependencies (uv recommended)
uv sync

# Alternative with pip
pip install -r requirements.txt  # Note: No requirements.txt exists, use pyproject.toml
```

### Code Quality
```bash
# Format code (configured in pyproject.toml)
black .

# Lint code (configured in pyproject.toml)  
ruff check .
```

## Architecture

This is a Matrix bot that monitors Matrix rooms for PDF uploads and generates AI-powered summaries using single or dual LLM processing. Key architectural components:

### Core Pipeline
1. **PDF Detection**: Monitors Matrix room for `.pdf` file uploads via `RoomMessageMedia` events
2. **Download & Extract**: Downloads PDF files and extracts text using `pypdf`
3. **Preprocessing**: Removes watermarks (specifically 5-digit sequences that repeat 3+ times)
4. **AI Summarization**: Uses configurable LLM(s) with support for multiple providers and concurrent dual processing
5. **Response**: Posts threaded replies with single or dual analyses back to the Matrix room

### Dual-LLM Architecture
- **Single LLM Mode**: Traditional single analysis using one LLM (default behavior)
- **Dual LLM Mode**: Concurrent processing with two different LLMs/prompts for comparison
- **Multi-Provider Support**: OpenAI, Anthropic Claude, Azure OpenAI, Ollama, and generic OpenAI-compatible APIs
- **Concurrent Processing**: When dual mode is enabled, both LLMs process the PDF simultaneously

### State Management
- **Session Persistence**: Stores Matrix session data (access tokens, sync tokens) in `session.json`
- **Sync Token Handling**: Preserves sync position to avoid reprocessing old messages after restarts
- **Graceful Shutdown**: Saves session state on SIGINT/shutdown

### Configuration
- Uses `.env` file for all configuration (Matrix credentials, LLM providers, room ID, etc.)
- Copy `.env.example` to `.env` and configure before running
- **Session file**: Configurable via `SESSION_FILE` environment variable (defaults to `session.json`)

#### Single LLM Configuration (Default)
- **Provider**: `DEFAULT_LLM_PROVIDER` - LLM provider (openai, anthropic, azure, generic)
- **Model**: `DEFAULT_LLM_MODEL` - Model identifier (e.g., gpt-5-mini, claude-3-5-sonnet)
- **API Key**: `DEFAULT_LLM_API_KEY` - API key for the LLM service
- **Base URL**: `DEFAULT_LLM_BASE_URL` - Optional custom endpoint for OpenAI-compatible APIs
- **Prompt**: `DEFAULT_LLM_PROMPT` - Path to prompt file (defaults to `prompts/medical_triage.txt`)

#### Dual LLM Configuration (Optional)
- **Enable Dual Mode**: `DUAL_LLM_ENABLED=true` - Enables concurrent dual processing
- **Secondary Provider**: `SECONDARY_LLM_PROVIDER` - Provider for second analysis
- **Secondary Model**: `SECONDARY_LLM_MODEL` - Model for secondary analysis
- **Secondary API Key**: `SECONDARY_LLM_API_KEY` - API key for secondary LLM
- **Secondary Base URL**: `SECONDARY_LLM_BASE_URL` - Optional custom endpoint
- **Secondary Prompt**: `SECONDARY_LLM_PROMPT` - Path to secondary prompt file

#### Common Parameters
- `LLM_TEMPERATURE`: Response creativity control (0.0-2.0, applies to both LLMs)
- `LLM_MAX_TOKENS`: Maximum response length (applies to both LLMs)

#### Backward Compatibility
The following legacy variables are still supported:
- `OPENAI_API_KEY` → Falls back to `DEFAULT_LLM_API_KEY`
- `LLM_MODEL` → Falls back to `DEFAULT_LLM_MODEL`
- `LLM_BASE_URL` → Falls back to `DEFAULT_LLM_BASE_URL`
- `PROMPT_FILE` → Falls back to `DEFAULT_LLM_PROMPT`

### Specialized Use Case
The bot is currently configured for Brazilian Portuguese medical report analysis with specific triage criteria for vascular surgery patients. The summarization instructions are stored in `prompts/medical_triage.txt` and include detailed acceptance/rejection criteria for a hospital's vascular department. The prompt file can be easily customized without modifying the code.

### Key Dependencies
- `matrix-nio[e2e]`: Matrix client library with E2E encryption support
- `pypdf`: PDF text extraction
- `openai`: OpenAI API client (also used for OpenAI-compatible APIs)
- `anthropic`: Anthropic Claude API client (optional, for Anthropic provider)
- `python-dotenv`: Environment variable management
- `aiohttp`: HTTP client (dependency of matrix-nio)

### Key Components
- **LLM Factory** (`llm_factory.py`): Multi-provider LLM client creation and management
- **PDF Processor** (`pdf_processor.py`): Enhanced with dual LLM processing capabilities
- **Job Queue** (`job_queue.py`): Handles asynchronous PDF processing tasks
- **Main Bot** (`bot.py`): Matrix integration, configuration management, and result handling

### Event Handling
- Asynchronous event-driven architecture using `asyncio`
- Uses callbacks for message events and sync responses
- Maintains persistent sync loop with automatic reconnection
- Background job processing with concurrent LLM analysis when dual mode is enabled

### Supported LLM Providers
- **OpenAI**: GPT models via OpenAI API
- **Anthropic**: Claude models via Anthropic API
- **Azure OpenAI**: GPT models via Azure endpoints
- **Ollama**: Local models via Ollama server
- **Generic**: Any OpenAI-compatible API (LM Studio, local deployments, etc.)