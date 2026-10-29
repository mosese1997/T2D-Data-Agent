# Build context = repo root (see infra/compose/docker-compose.yml).
FROM nginx:1.27-alpine
COPY infra/nginx/nginx.conf /etc/nginx/nginx.conf
COPY apps/web/dist /usr/share/nginx/html
