# Matrix PDF Summarizer Bot

A Matrix bot that automatically detects PDF uploads in a room, extracts their text content, and generates AI-powered summaries.

## Features

- 🤖 Automatically detects PDF file uploads in Matrix rooms
- 📄 Extracts text from PDF documents
- 🧹 Removes repeating watermark sequences
- 🧠 Generates concise summaries using configurable LLM (defaults to GPT-5-mini)
- 🔧 Supports OpenAI-compatible APIs (Ollama, LM Studio, Azure OpenAI, etc.)
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
   - `LLM_MODEL`: AI model to use (defaults to `gpt-5-mini`)
   - `LLM_BASE_URL`: (Optional) Custom API endpoint for OpenAI-compatible APIs
   - `LLM_TEMPERATURE`: (Optional) Response creativity (0.0-2.0)
   - `LLM_MAX_TOKENS`: (Optional) Maximum response length
   - `PROMPT_FILE`: Path to prompt file (defaults to `prompts/medical_triage.txt`)

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

## Production Deployment (VPS/Server)

For deploying the bot on the same server as your Matrix homeserver with resource optimization:

### 1. Create dedicated user and directory
```bash
# Create bot user with limited privileges
sudo useradd -m -s /bin/bash matrixbot
sudo su - matrixbot

# Create bot directory
mkdir ~/pdf-bot
cd ~/pdf-bot
```

### 2. Install the bot
```bash
# Clone repository
git clone https://github.com/carlosapgomes/matrix-pdf-summarizer-bot.git .

# Install uv (recommended for faster dependency resolution)
curl -LsSf https://astral.sh/uv/install.sh | sh
source ~/.bashrc

# Install dependencies
uv sync
```

### 3. Configure environment
```bash
# Copy and edit configuration
cp .env.example .env
nano .env
```

Configure with your local Matrix server:
```bash
MATRIX_HOMESERVER=http://localhost:8008  # or your Matrix server port
MATRIX_USER=@pdfbot:yourdomain.com
MATRIX_PASSWORD=your_bot_password
MATRIX_ROOM_ID=!yourroom:yourdomain.com
OPENAI_API_KEY=your_openai_key
LLM_MODEL=gpt-5-mini
# LLM_BASE_URL=http://localhost:11434/v1  # Optional: for local Ollama
```

### 4. Create systemd service with resource limits
```bash
sudo nano /etc/systemd/system/matrix-pdf-bot.service
```

```ini
[Unit]
Description=Matrix PDF Summarizer Bot
After=network.target
Wants=network.target

[Service]
Type=simple
User=matrixbot
Group=matrixbot
WorkingDirectory=/home/matrixbot/pdf-bot
ExecStart=/home/matrixbot/.local/bin/uv run bot.py
Restart=always
RestartSec=10

# Resource limits to protect Matrix server
CPUQuota=50%
MemoryMax=512M
Nice=10
IOSchedulingClass=2
IOSchedulingPriority=7

# Security hardening
NoNewPrivileges=true
PrivateTmp=true
ProtectSystem=strict
ReadWritePaths=/home/matrixbot/pdf-bot

[Install]
WantedBy=multi-user.target
```

### 5. Deploy and start
```bash
# Reload systemd and enable service
sudo systemctl daemon-reload
sudo systemctl enable matrix-pdf-bot.service
sudo systemctl start matrix-pdf-bot.service

# Check status
sudo systemctl status matrix-pdf-bot.service
```

### 6. Monitor resource usage
```bash
# Monitor bot resources
sudo systemctl status matrix-pdf-bot.service
sudo journalctl -u matrix-pdf-bot.service -f

# Check system resources
htop
# Look for python processes under matrixbot user
```

### Resource Optimizations Applied
- **CPU limit**: 50% maximum CPU usage
- **Memory limit**: 512MB maximum (adjust based on your VPS specs)
- **Process priority**: Lower priority (nice=10) so Matrix gets preference
- **I/O priority**: Lower I/O scheduling priority
- **Security isolation**: Restricted filesystem access and privileges
- **Dedicated user**: Runs under separate user account

## Customization

### AI Prompt Configuration

The bot's summarization instructions are stored in an external prompt file for easy customization:

- **Default prompt**: `prompts/medical_triage.txt`
- **Custom prompt**: Set `PROMPT_FILE` in `.env` to point to your own prompt file

The default prompt is configured for medical report triage in Brazilian Portuguese with specific acceptance criteria for vascular surgery patients.

### Using Different LLM Providers

The bot supports any OpenAI-compatible API. Examples:

**Local LLM with Ollama:**
```bash
LLM_MODEL=llama3.2
LLM_BASE_URL=http://localhost:11434/v1
```

**Azure OpenAI:**
```bash
LLM_MODEL=gpt-4
LLM_BASE_URL=https://your-resource.openai.azure.com/openai/deployments/your-deployment
```

**LM Studio:**
```bash
LLM_MODEL=local-model
LLM_BASE_URL=http://localhost:1234/v1
```

## Acknowledgments

This project was built with the assistance of:
- **Claude Sonnet 4.5** via [Claude Code](https://claude.com/claude-code)
- **GPT-4** for ideation and guidance

## License

MIT License - see [LICENSE](LICENSE) file for details
