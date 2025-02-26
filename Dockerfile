# Use an official Python runtime as a parent image
FROM python:3.9-slim

# Prevent Python from writing pyc files and enable unbuffered logging
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

# Set working directory
WORKDIR /app

# Install system dependencies including git
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc git && \
    rm -rf /var/lib/apt/lists/*  # Clean up to reduce image size

# Copy and install requirements
COPY requirements.txt /app/
RUN pip install --upgrade pip && pip install --default-timeout=100 --no-cache-dir -r requirements.txt

# Copy the rest of the application code
COPY . /app/

# Expose the port for the FastAPI app
EXPOSE 8000

# Command to run the app using Gunicorn with Uvicorn workers.
CMD ["gunicorn", "-k", "uvicorn.workers.UvicornWorker", "app.main:app", "--bind", "0.0.0.0:8000", "--workers", "4"]