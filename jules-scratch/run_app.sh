#!/bin/bash
set -e

# 0. Kill any existing gunicorn processes
echo "--- Killing existing Gunicorn processes ---"
pkill -f gunicorn || true
sleep 2 # Give a moment for the processes to die

# 1. Start the gunicorn server in the background
echo "--- Starting Gunicorn ---"
gunicorn --chdir Bot-GPT --bind 0.0.0.0:5001 --workers 1 --threads 8 'app:create_app()' --timeout 120 > app.log 2>&1 &
GUNICORN_PID=$!
echo "Gunicorn started with PID $GUNICORN_PID"
sleep 15 # Give the server a moment to start

# 2. Run the Playwright tests
echo "--- Running Playwright tests ---"
pytest jules-scratch/verification/test_settings.py

# 3. Stop the Gunicorn server
echo "--- Stopping Gunicorn ---"
kill $GUNICORN_PID
echo "Gunicorn stopped."

echo "--- Test run complete ---"
