# --- Stage 1: Build ---
FROM node:22 AS builder

WORKDIR /app-front

COPY  package.json package-lock.json ./
RUN npm ci

COPY . .

RUN npm run build

# --- Stage 2: Nginx Runtime ---
FROM nginx:1.25

COPY --from=builder /app-front/build /usr/share/nginx/html
COPY ../nginx.conf /etc/nginx/conf.d/default.conf

EXPOSE 80
CMD ["nginx", "-g", "daemon off;"]
