#!/bin/bash
# KG Chat Launcher (Linux/Mac)
# Starts the app in background

# Get script directory
SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
cd "$SCRIPT_DIR/.."

# Run in background
nohup python3 src/main.py > /dev/null 2>&1 &

echo "KG Chat started in background"
echo "To exit: Right-click tray icon → Exit"
