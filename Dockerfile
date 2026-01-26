FROM --platform=linux/amd64 aecgeeks/ifcopenshell:latest

# Switch to root to install packages
USER root

# Install Python 3.10 from deadsnakes PPA
# Try installing python3.10-minimal first, then full python3.10 if needed
RUN apt-get update && \
    apt-get install -y --no-install-recommends software-properties-common && \
    add-apt-repository ppa:deadsnakes/ppa -y && \
    apt-get update && \
    (apt-get install -y --no-install-recommends python3.10-minimal python3.10 || \
     apt-get install -y --no-install-recommends python3.10) && \
    rm -rf /var/lib/apt/lists/* && \
    # Verify Python 3.10 is installed and find its location
    (python3.10 --version || \
     /usr/bin/python3.10 --version || \
     (PY310=$(find /usr -name python3.10 -type f 2>/dev/null | head -1) && \
      if [ -n "$PY310" ]; then \
        echo "Found Python 3.10 at: $PY310" && \
        ln -sf "$PY310" /usr/bin/python3.10 && \
        python3.10 --version; \
      else \
        echo "ERROR: python3.10 not found after installation" && \
        echo "Available packages:" && \
        apt-cache search python3.10 | head -20 && \
        ls -la /usr/bin/python* && \
        exit 1; \
      fi))

# Install pip for Python 3.10
RUN python3.10 -m ensurepip --upgrade || \
    (apt-get update && apt-get install -y curl && curl -sS https://bootstrap.pypa.io/get-pip.py | python3.10 && rm -rf /var/lib/apt/lists/*)

# Install Flask for the API server using Python 3.10
RUN python3.10 -m pip install --no-cache-dir flask flask-cors numpy

# Create the API server script
WORKDIR /app

# Copy the server file and scripts directory
COPY server.py .
COPY scripts/ ./scripts/

# Expose port (Render will set PORT env var)
ENV PORT=5001

# Use python3.10 directly (should be available after installation)
CMD ["python3.10", "server.py"]
