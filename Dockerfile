# Build stage
FROM python:3.9-slim as builder

WORKDIR /app

# Copy and install requirements
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy the rest of the application code
COPY . .

# Final stage
FROM python:3.9-slim

WORKDIR /app

# Copy from builder stage
COPY --from=builder /usr/local/lib/python3.9/site-packages /usr/local/lib/python3.9/site-packages
COPY --from=builder /app .

# Set the command to run the Streamlit app
CMD ["streamlit", "run", "ui/fet-form-table.py"]