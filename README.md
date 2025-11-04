# Matrix PDF Summarizer Bot

A Matrix bot that automatically detects PDF uploads in a room, extracts their text content, and generates AI-powered summaries.

## Features

- 🤖 Automatically detects PDF file uploads in Matrix rooms
- 📄 Extracts text from PDF documents
- 🧹 Removes repeating watermark sequences
- 🧠 Generates concise summaries using OpenAI's GPT-4o-mini
- 💬 Replies to the original PDF message with the summary (threaded)
- 💾 Persists sync tokens to avoid reprocessing messages after restarts
- 🛡️ Clean shutdown handling with state preservation

## Requirements

- Python 3.12+
- OpenAI API key
- Matrix account and homeserver access
- `uv` package manager (recommended)

## Installation

1. Clone this repository:
```bash
git clone <repository-url>
cd matrix-pdf-summarizer-bot
```

2. Install dependencies using `uv`:
```bash
uv sync
```

Alternatively, using pip:
```bash
pip install -r requirements.txt
```

3. Copy the example environment file and configure it:
```bash
cp .env.example .env
```

4. Edit `.env` with your credentials:
   - `MATRIX_HOMESERVER`: Your Matrix homeserver URL
   - `MATRIX_USER`: Your bot's Matrix user ID
   - `MATRIX_PASSWORD`: Your bot's password
   - `MATRIX_ROOM_ID`: The room ID to monitor (without server suffix)
   - `OPENAI_API_KEY`: Your OpenAI API key

## Running the Bot

Start the bot with:
```bash
uv run bot.py
```

Or if using a virtual environment:
```bash
source .venv/bin/activate
python bot.py
```

The bot will:
1. Connect to your Matrix homeserver
2. Join the specified room
3. Listen for PDF file uploads
4. Automatically process and summarize each PDF
5. Reply to the original message with the summary

## Usage

Simply upload a PDF file to the monitored Matrix room. The bot will:
1. Reply with "🧠 Processing `filename.pdf`..."
2. Download and extract text from the PDF
3. Remove any repeating watermarks
4. Generate a summary using AI
5. Reply with "📘 **Summary of `filename.pdf`:**" followed by the summary

All responses are threaded as replies to the original PDF upload message.

## Stopping the Bot

Press `Ctrl+C` to gracefully shutdown the bot. The sync position will be saved automatically, so the bot won't reprocess old messages when restarted.

## Customization

The bot's summarization instructions can be customized in `bot.py` at the `process_pdf()` function. Currently configured for medical report summaries in Brazilian Portuguese.

## Acknowledgments

This project was built with the assistance of:
- **Claude Sonnet 4.5** via [Claude Code](https://claude.com/claude-code)
- **GPT-4** for ideation and guidance

## License

MIT License - see [LICENSE](LICENSE) file for details
