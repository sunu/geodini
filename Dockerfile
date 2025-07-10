FROM python:3.11-slim

WORKDIR /app

# Copy the rest of the application
COPY geodini/ ./geodini

# Copy the streamlit app
COPY frontend/ ./frontend

# Use pyproject.toml for installing dependencies
COPY pyproject.toml .
RUN pip install --no-cache-dir .

COPY plugins/ /plugins
RUN pip install --no-cache-dir -e /plugins/geodini_kba_example

# Expose the port the app runs on
EXPOSE 9000

# Command to run the application
CMD ["uvicorn", "api:app", "--host", "0.0.0.0", "--port", "9000"] 
