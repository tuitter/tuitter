#!/bin/bash
# Tuitter launcher with OAuth support
# Manages both the OAuth server and main app

set -e

echo "🚀 Starting Tuitter..."

# Kill any existing OAuth servers or main.py instances
echo "🧹 Killing any existing instances..."
pkill -9 -f "python3 oauth_server.py" 2>/dev/null || true
pkill -9 -f "python3 main.py" 2>/dev/null || true
lsof -ti:5173 | xargs kill -9 2>/dev/null || true
sleep 0.5

# Cleanup function
cleanup() {
    echo "🧹 Cleaning up..."
    
    # Kill OAuth server
    if [ ! -z "$OAUTH_PID" ] && kill -0 $OAUTH_PID 2>/dev/null; then
        echo "   Stopping OAuth server (PID: $OAUTH_PID)..."
        kill $OAUTH_PID 2>/dev/null || true
        sleep 0.5
        kill -9 $OAUTH_PID 2>/dev/null || true  # Force kill if still alive
    fi
    
    # Also kill any python oauth_server.py processes
    pkill -f "python3 oauth_server.py" 2>/dev/null || true
    pkill -f "python3 main.py" 2>/dev/null || true
    
    # Clean up signal files
    rm -f .restart_signal .main_app_pid
    
    exit 0
}

trap cleanup EXIT INT TERM

# Start OAuth server in background
echo "📡 Starting OAuth server..."
python3 oauth_server.py &
OAUTH_PID=$!
echo "   OAuth server running (PID: $OAUTH_PID)"

# Give server time to bind to port
sleep 1

# Run main app in a loop for auto-restart
while true; do
    # Remove restart signal
    rm -f .restart_signal
    
    echo "▶️  Starting Tuitter app..."
    # Allow main.py to exit non-zero (e.g., SIGTERM 15 during OAuth restart)
    set +e
    python3 main.py
    EXIT_CODE=$?
    set -e
    
    # Check if we should restart (OAuth signal)
    if [ -f ".restart_signal" ]; then
        echo "🔄 OAuth completed - restarting app..."
        sleep 0.5
        continue
    else
        # Normal exit
        echo "👋 App exited (code: $EXIT_CODE)"
        break
    fi
done

# Cleanup handled by trap

