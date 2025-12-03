FROM --platform=linux/amd64 aecgeeks/ifcopenshell:latest

# Switch to root to install packages
USER root

# Install pip for Python 3.10 (matching the base image)
# The base image uses Python 3.10, so we need to use python3.10 explicitly
RUN apt-get update && apt-get install -y python3.10-dev python3-pip && rm -rf /var/lib/apt/lists/* \
    && python3.10 -m pip install --no-cache-dir flask flask-cors numpy

# Create the API server script
WORKDIR /app

# Copy the server file and scripts directory
COPY server.py .
COPY scripts/ ./scripts/

# Expose port (Render will set PORT env var)
ENV PORT=5001

CMD ["python3.10", "server.py"]

