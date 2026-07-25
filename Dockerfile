FROM python:3.12-slim

WORKDIR /app

# Install deps first so they cache across code changes.
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY src/ ./src/

EXPOSE 8000

# Runs the streamable-HTTP MCP server (serves /mcp).
CMD ["python", "-m", "src.server"]
