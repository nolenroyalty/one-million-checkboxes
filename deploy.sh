#!/bin/bash

# Configuration
REMOTE_USER="ubuntu"
REMOTE_HOST="142.93.76.97"
REMOTE_DIR="/home/ubuntu/"
WWW_DIR="/var/www/one-million-checkboxes"
SSH_KEY="~/.ssh/id_rsa"  # Path to your SSH key

# Local directories and files to sync
LOCAL_DIST="./dist"
LOCAL_SERVER="./server.py"
LOCAL_GUNICORN="./start_gunicorn.sh"
LOCAL_REQUIREMENTS="./requirements.txt"

# Rsync options
RSYNC_OPTS="-avz --delete"

# Sync dist directory
echo "Syncing dist directory..."
rsync $RSYNC_OPTS -e "ssh -i $SSH_KEY" "$LOCAL_DIST/" "root@$REMOTE_HOST:$WWW_DIR/"
ssh -i $SSH_KEY root@${REMOTE_HOST} -- chown -R www-data:www-data ${WWW_DIR}
ssh -i $SSH_KEY root@${REMOTE_HOST} -- chmod -R 755 ${WWW_DIR}

# Sync server.py
echo "Syncing server.py..."
rsync $RSYNC_OPTS -e "ssh -i $SSH_KEY" "$LOCAL_SERVER" "$REMOTE_USER@$REMOTE_HOST:$REMOTE_DIR/"

# Sync start_gunicorn.sh
echo "Syncing start_gunicorn.sh..."
rsync $RSYNC_OPTS -e "ssh -i $SSH_KEY" "$LOCAL_GUNICORN" "$REMOTE_USER@$REMOTE_HOST:$REMOTE_DIR/"

# Sync requirements.txt
echo "Syncing requirements.txt..."
rsync $RSYNC_OPTS -e "ssh -i $SSH_KEY" "$LOCAL_REQUIREMENTS" "$REMOTE_USER@$REMOTE_HOST:$REMOTE_DIR/"

echo "Sync completed!"
echo "Deployment finished!"
