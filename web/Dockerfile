# ---- Stage 1: build the React SPA -----------------------------------------
FROM node:20-slim AS build
WORKDIR /app

ARG WEB_BUILD_MODE=production
ENV WEB_BUILD_MODE=${WEB_BUILD_MODE}

COPY package.json package-lock.json* ./
RUN npm ci || npm install

COPY tsconfig*.json vite.config.ts index.html ./
COPY src ./src
RUN npm run build

# ---- Stage 2: FastAPI serves the built SPA + proxies /api ------------------
FROM python:3.12-slim
WORKDIR /app

ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    WEB_DIST_DIR=/app/dist

COPY requirements.txt .
RUN pip install -r requirements.txt

COPY main.py .
COPY --from=build /app/dist ./dist

EXPOSE 3000
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "3000"]
