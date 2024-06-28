#!/bin/bash

# Function to count running servers
count_running_servers() {
    ps aux | grep gunicorn | grep -oP 'bind \K0\.0\.0\.0:\d+' | sort | uniq | wc -l
}

# Main logic
running_servers=$(count_running_servers)

if [ $running_servers -lt 3 ]; then
    echo "Less than 3 servers running. Restarting all servers..."
    
    # Stop the service
    sudo systemctl stop one-million-checkboxes.service
    
    # Wait for 10 seconds
    sleep 10
    
    # Start the service
    sudo systemctl start one-million-checkboxes.service
    
    echo "Servers restarted."
else
    echo "At least 3 servers are running. No action needed."
fi
