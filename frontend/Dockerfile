# Frontend image (Phase 12): build the React app with Node, serve the static files with nginx.
# Build context is frontend/ (see docker-compose.yml).

# --- Stage 1: build ---
FROM node:22.23.4-alpine3.24 AS build
WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci
COPY . .
RUN npm run build

# --- Stage 2: serve ---
FROM nginx:1.30.6-alpine3.24
# The official image renders /etc/nginx/templates/*.template with envsubst at start-up
# (only variables that are set, so nginx's own $uri etc. are left alone).
COPY nginx/default.conf.template /etc/nginx/templates/default.conf.template
COPY --from=build /app/dist /usr/share/nginx/html
ENV BACKEND_URL=http://backend:8000 \
    MAX_UPLOAD_MB=500 \
    # Makes the image's entrypoint export NGINX_LOCAL_RESOLVERS (from /etc/resolv.conf) for the template.
    NGINX_ENTRYPOINT_LOCAL_RESOLVERS=1
EXPOSE 80
HEALTHCHECK --interval=15s --timeout=5s --start-period=10s --retries=5 \
    CMD wget -q -O /dev/null http://127.0.0.1/healthz || exit 1
