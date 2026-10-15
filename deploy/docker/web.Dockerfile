# syntax=docker/dockerfile:1
# Web — build bundle React rồi nginx làm "một cửa": bundle + proxy /<SERVICE_PATH>/api → api, /<SERVICE_PATH>/ws → realtime.
FROM node:26-slim AS build
WORKDIR /app/frontend
COPY frontend/package.json frontend/package-lock.json ./
RUN --mount=type=cache,target=/root/.npm npm ci
COPY frontend ./
ARG SERVICE_PATH=bizwithagents
ENV VITE_API_BASE_URL=/${SERVICE_PATH}/api \
    VITE_WS_PATH=/${SERVICE_PATH}/ws
RUN npm run build

FROM nginx:alpine AS nginx

# nginx:alpine khai EXPOSE 80 mà Dockerfile không gỡ được → chép filesystem sang scratch rồi khai lại PATH /
# entrypoint / cmd / stopsignal của image gốc: image chỉ còn cổng 16811 nên Traefik không chọn nhầm 80.
FROM scratch
COPY --from=nginx / /
# Chỉ thay biến của mình trong template — biến nginx ($host, $remote_addr…) giữ nguyên.
ENV PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin \
    NGINX_ENVSUBST_FILTER="^(WEB_PORT|SERVICE_PATH|API_UPSTREAM|REALTIME_UPSTREAM|REAL_IP_HEADER)\$" \
    WEB_PORT=16811 \
    SERVICE_PATH=bizwithagents \
    API_UPSTREAM=bw-api:16812 \
    REALTIME_UPSTREAM=bw-realtime:16813 \
    REAL_IP_HEADER=CF-Connecting-IP
COPY deploy/docker/nginx/default.conf.template /etc/nginx/templates/default.conf.template
COPY --from=build /app/frontend/dist /usr/share/nginx/html
EXPOSE 16811
STOPSIGNAL SIGQUIT
ENTRYPOINT ["/docker-entrypoint.sh"]
CMD ["nginx", "-g", "daemon off;"]
