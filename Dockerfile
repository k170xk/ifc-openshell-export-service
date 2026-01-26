FROM --platform=linux/amd64 aecgeeks/ifcopenshell:latest

# Switch to root to install packages
USER root

# Install Python 3.10 from deadsnakes PPA and find its location
RUN apt-get update && \
    apt-get install -y --no-install-recommends software-properties-common && \
    add-apt-repository ppa:deadsnakes/ppa -y && \
    apt-get update && \
    apt-get install -y --no-install-recommends python3.10 && \
    rm -rf /var/lib/apt/lists/*

# Find Python 3.10 executable and install pip
# Python 3.10 from deadsnakes typically installs to /usr/bin/python3.10
RUN /usr/bin/python3.10 -m ensurepip --upgrade || \
    (curl -sS https://bootstrap.pypa.io/get-pip.py | /usr/bin/python3.10) || \
    (apt-get update && apt-get install -y python3-pip && rm -rf /var/lib/apt/lists/*)

# Install Flask for the API server
RUN /usr/bin/python3.10 -m pip install --no-cache-dir flask flask-cors numpy || \
    python3 -m pip install --no-cache-dir flask flask-cors numpy

# Create the API server script
WORKDIR /app

# Copy the server file and scripts directory
COPY server.py .
COPY scripts/ ./scripts/

# Expose port (Render will set PORT env var)
ENV PORT=5001

# Try python3.10 first, fallback to python3
CMD ["/usr/bin/python3.10", "server.py"]
