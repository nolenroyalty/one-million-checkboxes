#!/bin/bash

BASE_PORT=5001

for i in 0 1 2 3
do
    PORT=$((BASE_PORT + i))
    gunicorn --worker-class eventlet --workers 1 --threads 3 --bind 0.0.0.0:$PORT server:app &
done

PROCESS_JOBS='true' gunicorn --worker-class eventlet --workers 1 server:app &

wait
