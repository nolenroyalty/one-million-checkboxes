#!/bin/bash

# Set up the environment
export HOME=/home/ubuntu
export PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin

source /home/ubuntu/venv/bin/activate
source /home/ubuntu/.redis-creds
export PYTHONPATH=/home/ubuntu:$PYTHONPATH
python /home/ubuntu/cleanup_old_logs.py

# Deactivate the virtual environment
deactivate
