# Build the SPA, then serve the static output from nginx.
#
# Vite inlines VITE_* variables at build time, so the backend URL is a build argument
# rather than a runtime environment variable. Changing it means rebuilding the image —
# stated here because the alternative (runtime config injection) is the usual reflex
# and is not what this image does.

FROM node:20-alpine AS build

WORKDIR /app

COPY package.json package-lock.json* ./
RUN npm ci --no-audit --no-fund

COPY tsconfig.json vite.config.ts index.html eslint.config.js ./
COPY src ./src

ARG VITE_API_BASE_URL=http://localhost:8080
ENV VITE_API_BASE_URL=$VITE_API_BASE_URL
RUN npm run build

FROM nginx:1.27-alpine AS runtime

COPY --from=build /app/dist /usr/share/nginx/html
COPY nginx.conf /etc/nginx/conf.d/default.conf

EXPOSE 5173
