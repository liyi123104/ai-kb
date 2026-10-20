# 前端镜像：Vite 构建 + Nginx 托管（计划书 T5.1）
FROM node:24-alpine AS build
WORKDIR /web

# 先装依赖，利用层缓存
COPY package.json ./
RUN npm install --registry=https://registry.npmmirror.com

COPY . .
RUN npm run build

FROM nginx:1.27-alpine
COPY nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build /web/dist /usr/share/nginx/html
EXPOSE 80
