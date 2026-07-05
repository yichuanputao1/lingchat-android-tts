#!/data/data/com.termux/files/usr/bin/bash
#
# Style-Bert-VITS2 TTS Server - Android/Termux Launch Script
#
# This script starts the Android-optimized TTS API server on Termux.
# It forces CPU mode and handles missing dependencies gracefully.
#
# Usage:
#   ./start_android.sh [options]
#
# Options:
#   --host HOST        Bind address (default: 0.0.0.0)
#   --port PORT        Server port (default: 5000)
#   --dir DIR          Model assets directory (default: model_assets)
#   --no_japanese      Disable Japanese language support
#   --preload_onnx_bert  Preload ONNX BERT models
#   --help             Show this help message
#

set -e

PROJECT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$PROJECT_DIR"

echo "========================================"
echo "  Style-Bert-VITS2 TTS Server (Android)"
echo "========================================"
echo "Project: $PROJECT_DIR"
echo "Date:    $(date)"
echo "Python:  $(python3 --version 2>&1)"
echo "----------------------------------------"

# --- Check Python ---
if ! command -v python3 &>/dev/null; then
    echo "[ERROR] Python3 not found. Install it via: pkg install python"
    exit 1
fi

# --- Check for virtual environment (recommended) ---
if [ -d ".venv" ]; then
    echo "[INFO] Activating virtual environment (.venv)..."
    source .venv/bin/activate
elif [ -d "venv" ]; then
    echo "[INFO] Activating virtual environment (venv)..."
    source venv/bin/activate
fi

# --- Install dependencies if missing (optional) ---
if [ ! -f ".deps_installed" ]; then
    echo ""
    echo "[HINT] First-time setup: Run the following to install dependencies:"
    echo "  pip install -r requirements_android.txt"
    echo ""
    echo "[HINT] For PyTorch CPU-only on Termux:"
    echo "  pip install torch torchvision torchaudio --index-url https://download.pytorch.org/whl/cpu"
    echo ""
    echo "[HINT] To skip this hint next time: touch .deps_installed"
    echo ""
fi

# --- Build command ---
CMD="python3 server_android.py"

# Parse arguments
EXTRA_ARGS=()
while [[ $# -gt 0 ]]; do
    case "$1" in
        --host)   CMD="$CMD --host $2"; shift 2 ;;
        --port)   CMD="$CMD --port $2"; shift 2 ;;
        --dir)    CMD="$CMD --dir $2";  shift 2 ;;
        --no_japanese)       CMD="$CMD --no_japanese";       shift ;;
        --preload_onnx_bert) CMD="$CMD --preload_onnx_bert"; shift ;;
        --help)
            echo ""
            echo "Usage: $0 [options]"
            echo ""
            echo "Options:"
            echo "  --host HOST        Bind address (default: 0.0.0.0)"
            echo "  --port PORT        Server port (default: 5000)"
            echo "  --dir DIR          Model assets directory (default: model_assets)"
            echo "  --no_japanese      Disable Japanese language support"
            echo "  --preload_onnx_bert  Preload ONNX BERT models"
            echo "  --help             Show this help"
            echo ""
            echo "API endpoints once started:"
            echo "  Health:  http://localhost:5000/health"
            echo "  Voice:   http://localhost:5000/voice?text=hello&language=EN"
            echo "  Status:  http://localhost:5000/status"
            echo "  Docs:    http://localhost:5000/docs"
            echo ""
            exit 0
            ;;
        *) EXTRA_ARGS+=("$1"); shift ;;
    esac
done

# Append any unrecognized arguments
if [ ${#EXTRA_ARGS[@]} -gt 0 ]; then
    CMD="$CMD ${EXTRA_ARGS[*]}"
fi

echo ""
echo "Starting server..."
echo "  Command: $CMD"
echo ""

# Run the server
exec $CMD
