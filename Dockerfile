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
WORKDIR /app

RUN addgroup --system aiya && adduser --system --ingroup aiya aiya
COPY --from=build /opt/venv /opt/venv
COPY --chown=aiya:aiya inc ./inc
COPY --chown=aiya:aiya tests ./tests
COPY --chown=aiya:aiya alembic ./alembic
COPY --chown=aiya:aiya alembic.ini pyproject.toml README.md ./
RUN chown -R aiya:aiya /app
USER aiya
EXPOSE 8000
CMD ["uvicorn", "inc.main:app", "--host", "0.0.0.0", "--port", "8000"]
