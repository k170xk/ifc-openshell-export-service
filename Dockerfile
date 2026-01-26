FROM --platform=linux/amd64 aecgeeks/ifcopenshell:latest

# Switch to root to install packages
USER root

# IfcOpenShell in base image is built for Python 3.10, but base only has Python 3.8
# Install Python 3.10 and pip for Python 3.10
RUN apt-get update && \
    apt-get install -y --no-install-recommends software-properties-common && \
    add-apt-repository ppa:deadsnakes/ppa -y && \
    apt-get update && \
    apt-get install -y --no-install-recommends python3.10 python3.10-distutils && \
    curl -sS https://bootstrap.pypa.io/get-pip.py | python3.10 && \
    rm -rf /var/lib/apt/lists/*

# Install Flask for the API server using Python 3.10
RUN python3.10 -m pip install --no-cache-dir flask flask-cors numpy

# Create the API server script
WORKDIR /app

# Copy the server file and scripts directory
COPY server.py .
COPY scripts/ ./scripts/

# Expose port (Render will set PORT env var)
ENV PORT=5001

# Use python3.10 to match IfcOpenShell build
CMD ["python3.10", "server.py"]
