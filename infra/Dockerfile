FROM python:3.12-slim@sha256:b18b261e1b4974b4f321451ad5251ded85abb22c2b8b262da527dda1d031ab30 AS dependencies
WORKDIR /app
COPY requirements.lock ./requirements.lock
RUN pip install --no-cache-dir -r requirements.lock
ENV PYTHONPATH=/app/backend:/app/demo-app
CMD ["uvicorn", "investigator.api:create_app", "--factory", "--host", "0.0.0.0", "--port", "8000"]

FROM dependencies AS retrieval-dependencies
COPY requirements-retrieval.lock ./requirements-retrieval.lock
RUN pip install --no-cache-dir -r requirements-retrieval.lock

FROM retrieval-dependencies AS cache-client
COPY requirements-cache.lock ./requirements-cache.lock
RUN pip install --no-cache-dir -r requirements-cache.lock

FROM dependencies AS base
COPY pyproject.toml alembic.ini ./
COPY backend ./backend
COPY demo-app ./demo-app
COPY scenarios ./scenarios
COPY tests ./tests
COPY scripts ./scripts
COPY knowledge ./knowledge
COPY examples ./examples
FROM retrieval-dependencies AS retrieval
COPY --from=base /app /app
COPY --from=cache-client /usr/local/lib/python3.12/site-packages/redis /usr/local/lib/python3.12/site-packages/redis
COPY --from=cache-client /usr/local/lib/python3.12/site-packages/redis-7.4.1.dist-info /usr/local/lib/python3.12/site-packages/redis-7.4.1.dist-info

FROM retrieval-dependencies AS agent-dependencies
COPY requirements-agent.lock ./requirements-agent.lock
RUN pip install --no-cache-dir -r requirements-agent.lock

FROM agent-dependencies AS agent
COPY --from=base /app /app
COPY --from=cache-client /usr/local/lib/python3.12/site-packages/redis /usr/local/lib/python3.12/site-packages/redis
COPY --from=cache-client /usr/local/lib/python3.12/site-packages/redis-7.4.1.dist-info /usr/local/lib/python3.12/site-packages/redis-7.4.1.dist-info

# Explicit optional image for API/uploader only; never gives AWS credentials to the agent.
FROM retrieval AS s3
COPY requirements-artifacts.lock ./requirements-artifacts.lock
RUN pip install --no-cache-dir -r requirements-artifacts.lock

# Operator-only test image with optional SDKs; never the runtime agent image.
FROM agent AS verification
COPY requirements-cache.lock requirements-mcp.lock requirements-artifacts.lock ./
RUN pip install --no-cache-dir -r requirements-cache.lock -r requirements-mcp.lock -r requirements-artifacts.lock
COPY compose*.yaml ./
COPY infra/iam ./infra/iam
COPY frontend/package.json ./frontend/package.json
