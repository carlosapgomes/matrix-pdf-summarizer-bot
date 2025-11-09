#!/usr/bin/env python3
"""
GitHub Webhook Receiver for Matrix PDF Summarizer Bot
Auto-deployment webhook that pulls latest code and restarts the bot service.
"""

import os
import sys
import hmac
import hashlib
import subprocess
import logging
from datetime import datetime
from flask import Flask, request, abort, jsonify
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

app = Flask(__name__)

# Configuration from environment variables
WEBHOOK_SECRET = os.getenv('WEBHOOK_SECRET')
WEBHOOK_PORT = int(os.getenv('WEBHOOK_PORT', 8080))
BOT_SERVICE_NAME = os.getenv('BOT_SERVICE_NAME', 'matrix-pdf-bot')
BOT_REPO_PATH = os.getenv('BOT_REPO_PATH', '/home/matrixbot/matrix-pdf-summarizer-bot')
ALLOWED_REPO = os.getenv('ALLOWED_REPO', 'carlosapgomes/matrix-pdf-summarizer-bot')

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('/var/log/matrix-pdf-bot-webhook.log'),
        logging.StreamHandler(sys.stdout)
    ]
)
logger = logging.getLogger(__name__)

def validate_signature(payload, signature):
    """Validate GitHub webhook signature using HMAC-SHA256"""
    if not WEBHOOK_SECRET:
        logger.warning("WEBHOOK_SECRET not configured - signature validation disabled!")
        return True
    
    if not signature:
        logger.error("No signature provided in request")
        return False
    
    expected_signature = 'sha256=' + hmac.new(
        WEBHOOK_SECRET.encode('utf-8'),
        payload,
        hashlib.sha256
    ).hexdigest()
    
    return hmac.compare_digest(expected_signature, signature)

def execute_deployment():
    """Execute git pull and service restart"""
    try:
        # Change to bot repository directory
        logger.info(f"Changing to repository directory: {BOT_REPO_PATH}")
        os.chdir(BOT_REPO_PATH)
        
        # Git pull to update code
        logger.info("Executing git pull...")
        result = subprocess.run(
            ['git', 'pull', 'origin', 'master'],
            capture_output=True,
            text=True,
            timeout=30
        )
        
        if result.returncode != 0:
            logger.error(f"Git pull failed: {result.stderr}")
            return False, f"Git pull failed: {result.stderr}"
        
        logger.info(f"Git pull output: {result.stdout}")
        
        # Install/update dependencies with uv
        logger.info("Syncing dependencies with uv...")
        uv_result = subprocess.run(
            ['uv', 'sync'],
            capture_output=True,
            text=True,
            timeout=60
        )
        
        if uv_result.returncode != 0:
            logger.warning(f"uv sync had issues: {uv_result.stderr}")
        
        # Restart systemd service
        logger.info(f"Restarting service: {BOT_SERVICE_NAME}")
        restart_result = subprocess.run(
            ['sudo', 'systemctl', 'restart', BOT_SERVICE_NAME],
            capture_output=True,
            text=True,
            timeout=30
        )
        
        if restart_result.returncode != 0:
            logger.error(f"Service restart failed: {restart_result.stderr}")
            return False, f"Service restart failed: {restart_result.stderr}"
        
        logger.info("Deployment completed successfully")
        return True, "Deployment completed successfully"
        
    except subprocess.TimeoutExpired as e:
        logger.error(f"Command timed out: {e}")
        return False, f"Command timed out: {e}"
    except Exception as e:
        logger.error(f"Deployment failed: {e}")
        return False, f"Deployment failed: {e}"

@app.route('/matrix-pdf-bot-webhook/deploy', methods=['POST'])
def handle_webhook():
    """Handle GitHub webhook for repository push events"""
    
    # Validate signature
    signature = request.headers.get('X-Hub-Signature-256')
    if not validate_signature(request.data, signature):
        logger.error("Invalid webhook signature")
        abort(403)
    
    # Parse JSON payload
    try:
        payload = request.get_json()
    except Exception as e:
        logger.error(f"Invalid JSON payload: {e}")
        abort(400)
    
    if not payload:
        logger.error("Empty payload received")
        abort(400)
    
    # Validate this is a push event to master branch
    if payload.get('ref') != 'refs/heads/master':
        logger.info(f"Ignoring push to branch: {payload.get('ref')}")
        return jsonify({'message': 'Not a master branch push, ignoring'}), 200
    
    # Validate repository
    repo_full_name = payload.get('repository', {}).get('full_name')
    if repo_full_name != ALLOWED_REPO:
        logger.error(f"Webhook from unauthorized repository: {repo_full_name}")
        abort(403)
    
    # Log deployment trigger
    commit_sha = payload.get('after', 'unknown')
    commit_message = payload.get('head_commit', {}).get('message', 'No message')
    pusher = payload.get('pusher', {}).get('name', 'unknown')
    
    logger.info(f"Deployment triggered by {pusher}")
    logger.info(f"Commit: {commit_sha[:8]} - {commit_message}")
    
    # Execute deployment
    success, message = execute_deployment()
    
    if success:
        return jsonify({
            'message': 'Deployment successful',
            'commit': commit_sha[:8],
            'timestamp': datetime.now().isoformat()
        }), 200
    else:
        logger.error(f"Deployment failed: {message}")
        return jsonify({
            'error': 'Deployment failed',
            'details': message,
            'commit': commit_sha[:8],
            'timestamp': datetime.now().isoformat()
        }), 500

@app.route('/matrix-pdf-bot-webhook/health', methods=['GET'])
def health_check():
    """Health check endpoint"""
    return jsonify({
        'status': 'healthy',
        'service': 'matrix-pdf-bot-webhook',
        'timestamp': datetime.now().isoformat()
    }), 200

if __name__ == '__main__':
    if not WEBHOOK_SECRET:
        logger.warning("WARNING: WEBHOOK_SECRET not set - webhook security is disabled!")
    
    logger.info(f"Starting webhook server on port {WEBHOOK_PORT}")
    logger.info(f"Monitoring repository: {ALLOWED_REPO}")
    logger.info(f"Bot service name: {BOT_SERVICE_NAME}")
    logger.info(f"Bot repository path: {BOT_REPO_PATH}")
    
    app.run(host='127.0.0.1', port=WEBHOOK_PORT, debug=False)