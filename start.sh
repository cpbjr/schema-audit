#!/bin/bash

# Function to handle headers
header() {
    echo -e "\n\033[1;34m>>> $1\033[0m"
}

header "Starting Schema Audit Web App..."

# Activate venv if it exists
if [ -d "venv" ]; then
    source venv/bin/activate
fi

# Trap Ctrl+C to kill both processes
trap 'kill $API_PID $FRONTEND_PID; exit' SIGINT

# Start Backend
header "Launching Backend (Port 8000)..."
uvicorn api:app --port 8000 --reload &
API_PID=$!

# Start Frontend
header "Launching Frontend (Port 5173)..."
cd client && npm run dev &
FRONTEND_PID=$!

# Wait for both
wait
