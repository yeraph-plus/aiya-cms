FROM node:24-alpine AS build

WORKDIR /app

ARG AIYA_ISSUER=http://127.0.0.1:8080
ARG AIYA_PUBLIC_BASE_URL=http://127.0.0.1:8080
ARG VITE_API_BASE_URL=
ENV AIYA_ISSUER=${AIYA_ISSUER}
ENV AIYA_PUBLIC_BASE_URL=${AIYA_PUBLIC_BASE_URL}
ENV VITE_API_BASE_URL=${VITE_API_BASE_URL}

COPY admin/package.json admin/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY admin/ ./
RUN npm run build

FROM nginxinc/nginx-unprivileged:1.31.3-alpine AS runtime

COPY admin/nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build --chown=101:101 /app/dist /usr/share/nginx/html

EXPOSE 8080

