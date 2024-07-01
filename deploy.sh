#!/bin/bash

# Configuration
REMOTE_USER="ubuntu"
#REMOTE_HOST="142.93.76.97"
REMOTE_DIR="/home/ubuntu/"
WWW_DIR="/var/www/one-million-checkboxes"
SSH_KEY="~/.ssh/id_rsa"  # Path to your SSH key

# Local directories and files to sync
LOCAL_DIST="./dist"
LOCAL_SERVER="./server.py"
LOCAL_GUNICORN="./start_gunicorn.sh"
LOCAL_REQUIREMENTS="./requirements.txt"
LOCAL_CLEANUPSH="./cleanup.sh"
LOCAL_CLEANUPPY="./cleanup_old_logs.py"
CHECKBOX_BIN="/tmp/checkbox"
echo "building..."
GOOS=linux GOARCH=amd64 go build -o $CHECKBOX_BIN main.go
echo $(md5sum $CHECKBOX_BIN)
# Rsync options
RSYNC_OPTS="-avz --delete"
GO_SYS_UNIT="go-one-million.service"

for REMOTE_HOST in bak.onemil 2bak.onemil 3bak.onemil 4bak.onemil 5bak.onemil 6bak.onemil 7bak.onemil 8bak.onemil
#for REMOTE_HOST in onemil
#for REMOTE_HOST in 2bak.onemil
do
    echo $REMOTE_HOST

    #REMOTE_HOST="8bak.onemil"

    ### Sync dist directory
    #echo "Syncing dist directory..."
    #rsync $RSYNC_OPTS -e "ssh -i $SSH_KEY" "$LOCAL_DIST/" "root@$REMOTE_HOST:$WWW_DIR/"
    #ssh -i $SSH_KEY root@${REMOTE_HOST} -- chown -R www-data:www-data ${WWW_DIR}
    #ssh -i $SSH_KEY root@${REMOTE_HOST} -- chmod -R 755 ${WWW_DIR}
    #echo "syncing new server binary..."

    ssh root@$REMOTE_HOST "systemctl stop $GO_SYS_UNIT"
    rsync $RSYNC_OPTS -e "ssh -i $SSH_KEY" "$CHECKBOX_BIN" "$REMOTE_USER@$REMOTE_HOST:$REMOTE_DIR/"
    ssh root@$REMOTE_HOST "systemctl start $GO_SYS_UNIT"


    ##Sync server.py
    #echo "Syncing server.py..."
    #rsync $RSYNC_OPTS -e "ssh -i $SSH_KEY" "$LOCAL_SERVER" "$REMOTE_USER@$REMOTE_HOST:$REMOTE_DIR/"

    # ##Sync server.py
    # echo "Syncing server.py..."
    # rsync $RSYNC_OPTS -e "ssh -i $SSH_KEY" "$LOCAL_SERVER" "$REMOTE_USER@$REMOTE_HOST:$REMOTE_DIR/"

    # ### Sync cleanup.sh
    # echo "Syncing cleanup.sh..."
    # rsync $RSYNC_OPTS -e "ssh -i $SSH_KEY" "$LOCAL_CLEANUPSH" "$REMOTE_USER@$REMOTE_HOST:$REMOTE_DIR/"

    # #### Sync cleanup_old_logs.py
    # echo "Syncing cleanup_old_logs.py..."
    # rsync $RSYNC_OPTS -e "ssh -i $SSH_KEY" "$LOCAL_CLEANUPPY" "$REMOTE_USER@$REMOTE_HOST:$REMOTE_DIR/"

    # #### Sync start_gunicorn.sh
    # echo "Syncing start_gunicorn.sh..."
    # rsync $RSYNC_OPTS -e "ssh -i $SSH_KEY" "$LOCAL_GUNICORN" "$REMOTE_USER@$REMOTE_HOST:$REMOTE_DIR/"

    # #### Sync requirements.txt
    # echo "Syncing requirements.txt..."
    # rsync $RSYNC_OPTS -e "ssh -i $SSH_KEY" "$LOCAL_REQUIREMENTS" "$REMOTE_USER@$REMOTE_HOST:$REMOTE_DIR/"

    # #### Sync gunicorn_restart
    # echo "Syncing gunicorn_restart..."
    # rsync $RSYNC_OPTS -e "ssh -i $SSH_KEY" "./gunicorn_restart.sh" "$REMOTE_USER@$REMOTE_HOST:$REMOTE_DIR/"

    # echo "Sync completed!"
    # echo "Deployment finished!"
done
