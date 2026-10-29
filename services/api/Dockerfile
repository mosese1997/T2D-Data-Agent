# Multi-stage, slim base (disk budget — see CLAUDE.md).
FROM python:3.12-slim AS build
WORKDIR /build
COPY packages/db packages/db
COPY packages/agent_adapter packages/agent_adapter
COPY packages/semantic packages/semantic
COPY packages/query_gateway packages/query_gateway
COPY packages/dashboard_schema packages/dashboard_schema
COPY packages/cloud_adapters packages/cloud_adapters
COPY services/api services/api
COPY config config
RUN pip install --no-cache-dir --prefix=/install \
    packages/db packages/agent_adapter packages/semantic \
    packages/query_gateway packages/dashboard_schema packages/cloud_adapters \
    services/api

FROM python:3.12-slim
WORKDIR /app
COPY --from=build /install /usr/local
COPY config /app/config
ENV APP_DATA_DIR=/var/lib/t2d
EXPOSE 8001
CMD ["uvicorn", "t2d_api.main:app", "--host", "0.0.0.0", "--port", "8001"]
