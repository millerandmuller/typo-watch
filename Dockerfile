FROM node:22-slim AS css
WORKDIR /build
COPY package.json package-lock.json ./
RUN npm ci --no-fund --no-audit
COPY static/src.css ./static/src.css
COPY templates ./templates
RUN npx tailwindcss -i ./static/src.css -o ./static/app.css --minify

FROM python:3.12-slim
WORKDIR /app

COPY requirements.txt pyproject.toml ./
RUN pip install --no-cache-dir -r requirements.txt

COPY squatwatch ./squatwatch
COPY templates ./templates
COPY static ./static
COPY seed ./seed
RUN pip install --no-cache-dir -e .

COPY --from=css /build/static/app.css ./static/app.css

ENV APP_ENV=production
ENV SQLITE_PATH=/data/squatwatch.db
RUN mkdir -p /data
VOLUME /data

EXPOSE 8000
CMD ["uvicorn", "squatwatch.app:app", "--host", "0.0.0.0", "--port", "8000"]
