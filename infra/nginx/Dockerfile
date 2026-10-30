# Build context = repo root (see infra/compose/docker-compose.yml).
FROM nginx:1.27-alpine
# Self-signed cert for the bare IP (no domain/DNS — task book boundary).
# Browsers that force-https get a warning-click-through instead of a dead
# connection; generated at build time so no key is ever committed.
RUN apk add --no-cache openssl
ARG PUBLIC_IP=101.44.189.191
RUN mkdir -p /etc/nginx/certs
RUN openssl req -x509 -newkey rsa:2048 -nodes -days 825 \
      -keyout /etc/nginx/certs/t2d.key \
      -out /etc/nginx/certs/t2d.crt \
      -subj "/CN=${PUBLIC_IP}" \
      -addext "subjectAltName=IP:${PUBLIC_IP},DNS:localhost"
COPY infra/nginx/nginx.conf /etc/nginx/nginx.conf
COPY apps/web/dist /usr/share/nginx/html
