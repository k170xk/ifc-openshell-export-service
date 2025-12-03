FROM --platform=linux/amd64 aecgeeks/ifcopenshell:latest

# Switch to root to install packages  
USER root

# The base image has Python 3.8, but IfcOpenShell needs Python 3.10
# Add deadsnakes PPA to get Python 3.10 packages for Ubuntu 20.04
# Use --no-install-recommends to avoid pulling in GUI dependencies
RUN DEBIAN_FRONTEND=noninteractive apt-get update && \
    DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends software-properties-common curl && \
    DEBIAN_FRONTEND=noninteractive add-apt-repository ppa:deadsnakes/ppa -y && \
    DEBIAN_FRONTEND=noninteractive apt-get update && \
    DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends python3.10 && \
    curl -sS https://bootstrap.pypa.io/get-pip.py | python3.10 && \
    python3.10 -m pip install --no-cache-dir flask flask-cors numpy && \
    rm -rf /var/lib/apt/lists/*

# Create the API server script
WORKDIR /app

# Copy the server file and scripts directory
COPY server.py .
COPY scripts/ ./scripts/

# Expose port (Render will set PORT env var)
ENV PORT=5001

# Use python3.10 explicitly to match IfcOpenShell
CMD ["python3.10", "server.py"]
