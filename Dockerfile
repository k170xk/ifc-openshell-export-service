FROM --platform=linux/amd64 aecgeeks/ifcopenshell:latest

# Switch to root to install packages  
USER root

# The base image should already have Python 3.10 and pip
# Check what Python version is available and use it
RUN python3 --version && \
    (python3.10 -m pip --version 2>/dev/null || python3 -m pip --version) && \
    (python3.10 -m pip install --no-cache-dir flask flask-cors numpy || \
     python3 -m pip install --no-cache-dir flask flask-cors numpy)

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

