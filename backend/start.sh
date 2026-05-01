#!/bin/bash
# Start Market Dashboard Backend
cd "$(dirname "$0")"

echo "========================================="
echo "  Market Dashboard API - Starting..."
echo "========================================="

# Check python
if ! command -v python3 &>/dev/null; then
  echo "ERROR: python3 not found"
  exit 1
fi

# Install dependencies if needed
if [ ! -d ".venv" ]; then
  echo "Creating virtual environment..."
  python3 -m venv .venv
fi

source .venv/bin/activate

echo "Installing dependencies..."
pip install -r requirements.txt -q

echo ""
echo "API running at: http://localhost:8000"
echo "Docs at:        http://localhost:8000/docs"
echo "Press Ctrl+C to stop"
echo ""

uvicorn main:app --host 0.0.0.0 --port 8000 --reload
