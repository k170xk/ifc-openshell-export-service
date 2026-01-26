FROM --platform=linux/amd64 aecgeeks/ifcopenshell:latest

# Switch to root to install packages
USER root

# Install pip first (base image has python3 but no pip)
RUN apt-get update && \
    apt-get install -y --no-install-recommends python3-pip && \
    rm -rf /var/lib/apt/lists/*

# Install Flask for the API server
RUN pip3 install --no-cache-dir flask flask-cors numpy

# Create the API server script
WORKDIR /app

# Copy the server file and scripts directory
COPY server.py .
COPY scripts/ ./scripts/

# Expose port (Render will set PORT env var)
ENV PORT=5001

# Use python3 (base image has python3)
CMD ["python3", "server.py"]
