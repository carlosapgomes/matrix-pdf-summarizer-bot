# GitHub Webhook Auto-Deployment

This directory contains a GitHub webhook receiver that automatically deploys updates to the Matrix PDF Summarizer Bot when you push to the master branch.

## How It Works

1. **GitHub Push**: You push code to the master branch
2. **Webhook Trigger**: GitHub sends a POST request to your server
3. **Validation**: Server validates the webhook signature for security
4. **Deployment**: Server runs `git pull` and restarts the bot service
5. **Logging**: All activities are logged for monitoring

## Files Overview

- `webhook_server.py` - Main webhook receiver application
- `matrix-pdf-bot-webhook.service` - Systemd service configuration
- `install.sh` - Automated installation script
- `.env.example` - Environment configuration template
- `pyproject.toml` - Python project configuration and dependencies
- `traefik-config.yml` - Traefik proxy configuration
- `traefik-integration-notes.md` - Detailed Traefik integration guide

## Quick Setup

### 1. Install the Webhook Service

```bash
# Run as root
cd webhook-deployment
sudo ./install.sh
```

### 2. Configure Environment

```bash
# Copy and edit configuration
cp .env.example .env
nano .env
```

Required configuration:

```bash
# Generate with: openssl rand -hex 32
WEBHOOK_SECRET=your-secret-key-here

# Choose an available port
WEBHOOK_PORT=8080

# Your bot's systemd service name
BOT_SERVICE_NAME=matrix-pdf-bot

# Path to your bot repository
BOT_REPO_PATH=/home/matrixbot/matrix-pdf-summarizer-bot

# GitHub repository (format: username/repo-name)
ALLOWED_REPO=carlosapgomes/matrix-pdf-summarizer-bot
```

### 3. Generate Webhook Secret

```bash
# Generate a secure random secret
openssl rand -hex 32
```

Copy this secret - you'll need it for both `.env` and GitHub configuration.

### 4. Configure Traefik (Required)

See `traefik-integration-notes.md` for detailed Traefik integration instructions.

**Quick option** - Add to your matrix-docker-ansible-deploy vars.yml:

```yaml
matrix_playbook_traefik_custom_proxy_configuration: |
  - name: matrix-pdf-bot-webhook
    router:
      rule: "Host(`{{ matrix_server_fqdn_matrix }}`) && PathPrefix(`/matrix-pdf-bot-webhook`)"
      service: matrix-pdf-bot-webhook-service
      middlewares:
        - matrix-pdf-bot-webhook-headers
      tls:
        certResolver: "{{ devture_traefik_certResolver_primary }}"
    service:
      loadBalancer:
        servers:
          - url: "http://127.0.0.1:8080"
    middleware:
      headers:
        customRequestHeaders:
          X-Forwarded-Proto: "https"
```

### 5. Start the Service

```bash
# Start and enable the webhook service
sudo systemctl start matrix-pdf-bot-webhook
sudo systemctl enable matrix-pdf-bot-webhook

# Check status
sudo systemctl status matrix-pdf-bot-webhook

# View logs
sudo journalctl -u matrix-pdf-bot-webhook -f
```

### 6. Configure GitHub Webhook

1. Go to your GitHub repository
2. Navigate to **Settings** → **Webhooks**
3. Click **Add webhook**
4. Configure:
   - **Payload URL**: `https://matrix.yourdomain.com/matrix-pdf-bot-webhook/deploy`
   - **Content type**: `application/json`
   - **Secret**: (the secret you generated in step 3)
   - **Which events**: Select "Just the push event"
   - **Active**: ✓ Checked

### 7. Test the Setup

```bash
# Test health endpoint
curl https://matrix.yourdomain.com/matrix-pdf-bot-webhook/health

# Should return:
# {"status": "healthy", "service": "matrix-pdf-bot-webhook", "timestamp": "..."}
```

Now push a test commit to master branch and check the logs:

```bash
sudo journalctl -u matrix-pdf-bot-webhook -f
```

## Security Features

- **HMAC-SHA256 Signature Validation**: Ensures requests are from GitHub
- **Repository Validation**: Only accepts webhooks from specified repository
- **Branch Filtering**: Only processes pushes to master branch
- **Localhost Binding**: Webhook server only listens on 127.0.0.1
- **HTTPS Only**: Traefik provides TLS termination
- **Sudoers Configuration**: Limited sudo permissions for service restart only

## Monitoring & Troubleshooting

### Check Service Status

```bash
sudo systemctl status matrix-pdf-bot-webhook
```

### View Logs

```bash
# Live logs
sudo journalctl -u matrix-pdf-bot-webhook -f

# Recent logs
sudo journalctl -u matrix-pdf-bot-webhook -n 50

# Webhook-specific log file
tail -f /var/log/matrix-pdf-bot-webhook.log
```

### Test Endpoints

```bash
# Health check
curl https://matrix.yourdomain.com/matrix-pdf-bot-webhook/health

# Test from GitHub (check webhook deliveries in GitHub settings)
```

### Common Issues

1. **"Invalid webhook signature"**

   - Check WEBHOOK_SECRET matches GitHub webhook secret
   - Verify secret is properly set in .env file

2. **"Service restart failed"**

   - Check if matrixbot user has sudo permissions
   - Verify BOT_SERVICE_NAME is correct
   - Check if the bot service exists: `systemctl list-units | grep matrix`

3. **"Git pull failed"**

   - Verify BOT_REPO_PATH exists and is a git repository
   - Check git remote configuration
   - Ensure matrixbot user has read access to repository

4. **Connection refused**
   - Check if service is running: `systemctl status webhook-deployment`
   - Verify port configuration in .env
   - Check Traefik configuration

### Manual Deployment Test

You can test the deployment process manually:

```bash
# Switch to bot directory
cd /home/matrixbot/matrix-pdf-summarizer-bot

# Test git pull
sudo -u matrixbot git pull origin master

# Test dependency sync
sudo -u matrixbot uv sync

# Test service restart
sudo systemctl restart matrix-pdf-bot

# Check bot status
sudo systemctl status matrix-pdf-bot
```

## Uninstall

```bash
# Stop and disable service
sudo systemctl stop matrix-pdf-bot-webhook
sudo systemctl disable matrix-pdf-bot-webhook

# Remove service file
sudo rm /etc/systemd/system/matrix-pdf-bot-webhook.service
sudo systemctl daemon-reload

# Remove sudoers entry (optional)
sudo visudo
# Remove line: matrixbot ALL=(ALL) NOPASSWD: /bin/systemctl restart matrix-pdf-bot

# Remove webhook directory (optional)
# rm -rf webhook-deployment
```

## Customization

### Change Deployment Branch

Edit `webhook_server.py` line 89:

```python
if payload.get('ref') != 'refs/heads/your-branch':
```

### Add Additional Commands

Edit the `execute_deployment()` function in `webhook_server.py` to add custom deployment steps like running tests, building assets, etc.

### Change Log Location

Edit `webhook-deployment.service` and update `ReadWritePaths`:

```ini
ReadWritePaths=/your/custom/log/path
```

## Support

If you encounter issues:

1. Check the logs first (see Monitoring section)
2. Verify all configuration steps
3. Test individual components (git pull, service restart)
4. Check GitHub webhook delivery logs
5. Ensure all required permissions are set

