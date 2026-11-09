"""Phase 12: static checks of the Docker setup (no Docker or network needed).

They catch the mistakes that break `docker compose up` quietly: a missing healthcheck or volume, the nginx
proxy not forwarding /api, a container path that the app would resolve against the wrong folder.
"""

import re
from pathlib import Path

import pytest
import yaml

from app.core.config import Settings

REPO = Path(__file__).resolve().parents[2]
if not (REPO / "docker-compose.yml").is_file():
    # Inside the backend image only backend/ exists; these checks run from a repo checkout.
    pytest.skip("docker-compose.yml not present (running inside the backend image)", allow_module_level=True)
COMPOSE = yaml.safe_load((REPO / "docker-compose.yml").read_text(encoding="utf-8"))
SERVICES = COMPOSE["services"]
NGINX = (REPO / "frontend" / "nginx" / "default.conf.template").read_text(encoding="utf-8")
BACKEND_DOCKERFILE = (REPO / "backend" / "Dockerfile").read_text(encoding="utf-8")


def test_compose_has_the_full_stack_and_optional_profiles():
    assert {"db", "backend", "frontend", "ollama", "seed"} <= set(SERVICES)
    assert "profiles" not in SERVICES["db"]
    assert "profiles" not in SERVICES["backend"]
    assert "profiles" not in SERVICES["frontend"]
    assert SERVICES["ollama"]["profiles"] == ["ollama"]
    assert SERVICES["seed"]["profiles"] == ["seed"]


def test_named_volumes_for_postgres_storage_chroma_and_model_cache():
    assert {"pgdata", "storage", "chroma", "hf-cache", "ollama"} <= set(COMPOSE["volumes"])
    backend_volumes = SERVICES["backend"]["volumes"]
    assert "storage:/data/storage" in backend_volumes
    assert "chroma:/data/chroma" in backend_volumes
    assert "hf-cache:/data/hf-cache" in backend_volumes
    assert any(v.startswith("./finetune/results:") and v.endswith(":ro") for v in backend_volumes)
    assert "pgdata:/var/lib/postgresql/data" in SERVICES["db"]["volumes"]


def test_backend_container_paths_match_the_volumes():
    env = SERVICES["backend"]["environment"]
    assert env["STORAGE_DIR"] == "/data/storage"
    assert env["CHROMA_DIR"] == "/data/chroma"
    assert env["HF_HOME"] == "/data/hf-cache"
    assert "@db:5432/" in env["DATABASE_URL"]
    # Absolute container paths must be used as they are, not resolved against backend/.
    s = Settings(_env_file=None, storage_dir=env["STORAGE_DIR"], chroma_dir=env["CHROMA_DIR"],
                 finetune_results_dir=env["FINETUNE_RESULTS_DIR"])
    assert s.storage_path.as_posix().endswith("/data/storage")
    assert s.chroma_path.as_posix().endswith("/data/chroma")
    assert s.finetune_results_path.as_posix().endswith("/app/finetune-results")


def test_start_order_waits_for_healthy_dependencies():
    assert SERVICES["backend"]["depends_on"]["db"]["condition"] == "service_healthy"
    assert SERVICES["frontend"]["depends_on"]["backend"]["condition"] == "service_healthy"
    assert "healthcheck" in SERVICES["db"]
    assert "healthcheck" in SERVICES["ollama"]
    assert "HEALTHCHECK" in BACKEND_DOCKERFILE and "/api/health" in BACKEND_DOCKERFILE
    assert "HEALTHCHECK" in (REPO / "frontend" / "Dockerfile").read_text(encoding="utf-8")


def test_backend_image_runs_as_non_root_with_ffmpeg_and_cpu_torch():
    assert re.search(r"^USER app$", BACKEND_DOCKERFILE, re.MULTILINE)
    assert "ffmpeg" in BACKEND_DOCKERFILE
    assert "download.pytorch.org/whl/cpu" in BACKEND_DOCKERFILE


def test_base_images_are_pinned():
    dockerfiles = [BACKEND_DOCKERFILE, (REPO / "frontend" / "Dockerfile").read_text(encoding="utf-8")]
    for line in "\n".join(dockerfiles).splitlines():
        if line.startswith("FROM "):
            image = line.split()[1]
            assert re.search(r":\d+\.\d+\.\d+", image), f"unpinned base image: {image}"
    assert re.search(r":\d+\.\d+\.\d+$", SERVICES["ollama"]["image"])


def test_nginx_proxies_api_and_serves_the_spa():
    assert re.search(r"location ~ \^/\(api\|docs\|openapi\\\.json\)", NGINX)
    # Resolved per request, so a recreated backend container (new IP) does not leave nginx returning 502.
    assert "resolver ${NGINX_LOCAL_RESOLVERS}" in NGINX
    assert "set $backend_upstream ${BACKEND_URL};" in NGINX
    assert "proxy_pass $backend_upstream;" in NGINX
    assert "NGINX_ENTRYPOINT_LOCAL_RESOLVERS=1" in (REPO / "frontend" / "Dockerfile").read_text(encoding="utf-8")
    assert "client_max_body_size ${MAX_UPLOAD_MB}m;" in NGINX
    assert "try_files $uri $uri/ /index.html;" in NGINX
    timeout = int(re.search(r"proxy_read_timeout (\d+)s;", NGINX).group(1))
    assert timeout >= Settings(_env_file=None).llm_timeout_sec


def test_shell_scripts_use_lf_line_endings():
    for name in ("entrypoint.sh", "seed-volumes.sh"):
        data = (REPO / "backend" / "docker" / name).read_bytes()
        assert data.startswith(b"#!/bin/sh")
        assert b"\r\n" not in data, f"{name} has CRLF line endings and would fail in Linux"
