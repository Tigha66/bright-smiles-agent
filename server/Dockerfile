FROM python:3.12-slim

# Install uv
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

WORKDIR /app

# Copy project files
COPY pyproject.toml .
COPY server/ server/

# Install dependencies
RUN uv sync --no-dev

# Expose port
EXPOSE 7860

# Run the server
CMD ["uv", "run", "python", "-m", "server.server", "--host", "0.0.0.0", "--port", "7860"]
