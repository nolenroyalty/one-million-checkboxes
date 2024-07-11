#!/bin/bash

set -e
set -x

PYTHON_SCRIPT="/home/ubuntu/freeze_bits_and_compute_stats.py"
TEMP_OUTPUT="/tmp/some-numbers.html"
FINAL_OUTPUT="/var/www/generated-content/some-numbers.html"
CONTENT_DIR="/var/www/generated-content"
STAGING_OUTPUT="/tmp/some-numbers-staging.html"
UBUNTU_USER="ubuntu"
WWW_USER="www-data"
WWW_GROUP="www-data"
VENV_PATH="/home/ubuntu/venv/bin/activate"

if [ "$(id -u)" -ne 0 ]; then
    echo "This script must be run as root" >&2
    exit 1
fi

cleanup() {
    rm -f "$TEMP_OUTPUT" "$STAGING_OUTPUT"
}
trap cleanup EXIT

mkdir -p "$CONTENT_DIR"
chown "$WWW_USER:$WWW_GROUP" "$CONTENT_DIR"
chmod 775 "$CONTENT_DIR"

sudo -u "$UBUNTU_USER" bash -c "
source $VENV_PATH
source /home/ubuntu/.redis-creds
python $PYTHON_SCRIPT
"

if [ ! -f "$TEMP_OUTPUT" ]; then
    echo "Error: Python script did not generate the output file." >&2
    exit 1
fi

cp "$TEMP_OUTPUT" "$STAGING_OUTPUT"

chown "$WWW_USER:$WWW_GROUP" "$STAGING_OUTPUT"
chmod 644 "$STAGING_OUTPUT"

mv "$STAGING_OUTPUT" "$FINAL_OUTPUT"

echo "Stats file updated successfully at $FINAL_OUTPUT"
