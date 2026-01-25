# --- Stage 1: Build ---
FROM node:22-alpine AS builder

WORKDIR /app-front

COPY admin/package.json admin/package-lock.json ./
RUN npm ci

COPY admin ./

RUN npm run build

# --- Stage 2: Nginx Runtime ---
FROM nginx:1.25-alpine

COPY --from=builder /app-front/build /usr/share/nginx/html
COPY nginx.conf /etc/nginx/conf.d/default.conf

EXPOSE 80
CMD ["nginx", "-g", "daemon off;"]
