#!/bin/bash

# jitter
x=$((RANDOM % 300)) 
echo "sleeping for $x"
sleep "$x"

count_running_servers() {
    ps aux | grep gunicorn | grep -oP 'bind \K0\.0\.0\.0:\d+' | sort | uniq | wc -l
}

running_servers=$(count_running_servers)

if [ $running_servers -lt 3 ]; then
    echo "Less than 3 servers running. Restarting all servers..."
    
    sudo systemctl stop one-million-checkboxes.service
    
    sleep 10
    
    sudo systemctl start one-million-checkboxes.service
    
    echo "Servers restarted."
else
    echo "At least 3 servers are running. No action needed."
fi
