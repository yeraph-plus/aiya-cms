from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def test_production_image_serves_spa_and_proxies_backend() -> None:
    dockerfile = (ROOT / "Dockerfile.production").read_text(encoding="utf-8")
    nginx = (ROOT / "deploy" / "nginx.production.conf").read_text(encoding="utf-8")
    nginx_root = (ROOT / "deploy" / "nginx.conf").read_text(encoding="utf-8")

    assert "COPY admin/dist/ /usr/share/nginx/html/" in dockerfile
    assert "USER aiya" in dockerfile
    assert "supervisord" in dockerfile
    assert "pid /tmp/nginx.pid;" in nginx_root
    assert "server 127.0.0.1:8000;" in nginx
    assert "location /api/" in nginx
    assert "location /oidc/" in nginx
    assert "try_files $uri $uri/ /index.html;" in nginx


def test_production_workflow_builds_assets_before_image() -> None:
    workflow = (ROOT / ".github" / "workflows" / "production-image.yml").read_text(encoding="utf-8")
    dockerignore = (ROOT / ".dockerignore").read_text(encoding="utf-8")

    assert "run: npm run build" in workflow
    assert "docker/build-push-action@v6" in workflow
    assert "file: Dockerfile.production" in workflow
    assert "!admin/dist/**" in dockerignore


def test_production_compose_owns_runtime_environment() -> None:
    dockerfile = (ROOT / "Dockerfile.production").read_text(encoding="utf-8")
    compose = (ROOT / "compose.production.yaml").read_text(encoding="utf-8")
    entrypoint = (ROOT / "deploy" / "production-entrypoint.sh").read_text(encoding="utf-8")

    assert "ENV " not in dockerfile
    assert "env_file" not in compose
    assert "environment:" in compose
    assert "AIYA_PG_HOST=${AIYA_PG_HOST:?AIYA_PG_HOST is required}" in compose
    assert "AIYA_DATABASE_URL=${AIYA_DATABASE_URL:?AIYA_DATABASE_URL is required}" in compose
    assert "AIYA_REDIS_URL=${AIYA_REDIS_URL:?AIYA_REDIS_URL is required}" in compose
    assert "AIYA_OIDC_SIGNING_KEY_DIR=/var/lib/aiya/oidc-keys" in compose
    assert "AIYA_AUTO_INSTALL=${AIYA_AUTO_INSTALL:-true}" in compose
    assert "/opt/venv/bin/python -m inc.cli install" in entrypoint
    assert '"${1:-}" = "supervisord"' in entrypoint
