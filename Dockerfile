FROM --platform=linux/amd64 aecgeeks/ifcopenshell:latest

# Switch to root to install packages
USER root

# Install pip if not already available, then install Flask dependencies
# The base image already has Python 3.10, just need pip
RUN apt-get update && apt-get install -y python3-pip && rm -rf /var/lib/apt/lists/* \
    && python3 -m pip install --no-cache-dir flask flask-cors numpy

# Create the API server script
WORKDIR /app

# Copy the server file and scripts directory
COPY server.py .
COPY scripts/ ./scripts/

# Expose port (Render will set PORT env var)
ENV PORT=5001

CMD ["python3", "server.py"]

