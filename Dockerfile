# Use official Python 3.10 image instead of ifcopenshell image
# This avoids Python version conflicts
FROM --platform=linux/amd64 python:3.10-slim

# Install minimal system dependencies
# Note: For server-side IFC processing, OpenGL is typically not needed
# Only install build-essential if IfcOpenShell needs to compile extensions
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
        build-essential \
        && \
    rm -rf /var/lib/apt/lists/*

# Install Python dependencies including IfcOpenShell via pip
RUN pip install --no-cache-dir \
    flask \
    flask-cors \
    numpy \
    ifcopenshell

# Create the API server script
WORKDIR /app

# Copy the server file and scripts directory
COPY server.py .
COPY scripts/ ./scripts/

# Expose port (Render will set PORT env var)
ENV PORT=5001

# Use python3 (Python 3.10 is the default in python:3.10-slim)
CMD ["python3", "server.py"]
