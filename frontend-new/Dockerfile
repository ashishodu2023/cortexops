FROM node:20-alpine AS build

WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci --no-audit --no-fund

COPY . .
# Optional build-time default; CORTEXOPS_API_URL at runtime takes precedence.
ARG VITE_API_URL=""
ENV VITE_API_URL=${VITE_API_URL}
RUN npm run build


FROM nginxinc/nginx-unprivileged:1.27-alpine

ENV CORTEXOPS_API_URL=http://localhost:8000 \
    NGINX_ENVSUBST_FILTER=^CORTEXOPS_

COPY nginx/default.conf.template /etc/nginx/templates/default.conf.template
COPY --chmod=0755 nginx/15-validate-cortexops-config.sh /docker-entrypoint.d/15-validate-cortexops-config.sh
COPY --from=build /app/dist /usr/share/nginx/html

USER 101
EXPOSE 8080
