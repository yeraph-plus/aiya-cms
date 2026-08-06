FROM node:24.4.1-alpine AS build

WORKDIR /app/admin
COPY admin/.npmrc admin/package.json admin/package-lock.json ./
RUN npm ci
COPY admin ./
RUN npm run build

FROM nginx:1.29.1-alpine AS runtime

COPY --from=build /app/admin/dist /usr/share/nginx/html
COPY admin/nginx.conf /etc/nginx/conf.d/default.conf
RUN addgroup -S aiya && adduser -S -G aiya aiya \
    && chown -R aiya:aiya /usr/share/nginx/html /var/cache/nginx /var/log/nginx /etc/nginx/conf.d \
    && touch /var/run/nginx.pid \
    && chown aiya:aiya /var/run/nginx.pid
USER aiya
EXPOSE 8080
CMD ["nginx", "-g", "daemon off;"]
