# Use an official Python runtime as a parent image
FROM python:3.11-slim

# Set the working directory in the container
WORKDIR /app_audit

# Copy requirements file (ensure you have created one)
# Create it via: pip freeze > requirements.txt
COPY requirements.txt .

# Install dependencies
RUN pip install --no-cache-dir -r requirements.txt

# Copy the entire project directory into the container
COPY . .

# Expose the port the app runs on (default in docs is 8001)
EXPOSE 8001

# Run the agent server using uvicorn
# Update the path 'remote_a2a.hello_world.agent' to match your specific file path
CMD ["uvicorn", "audit.agent:a2a_app", "--host", "0.0.0.0", "--port", "8001"]