"""compose.yml cho Coolify: 6 service `bw-*`, một cửa `bw-web`, env bắt buộc, Mongo tuỳ cờ, migrate đầu api."""

from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[3]
COMPOSE = yaml.safe_load((ROOT / "compose.yml").read_text())
SERVICES = COMPOSE["services"]
BACKEND = ("bw-api", "bw-consumer", "bw-worker", "bw-scheduler")


def test_six_prefixed_services_no_host_ports_no_volumes_no_shared_network():
    assert set(SERVICES) == {*BACKEND, "bw-realtime", "bw-web"}
    assert all("ports" not in svc for svc in SERVICES.values())
    assert all("volumes" not in svc for svc in SERVICES.values()) and "volumes" not in COMPOSE
    assert "networks" not in COMPOSE and all("networks" not in svc for svc in SERVICES.values())


def test_backend_commands():
    assert SERVICES["bw-api"]["command"] == ["sh", "-c", "bw migrate && exec bw api"]
    assert SERVICES["bw-consumer"]["command"] == ["bw", "consume"]
    assert SERVICES["bw-worker"]["command"] == ["bw", "work"]
    assert SERVICES["bw-scheduler"]["command"] == ["bw", "schedule"]


def test_required_env_and_optional_mongo():
    env = SERVICES["bw-api"]["environment"]
    required = (
        "POSTGRES_RW_URL",
        "REDIS_RW_URL",
        "RABBITMQ_URL",
        "SUPERADMIN_EMAILS",
        "AUTH_PRIVATE_KEY",
        "AUTH_PUBLIC_KEY",
    )
    for name in required:
        assert env[name] == f"${{{name}:?}}", name
    assert not any(name.endswith("_KEY_FILE") for name in env)
    assert env["MONGO_ENABLED"] == "${MONGO_ENABLED:-true}"
    assert env["MONGO_RW_URL"] == "${MONGO_RW_URL:-}"
    assert env["SERVICE_PATH"] == "${SERVICE_PATH:-bizwithagents}"
    assert env["PUBLIC_URL"] == "${PUBLIC_URL:-}"
    assert env["LOG_HTTP_IN"] == "${LOG_HTTP_IN:-true}" and env["LOG_HTTP_OUT"] == "${LOG_HTTP_OUT:-true}"
    assert env["LOG_HTTP_SLOW_MS"] == "${LOG_HTTP_SLOW_MS:-1000}"
    for name in BACKEND:
        assert SERVICES[name]["environment"] == env  # cùng anchor x-backend-env
    realtime = SERVICES["bw-realtime"]["environment"]
    assert realtime["AUTH_PUBLIC_KEY"] == "${AUTH_PUBLIC_KEY:?}" and "AUTH_PRIVATE_KEY" not in realtime


def test_startup_order_and_healthchecks():
    api = SERVICES["bw-api"]
    assert not api["depends_on"] and "/api/health/ready" in str(api["healthcheck"])
    for name in ("bw-consumer", "bw-worker", "bw-scheduler"):
        assert SERVICES[name]["depends_on"]["bw-api"]["condition"] == "service_healthy", name
    assert "depends_on" not in SERVICES["bw-realtime"]
    assert SERVICES["bw-web"]["depends_on"]["bw-api"]["condition"] == "service_healthy"
    assert SERVICES["bw-web"]["depends_on"]["bw-realtime"]["condition"] == "service_healthy"


def test_web_is_the_only_door():
    web = SERVICES["bw-web"]["environment"]
    assert web["SERVICE_URL_BW_WEB"] == "${SERVICE_URL_BW_WEB:?}"
    assert web["API_UPSTREAM"] == "bw-api:16812" and web["REALTIME_UPSTREAM"] == "bw-realtime:16813"
    assert SERVICES["bw-realtime"]["environment"]["WS_PATH"] == "/${SERVICE_PATH:-bizwithagents}/ws"
    backend_urls = SERVICES["bw-api"]["environment"]
    assert backend_urls["GOOGLE_REDIRECT_URI"].startswith("${SERVICE_URL_BW_WEB:?}/")
    assert backend_urls["FRONTEND_AUTH_CALLBACK_URL"] == "${SERVICE_URL_BW_WEB:?}/auth/callback"


def test_image_defaults_match_compose_upstreams():
    web_dockerfile = (ROOT / "deploy/docker/web.Dockerfile").read_text()
    for line in (
        "WEB_PORT=16811",
        "API_UPSTREAM=bw-api:16812",
        "REALTIME_UPSTREAM=bw-realtime:16813",
        "EXPOSE 16811",
    ):
        assert line in web_dockerfile, line
    assert "EXPOSE 16812" in (ROOT / "deploy/docker/backend.Dockerfile").read_text()
    assert "EXPOSE 16813" in (ROOT / "deploy/docker/realtime.Dockerfile").read_text()
    template = (ROOT / "deploy/docker/nginx/default.conf.template").read_text()
    assert "listen ${WEB_PORT};" in template and "WEB_PORT|" in web_dockerfile  # envsubst thay được WEB_PORT


def test_internal_ports_are_168xx():
    """Cổng container nội bộ dải 168xx: web 16811 · api 16812 · realtime 16813 — healthcheck gọi đúng cổng."""
    assert SERVICES["bw-api"]["environment"]["PORT"] == 16812
    assert "127.0.0.1:16812/" in str(SERVICES["bw-api"]["healthcheck"])
    assert SERVICES["bw-realtime"]["environment"]["REALTIME_PORT"] == 16813
    assert "127.0.0.1:16813" in str(SERVICES["bw-realtime"]["healthcheck"])
    assert SERVICES["bw-web"]["environment"]["WEB_PORT"] == 16811
    assert "127.0.0.1:16811/" in str(SERVICES["bw-web"]["healthcheck"])


def test_web_exposes_only_its_port_for_traefik():
    """Domain không kèm cổng: image web chỉ khai 16811 (dựng lại từ scratch, bỏ EXPOSE 80 của nginx:alpine)
    và compose `expose` cùng cổng để Coolify ghi label cổng cho Traefik — còn cổng 80 thì Traefik chọn nhầm, trả 502."""
    lines = (ROOT / "deploy/docker/web.Dockerfile").read_text().splitlines()
    assert [line for line in lines if line.startswith("FROM ")][-1] == "FROM scratch"
    assert [line for line in lines if line.startswith("EXPOSE")] == ["EXPOSE 16811"]
    assert SERVICES["bw-web"]["expose"] == [str(SERVICES["bw-web"]["environment"]["WEB_PORT"])]
    assert [name for name, svc in SERVICES.items() if "expose" in svc] == ["bw-web"]
