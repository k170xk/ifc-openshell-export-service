FROM --platform=linux/amd64 aecgeeks/ifcopenshell:latest

# Switch to root to install packages  
USER root

# Install Flask dependencies using pip (base image should have pip)
# Try python3.10 first, fallback to python3
RUN (python3.10 -m pip install --no-cache-dir flask flask-cors numpy 2>/dev/null || \
     (apt-get update && apt-get install -y python3-pip && rm -rf /var/lib/apt/lists/* && \
      python3 -m pip install --no-cache-dir flask flask-cors numpy))

# Create the API server script
WORKDIR /app

# Copy the server file and scripts directory
COPY server.py .
COPY scripts/ ./scripts/

# Expose port (Render will set PORT env var)
ENV PORT=5001

# Try python3.10 first, fallback to python3
CMD ["sh", "-c", "python3.10 server.py 2>/dev/null || python3 server.py"]

