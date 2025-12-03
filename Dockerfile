FROM --platform=linux/amd64 aecgeeks/ifcopenshell:latest

# Switch to root to install packages  
USER root

# The base image has Python 3.8, but IfcOpenShell needs Python 3.10
# Install Python 3.10 and its pip, then use it for everything
RUN apt-get update && \
    apt-get install -y python3.10 python3.10-venv python3.10-dev && \
    python3.10 -m ensurepip --upgrade && \
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
