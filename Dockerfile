FROM node:22-alpine AS web-build
WORKDIR /web
COPY web/package.json web/package-lock.json* ./
RUN npm install
COPY web/ ./
RUN npm run build

FROM python:3.12-slim
WORKDIR /app
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY app ./app
COPY scripts ./scripts
COPY alembic.ini ./
COPY alembic ./alembic
COPY --from=web-build /web/dist ./web/dist
ENV WEB_DIST_DIR=/app/web/dist
EXPOSE 8000
CMD ["sh", "-c", "python scripts/seed_demo.py && uvicorn app.main:app --host 0.0.0.0 --port 8000"]