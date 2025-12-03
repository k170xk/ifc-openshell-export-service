FROM --platform=linux/amd64 aecgeeks/ifcopenshell:latest

# Switch to root to install packages  
USER root

# The base image already has Python 3.10 and likely has pip
# Try using existing pip first, avoid installing python3-pip (which brings Python 3.8)
RUN python3 --version && \
    (python3 -m pip --version || python3.10 -m pip --version || pip3 --version) && \
    (python3 -m pip install --no-cache-dir flask flask-cors numpy || \
     python3.10 -m pip install --no-cache-dir flask flask-cors numpy || \
     pip3 install --no-cache-dir flask flask-cors numpy)

# Create the API server script
WORKDIR /app

# Copy the server file and scripts directory
COPY server.py .
COPY scripts/ ./scripts/

# Expose port (Render will set PORT env var)
ENV PORT=5001

# Use python3.10 explicitly to match IfcOpenShell
CMD ["python3.10", "server.py"]

