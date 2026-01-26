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

# Use a wrapper script to find and use the correct Python
RUN echo '#!/bin/bash\nPYTHON=$(which python3.10 2>/dev/null || find /usr -name python3.10 2>/dev/null | head -1 || which python3)\nexec $PYTHON server.py' > /app/start.sh && \
    chmod +x /app/start.sh

CMD ["/app/start.sh"]
