FROM --platform=linux/amd64 aecgeeks/ifcopenshell:latest

# Switch to root to install packages
USER root

# Install Python 3.10 from deadsnakes PPA
RUN apt-get update && \
    apt-get install -y --no-install-recommends software-properties-common && \
    add-apt-repository ppa:deadsnakes/ppa -y && \
    apt-get update && \
    apt-get install -y --no-install-recommends python3.10 && \
    rm -rf /var/lib/apt/lists/*

# Find where Python 3.10 was installed and create symlink if needed
RUN PYTHON310=$(which python3.10 2>/dev/null || find /usr -name python3.10 2>/dev/null | head -1) && \
    if [ -z "$PYTHON310" ]; then \
        echo "Python 3.10 not found, checking alternatives..."; \
        PYTHON310=$(ls /usr/bin/python3.10* 2>/dev/null | head -1 || echo ""); \
    fi && \
    if [ -n "$PYTHON310" ]; then \
        echo "Found Python 3.10 at: $PYTHON310"; \
        $PYTHON310 -m ensurepip --upgrade || \
        (apt-get update && apt-get install -y curl && curl -sS https://bootstrap.pypa.io/get-pip.py | $PYTHON310); \
        $PYTHON310 -m pip install --no-cache-dir flask flask-cors numpy; \
    else \
        echo "Python 3.10 not found, using python3"; \
        apt-get update && apt-get install -y python3-pip && rm -rf /var/lib/apt/lists/*; \
        python3 -m pip install --no-cache-dir flask flask-cors numpy; \
    fi

# Create the API server script
WORKDIR /app

# Copy the server file and scripts directory
COPY server.py .
COPY scripts/ ./scripts/

# Expose port (Render will set PORT env var)
ENV PORT=5001

# Create a wrapper script to find and use Python 3.10
RUN cat > /app/start.sh << 'EOF'
#!/bin/bash
set -e

# Try to find Python 3.10
PYTHON310=""
if command -v python3.10 >/dev/null 2>&1; then
    PYTHON310=$(command -v python3.10)
elif [ -f /usr/bin/python3.10 ]; then
    PYTHON310=/usr/bin/python3.10
else
    PYTHON310=$(find /usr -name python3.10 -type f 2>/dev/null | head -1)
fi

if [ -n "$PYTHON310" ] && [ -x "$PYTHON310" ]; then
    echo "Using Python 3.10 at: $PYTHON310"
    exec "$PYTHON310" /app/server.py
else
    echo "ERROR: Python 3.10 not found! IfcOpenShell requires Python 3.10."
    echo "Available Python versions:"
    ls -la /usr/bin/python* 2>/dev/null || true
    exit 1
fi
EOF
RUN chmod +x /app/start.sh

CMD ["/app/start.sh"]
