# Frontend (Vite build) + nginx. /api se prosleđuje na BACKEND_HOST:8000.
FROM oven/bun:1 AS build
WORKDIR /app
COPY package.json bun.lock bunfig.toml ./
RUN bun install --frozen-lockfile
COPY . .
RUN bunx vite build

FROM nginx:1.27-alpine
ARG BACKEND_HOST=backend
RUN cat > /etc/nginx/conf.d/default.conf <<EOF
server {
    listen 80;
    root /usr/share/nginx/html;
    index index.html;

    location /api/ {
        proxy_pass http://${BACKEND_HOST}:8000;
        proxy_set_header Host \$host;
        proxy_set_header X-Forwarded-For \$remote_addr;
    }

    location / {
        try_files \$uri /index.html;
    }
}
EOF
COPY --from=build /app/dist /usr/share/nginx/html
