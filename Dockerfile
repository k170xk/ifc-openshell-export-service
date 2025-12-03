FROM --platform=linux/amd64 aecgeeks/ifcopenshell:latest

# Switch to root to install packages  
USER root

# The base image should already have Python 3.10 and pip
# Use the Python that comes with the base image (don't install python3-pip which brings Python 3.8)
# Check if pip3 or python3 -m pip works, use that
RUN (pip3 install --no-cache-dir flask flask-cors numpy 2>/dev/null || \
     python3.10 -m pip install --no-cache-dir flask flask-cors numpy 2>/dev/null || \
     (apt-get update && apt-get install -y python3-pip && rm -rf /var/lib/apt/lists/* && \
      python3.10 -m pip install --no-cache-dir flask flask-cors numpy))

# Create the API server script
WORKDIR /app

# Copy the server file and scripts directory
COPY server.py .
COPY scripts/ ./scripts/

# Expose port (Render will set PORT env var)
ENV PORT=5001

# Use python3.10 if available, otherwise python3
# But we need to ensure we're using the Python that matches IfcOpenShell
CMD ["sh", "-c", "if command -v python3.10 >/dev/null 2>&1; then python3.10 server.py; else python3 server.py; fi"]

