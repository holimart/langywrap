#!/bin/bash
# Run Claude Code in Docker sandbox
# Part of Phase 3: Execution Isolation

set -e

PROJECT_DIR="${1:-$(pwd)}"
RUNTIME="${2:-runc}"  # Options: runc, runsc (gVisor)

echo "======================================"
echo "Starting Claude Sandbox"
echo "======================================"
echo "Project: $PROJECT_DIR"
echo "Runtime: $RUNTIME"
echo ""

# Check if Docker is running
if ! docker info > /dev/null 2>&1; then
    echo "❌ Docker is not running. Please start Docker and try again."
    exit 1
fi

# Build sandbox image if it doesn't exist
if ! docker image inspect claude-sandbox > /dev/null 2>&1; then
    echo "Building sandbox image..."
    SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
    docker build -f "$SCRIPT_DIR/Dockerfile.sandbox" -t claude-sandbox "$SCRIPT_DIR"
fi

# Run container
echo "Starting container..."
docker run -it --rm \
    --name claude-sandbox \
    --runtime="$RUNTIME" \
    --network=none \
    --memory=4g \
    --cpus=2 \
    --pids-limit=100 \
    --read-only \
    --tmpfs /tmp:size=500m \
    --security-opt=no-new-privileges \
    -v "$PROJECT_DIR:/workspace" \
    -w /workspace \
    claude-sandbox \
    bash

echo ""
echo "✅ Sandbox session ended"
