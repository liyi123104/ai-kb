# 前端镜像：Vite 构建 + Nginx 托管（计划书 T5.1）
# 基础镜像可替换（国内网络见 --build-arg NODE_IMAGE=... / NGINX_IMAGE=...）
# 注意：两个 ARG 都必须写在第一个 FROM 之前，才在全局作用域可见，
# 否则第二个 FROM 拿到的会是空值（报 "base name should not be blank"）。
ARG NODE_IMAGE=node:24-alpine
ARG NGINX_IMAGE=nginx:1.27-alpine

FROM ${NODE_IMAGE} AS build
WORKDIR /web

# 先装依赖，利用层缓存
COPY package.json ./
RUN npm install --registry=https://registry.npmmirror.com

COPY . .
RUN npm run build

FROM ${NGINX_IMAGE}
COPY nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build /web/dist /usr/share/nginx/html
EXPOSE 80
