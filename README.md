# Matrix PDF Summarizer Bot

A Matrix bot that automatically detects PDF uploads in a room, extracts their text content, and generates AI-powered summaries.

## Features

- 🤖 Automatically detects PDF file uploads in Matrix rooms
- 📄 Extracts text from PDF documents
- 🧹 Removes repeating watermark sequences
- 🧠 Generates concise summaries using configurable LLM (defaults to GPT-5-mini)
- 🔄 **Dual LLM processing** - Compare analyses from two different LLMs simultaneously
- 🌐 **Multi-provider support** - OpenAI, Anthropic Claude, Azure OpenAI, Ollama, and generic APIs
- 🔧 Supports OpenAI-compatible APIs (Ollama, LM Studio, etc.)
- 💬 Replies to the original PDF message with the summary (threaded)
- 💾 Persists sync tokens to avoid reprocessing messages after restarts
- 🛡️ Clean shutdown handling with state preservation

## Requirements

- Python 3.12+
- At least one LLM API key (OpenAI, Anthropic, etc.)
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

### Matrix Configuration
- `MATRIX_HOMESERVER`: Your Matrix homeserver URL
- `MATRIX_USER`: Your bot's Matrix user ID
- `MATRIX_PASSWORD`: Your bot's password
- `MATRIX_ROOM_ID`: The room ID to monitor (without server suffix)

### Default LLM Configuration
- `DEFAULT_LLM_PROVIDER`: LLM provider (`openai`, `anthropic`, `azure`, `generic`)
- `DEFAULT_LLM_API_KEY`: API key for your chosen provider
- `DEFAULT_LLM_MODEL`: AI model to use (e.g., `gpt-5-mini`, `claude-3-5-sonnet`)
- `DEFAULT_LLM_BASE_URL`: (Optional) Custom API endpoint for OpenAI-compatible APIs
- `DEFAULT_LLM_PROMPT`: Path to prompt file (defaults to `prompts/medical_triage.txt`)

### Dual LLM Configuration (Optional)
- `DUAL_LLM_ENABLED`: Set to `true` to enable dual processing
- `SECONDARY_LLM_PROVIDER`: Second LLM provider for comparison
- `SECONDARY_LLM_API_KEY`: API key for secondary LLM
- `SECONDARY_LLM_MODEL`: Model for secondary analysis
- `SECONDARY_LLM_BASE_URL`: (Optional) Custom endpoint for secondary LLM
- `SECONDARY_LLM_PROMPT`: Path to secondary prompt file

### Common Parameters
- `LLM_TEMPERATURE`: (Optional) Response creativity (0.0-2.0)
- `LLM_MAX_TOKENS`: (Optional) Maximum response length

### Backward Compatibility (Deprecated)
- `OPENAI_API_KEY`: Falls back to `DEFAULT_LLM_API_KEY`
- `LLM_MODEL`: Falls back to `DEFAULT_LLM_MODEL`
- `LLM_BASE_URL`: Falls back to `DEFAULT_LLM_BASE_URL`
- `PROMPT_FILE`: Falls back to `DEFAULT_LLM_PROMPT`

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

### Single LLM Mode (Default)
1. Reply with "🧠 Processing `filename.pdf`..."
2. Download and extract text from the PDF
3. Remove any repeating watermarks
4. Generate a summary using your configured LLM
5. Reply with the analysis

### Dual LLM Mode (When Enabled)
1. Reply with "🧠 Processing `filename.pdf`..."
2. Download and extract text from the PDF
3. Remove any repeating watermarks
4. Concurrently generate analyses using both configured LLMs
5. Reply with "🤖 **Análise Primária**" followed by primary analysis
6. Reply with "🔍 **Análise Secundária**" followed by secondary analysis

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
# Matrix Configuration
MATRIX_HOMESERVER=http://localhost:8008  # or your Matrix server port
MATRIX_USER=@pdfbot:yourdomain.com
MATRIX_PASSWORD=your_bot_password
MATRIX_ROOM_ID=!yourroom:yourdomain.com

# Default LLM Configuration
DEFAULT_LLM_PROVIDER=openai
DEFAULT_LLM_MODEL=gpt-5-mini
DEFAULT_LLM_API_KEY=your_openai_key

# Optional: Enable dual LLM for model comparison
# DUAL_LLM_ENABLED=true
# SECONDARY_LLM_PROVIDER=anthropic
# SECONDARY_LLM_MODEL=claude-3-5-sonnet-20241022
# SECONDARY_LLM_API_KEY=your_anthropic_key
# SECONDARY_LLM_PROMPT=prompts/medical_triage_secondary.txt

# Optional: Use local Ollama
# DEFAULT_LLM_PROVIDER=generic
# DEFAULT_LLM_BASE_URL=http://localhost:11434/v1
# DEFAULT_LLM_API_KEY=not_required
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

## Auto-Deployment Options

