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

This is a single-file Matrix bot (`bot.py`) that monitors Matrix rooms for PDF uploads and generates AI-powered summaries. Key architectural components:

### Core Pipeline
1. **PDF Detection**: Monitors Matrix room for `.pdf` file uploads via `RoomMessageMedia` events
2. **Download & Extract**: Downloads PDF files and extracts text using `pypdf`
3. **Preprocessing**: Removes watermarks (specifically 5-digit sequences that repeat 3+ times)
4. **AI Summarization**: Uses OpenAI GPT-4o-mini to generate summaries with specialized medical instructions
5. **Response**: Posts threaded replies with summaries back to the Matrix room

### State Management
- **Session Persistence**: Stores Matrix session data (access tokens, sync tokens) in `session.json`
- **Sync Token Handling**: Preserves sync position to avoid reprocessing old messages after restarts
- **Graceful Shutdown**: Saves session state on SIGINT/shutdown

### Configuration
- Uses `.env` file for all configuration (Matrix credentials, OpenAI API key, room ID)
- Copy `.env.example` to `.env` and configure before running
- Session file location configurable via `SESSION_FILE` environment variable

### Specialized Use Case
The bot is currently configured for Brazilian Portuguese medical report analysis with specific triage criteria for vascular surgery patients. The summarization instructions are hardcoded in the `process_pdf()` function and include detailed acceptance/rejection criteria for a hospital's vascular department.

### Key Dependencies
- `matrix-nio[e2e]`: Matrix client library with E2E encryption support
- `pypdf`: PDF text extraction
- `openai`: OpenAI API client
- `python-dotenv`: Environment variable management
- `aiohttp`: HTTP client (dependency of matrix-nio)

### Event Handling
- Asynchronous event-driven architecture using `asyncio`
- Uses callbacks for message events and sync responses
- Maintains persistent sync loop with automatic reconnection