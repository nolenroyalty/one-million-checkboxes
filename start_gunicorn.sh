#!/bin/bash

NUM_PROCESSES=4  # Adjust this based on your server's capabilities
BASE_PORT=5001

for i in $(seq 0 $((NUM_PROCESSES-1)))
do
    PORT=$((BASE_PORT + i))
    gunicorn --worker-class eventlet --workers 1 --threads 4 --bind 127.0.0.1:$PORT server:app &
done

PROCESS_JOBS='true' gunicorn --worker-class eventlet --workers 1 server:app &

wait