You can set up automatic deployment to update the bot when you push changes to the repository:

### Option 1: Cron Job with Git Polling (Recommended)

Simple cron job that checks for updates every few minutes:

```bash
# Edit crontab as the matrixbot user
sudo su - matrixbot
crontab -e

# Add this line to check for updates every 5 minutes
*/5 * * * * cd /home/matrixbot/pdf-bot && git fetch && [ $(git rev-list HEAD...origin/master --count) != 0 ] && git pull && sudo /usr/bin/systemctl restart matrix-pdf-bot.service
```

**How it works:**

- `git fetch` - Downloads latest commit info (lightweight operation)
- `git rev-list HEAD...origin/master --count` - Counts commits you don't have locally
- If count > 0, runs `git pull` and restarts the service
- Only triggers actual deployment when there are new commits

**Setup requirements:**

```bash
# Give matrixbot user permission to restart the service
sudo visudo
# Add this line:
matrixbot ALL=(ALL) NOPASSWD: /usr/bin/systemctl restart matrix-pdf-bot.service
```

**Benefits:**

- Very simple setup
- Minimal network usage (~500 bytes per check when no updates)
- No external dependencies
- Works with any git hosting (GitHub, GitLab, etc.)

### Option 2: GitHub Actions with SSH (Alternative)

For more control, you can use GitHub Actions to deploy via SSH when you push to master. This requires SSH key setup and is more complex but gives you deployment status in GitHub.

## Customization

### AI Prompt Configuration

The bot's summarization instructions are stored in an external prompt file for easy customization:

- **Default prompt**: `prompts/medical_triage.txt`
- **Custom prompt**: Set `PROMPT_FILE` in `.env` to point to your own prompt file

The default prompt is configured for medical report triage in Brazilian Portuguese with specific acceptance criteria for vascular surgery patients.

### Using Different LLM Providers

The bot supports multiple LLM providers. Examples:

#### Single LLM Configuration Examples

**OpenAI (Default):**
```bash
DEFAULT_LLM_PROVIDER=openai
DEFAULT_LLM_MODEL=gpt-5-mini
DEFAULT_LLM_API_KEY=sk-your_openai_key_here
# DEFAULT_LLM_BASE_URL not needed (uses default endpoint)
```

**Anthropic Claude:**
```bash
DEFAULT_LLM_PROVIDER=anthropic
DEFAULT_LLM_MODEL=claude-3-5-sonnet-20241022
DEFAULT_LLM_API_KEY=sk-ant-your_anthropic_key_here
```

**Local LLM with Ollama:**
```bash
DEFAULT_LLM_PROVIDER=generic
DEFAULT_LLM_MODEL=llama3.1:8b
DEFAULT_LLM_BASE_URL=http://localhost:11434/v1
DEFAULT_LLM_API_KEY=not_required
```

**Azure OpenAI:**
```bash
DEFAULT_LLM_PROVIDER=azure
DEFAULT_LLM_MODEL=your-deployment-name
DEFAULT_LLM_BASE_URL=https://your-resource.openai.azure.com/
DEFAULT_LLM_API_KEY=your_azure_api_key
```

#### Dual LLM Configuration Examples

**OpenAI + Anthropic:**
```bash
# Primary LLM
DEFAULT_LLM_PROVIDER=openai
DEFAULT_LLM_MODEL=gpt-5-mini
DEFAULT_LLM_API_KEY=sk-your_openai_key_here
DEFAULT_LLM_PROMPT=prompts/medical_triage_primary.txt

# Enable dual mode
DUAL_LLM_ENABLED=true

# Secondary LLM
SECONDARY_LLM_PROVIDER=anthropic
SECONDARY_LLM_MODEL=claude-3-5-sonnet-20241022
SECONDARY_LLM_API_KEY=sk-ant-your_anthropic_key_here
SECONDARY_LLM_PROMPT=prompts/medical_triage_secondary.txt
```

**Cloud + Local (Cost Optimization):**
```bash
# Primary LLM (Cloud)
DEFAULT_LLM_PROVIDER=openai
DEFAULT_LLM_MODEL=gpt-5-mini
DEFAULT_LLM_API_KEY=sk-your_openai_key_here

# Enable dual mode
DUAL_LLM_ENABLED=true

# Secondary LLM (Local)
SECONDARY_LLM_PROVIDER=generic
SECONDARY_LLM_MODEL=qwen2.5:7b
SECONDARY_LLM_BASE_URL=http://localhost:11434/v1
SECONDARY_LLM_API_KEY=not_required
SECONDARY_LLM_PROMPT=prompts/medical_triage_experimental.txt
```

## Acknowledgments

This project was built with the assistance of:

- **Claude Sonnet 4.5** via [Claude Code](https://claude.com/claude-code)
- **GPT-4** for ideation and guidance

## License

MIT License - see [LICENSE](LICENSE) file for details
