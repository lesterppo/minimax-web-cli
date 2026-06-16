#!/bin/bash
# Start all AI web CLI page servers in background
# Usage: ./start_servers.sh [stop|status]

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
VENV_PYTHON="$HOME/.hermes/hermes-agent/.venv/bin/python"

start_one() {
    local name=$1 port=$2 script=$3
    if curl -s --max-time 2 "http://127.0.0.1:$port/health" > /dev/null 2>&1; then
        echo "  $name: already running on :$port"
        return 0
    fi
    echo "  $name: starting..."
    nohup "$VENV_PYTHON" "$script" > "$HOME/.chrome-daemon/${name}_server.log" 2>&1 &
    # Wait for health
    for i in $(seq 1 20); do
        sleep 1
        if curl -s --max-time 1 "http://127.0.0.1:$port/health" > /dev/null 2>&1; then
            echo "  $name: ready on :$port"
            return 0
        fi
    done
    echo "  $name: FAILED to start"
    return 1
}

stop_one() {
    local name=$1 port=$2
    curl -s --max-time 2 "http://127.0.0.1:$port/stop" > /dev/null 2>&1
    echo "  $name: stopped"
}

case "${1:-start}" in
    stop)
        echo "Stopping all servers..."
        stop_one minimax 9871
        stop_one mimo 9872
        stop_one qwen 9873
        ;;
    status)
        for s in "minimax:9871" "mimo:9872" "qwen:9873"; do
            name=${s%:*}; port=${s#*:}
            if curl -s --max-time 1 "http://127.0.0.1:$port/health" > /dev/null 2>&1; then
                echo "  $name: ✓ running"
            else
                echo "  $name: ✗ down"
            fi
        done
        ;;
    *)
        echo "Starting all servers..."
        mkdir -p "$HOME/.chrome-daemon"
        start_one minimax 9871 "$SCRIPT_DIR/minimax/minimax_server.py"
        start_one mimo     9872 "$SCRIPT_DIR/mimo/mimo_server.py"
        start_one qwen     9873 "$SCRIPT_DIR/qwen/qwen_server.py"
        echo "Done."
        ;;
esac
