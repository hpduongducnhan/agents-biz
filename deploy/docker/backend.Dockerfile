# syntax=docker/dockerfile:1
# Backend — MỘT image cho mọi role (bw migrate / api / consume / work / schedule); lệnh đặt ở compose.
ARG PYTHON_VERSION=3.13

FROM python:${PYTHON_VERSION}-slim AS build
ENV PIP_DISABLE_PIP_VERSION_CHECK=1 POETRY_NO_INTERACTION=1 POETRY_VIRTUALENVS_IN_PROJECT=true
RUN pip install --no-cache-dir poetry
WORKDIR /app/backend
COPY backend/pyproject.toml backend/poetry.lock backend/poetry.toml ./
RUN --mount=type=cache,target=/root/.cache/pypoetry poetry install --without dev --no-root
COPY backend/app ./app
COPY backend/migrations ./migrations
RUN poetry install --without dev && .venv/bin/python -m compileall -q app migrations

FROM python:${PYTHON_VERSION}-slim
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 PATH=/app/backend/.venv/bin:$PATH
RUN useradd --system --uid 10001 --home-dir /app --no-create-home bw
COPY --from=build /app /app
WORKDIR /app/backend
USER bw
EXPOSE 16812
CMD ["bw", "api"]
