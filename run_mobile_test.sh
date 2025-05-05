#!/bin/bash
# Helper script to run the Flask server for local mobile testing.
# Sets the mobile test mode flag and binds to 0.0.0.0.

export FLASK_MOBILE_TEST_MODE=true
echo "FLASK_MOBILE_TEST_MODE enabled."
echo "Starting Flask server on port 5001, accessible on your local network..."
flask run --host=0.0.0.0 --port=5001
# You could also add --port=5001 here if you prefer that port for mobile testing

# Unset the variable when the script exits (optional, might not work reliably depending on shell)
# trap 'unset FLASK_MOBILE_TEST_MODE' EXIT 