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
    ifcopenshell \
    gunicorn

# Create the API server script
WORKDIR /app

# Copy the server file and scripts directory
COPY server.py .
COPY scripts/ ./scripts/

# Expose port (Render will set PORT env var)
ENV PORT=5001

# Use gunicorn for production WSGI server
# Gunicorn will automatically use the PORT environment variable.
# gthread worker: the accept loop keeps heartbeating while a long export runs on a
# thread, and --timeout matches Render's 100-minute edge limit so a large site is
# never killed mid-write. /dev/shm keeps heartbeat files off the (slow) disk.
CMD exec gunicorn --bind 0.0.0.0:${PORT:-5001} --worker-class gthread --workers 2 --threads 4 --timeout 6000 --graceful-timeout 60 --keep-alive 75 --worker-tmp-dir /dev/shm --access-logfile - --error-logfile - server:app
