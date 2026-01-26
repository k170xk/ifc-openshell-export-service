FROM --platform=linux/amd64 aecgeeks/ifcopenshell:latest

# Install Flask for the API server
# The base image has Python, try pip3 or python -m pip
RUN python3 -m pip install --no-cache-dir flask flask-cors numpy || \
    pip3 install --no-cache-dir flask flask-cors numpy || \
    python -m pip install --no-cache-dir flask flask-cors numpy

# Create the API server script
WORKDIR /app

# Copy the server file and scripts directory
COPY server.py .
COPY scripts/ ./scripts/

# Expose port (Render will set PORT env var)
ENV PORT=5001

# Use python (base image should have Python available)
CMD ["python", "server.py"]
