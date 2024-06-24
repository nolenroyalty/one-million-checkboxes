#!/bin/bash

# Configuration
REMOTE_USER="ubuntu"
REMOTE_HOST="142.93.76.97"
REMOTE_DIR="/home/ubuntu/"
SSH_KEY="~/.ssh/id_rsa"  # Path to your SSH key

# Local directories and files to sync
LOCAL_DIST="./dist"
LOCAL_SERVER="./server.py"
LOCAL_REQUIREMENTS="./requirements.txt"

# Rsync options
RSYNC_OPTS="-avz --delete"

# Sync dist directory
echo "Syncing dist directory..."
rsync $RSYNC_OPTS -e "ssh -i $SSH_KEY" "$LOCAL_DIST/" "$REMOTE_USER@$REMOTE_HOST:$REMOTE_DIR/dist/"

# Sync server.py
echo "Syncing server.py..."
rsync $RSYNC_OPTS -e "ssh -i $SSH_KEY" "$LOCAL_SERVER" "$REMOTE_USER@$REMOTE_HOST:$REMOTE_DIR/"

# Sync requirements.txt
echo "Syncing requirements.txt..."
rsync $RSYNC_OPTS -e "ssh -i $SSH_KEY" "$LOCAL_REQUIREMENTS" "$REMOTE_USER@$REMOTE_HOST:$REMOTE_DIR/"

echo "Sync completed!"
echo "Deployment finished!"
