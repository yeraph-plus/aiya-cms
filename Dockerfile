FROM python:3.14-slim-bookworm AS build

ENV VIRTUAL_ENV=/opt/venv
ENV PATH="/opt/venv/bin:$PATH"
WORKDIR /build

RUN python -m venv "$VIRTUAL_ENV"
COPY pyproject.toml README.md ./
COPY inc ./inc
RUN pip install --no-cache-dir --upgrade pip==25.3 \
    && pip install --no-cache-dir ".[dev]"

FROM python:3.14-slim-bookworm AS runtime

ENV VIRTUAL_ENV=/opt/venv
ENV PATH="/opt/venv/bin:$PATH"
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV PYTHONPATH=/app
WORKDIR /app

RUN addgroup --system aiya \
    && adduser --system --ingroup aiya aiya \
    && mkdir -p /var/lib/aiya/oidc-keys \
    && chown -R aiya:aiya /var/lib/aiya
COPY --from=build /opt/venv /opt/venv
COPY --chown=aiya:aiya inc ./inc
COPY --chown=aiya:aiya tests ./tests
COPY --chown=aiya:aiya alembic ./alembic
COPY --chown=aiya:aiya deploy ./deploy
COPY --chown=aiya:aiya .github/workflows/production-image.yml ./.github/workflows/production-image.yml
COPY --chown=aiya:aiya alembic.ini pyproject.toml README.md \
    Dockerfile Dockerfile.production .dockerignore compose.production.yaml \
    openapi.json openapi.sha256 openapi.admin.json openapi.admin.sha256 \
    openapi.user.json openapi.user.sha256 ./
RUN chown -R aiya:aiya /app
USER aiya
EXPOSE 8000
CMD ["uvicorn", "inc.main:get_app", "--factory", "--host", "0.0.0.0", "--port", "8000"]
