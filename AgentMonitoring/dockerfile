FROM python:3.11.9-slim

# Set timezone to Asia/Seoul
ENV TZ=Asia/Seoul
RUN ln -snf /usr/share/zoneinfo/$TZ /etc/localtime \
    && echo $TZ > /etc/timezone

# Copy ultrafast-python execution binaries
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

WORKDIR /app

# Install dependencies without installing the project itself
COPY pyproject.toml uv.lock* ./
RUN uv sync --locked --no-install-project

# Copy project source code and install remaining dependencies
COPY . .
RUN uv sync --locked

# Ensure virtualenv binaries are in PATH
ENV PATH="/app/.venv/bin:$PATH"

EXPOSE 8000

CMD ["uv", "run", "main.py", "--host", "0.0.0.0", "--port", "8000"]
