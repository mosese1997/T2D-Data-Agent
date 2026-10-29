# Multi-stage, slim base (disk budget — see CLAUDE.md).
FROM python:3.12-slim AS build
WORKDIR /build
COPY packages/db packages/db
COPY packages/agent_adapter packages/agent_adapter
COPY packages/semantic packages/semantic
COPY packages/query_gateway packages/query_gateway
COPY packages/dashboard_schema packages/dashboard_schema
COPY packages/cloud_adapters packages/cloud_adapters
COPY services/worker services/worker
COPY config config
RUN pip install --no-cache-dir --prefix=/install \
    -e packages/db -e packages/agent_adapter -e packages/semantic \
    -e packages/query_gateway -e packages/dashboard_schema -e packages/cloud_adapters \
    -e services/worker

FROM python:3.12-slim
WORKDIR /app
COPY --from=build /install /usr/local
COPY config /app/config
COPY services/worker/t2d_worker /app/t2d_worker
ENV APP_DATA_DIR=/var/lib/t2d
EXPOSE 8002
CMD ["python", "-m", "t2d_worker.main"]
