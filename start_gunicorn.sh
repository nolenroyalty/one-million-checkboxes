#!/bin/bash

BASE_PORT=5001

for i in 0 1 2 3 4 5
do
    PORT=$((BASE_PORT + i))
    gunicorn --worker-class eventlet --workers 1 --threads 4 --bind 127.0.0.1:$PORT server:app &
done

PROCESS_JOBS='true' gunicorn --worker-class eventlet --workers 1 server:app &

wait
