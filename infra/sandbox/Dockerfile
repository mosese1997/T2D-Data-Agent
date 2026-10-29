# OpenSandbox server (docker runtime). Runs with the host docker socket —
# the SERVER needs it to create sandboxes; sandboxes themselves get no
# host mounts (probe-verified: Mounts=[], deny-all egress opt-in).
FROM python:3.12-slim
RUN pip install --no-cache-dir opensandbox-server==1.2.0
COPY infra/sandbox/opensandbox-config.toml /etc/opensandbox/config.toml
EXPOSE 8003
CMD ["opensandbox-server", "--config", "/etc/opensandbox/config.toml"]
