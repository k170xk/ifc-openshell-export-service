FROM --platform=linux/amd64 aecgeeks/ifcopenshell:latest

# Switch to root to install packages
USER root

# Install Python 3.10 from deadsnakes PPA and verify installation
RUN apt-get update && \
    apt-get install -y --no-install-recommends software-properties-common && \
    add-apt-repository ppa:deadsnakes/ppa -y && \
    apt-get update && \
    apt-get install -y --no-install-recommends python3.10 python3.10-distutils && \
    rm -rf /var/lib/apt/lists/* && \
    # Verify Python 3.10 is installed
    python3.10 --version || (echo "ERROR: python3.10 not found after installation" && ls -la /usr/bin/python* && exit 1)

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
