import importlib.util
import os
from pathlib import Path

os.environ.setdefault("TELEGRAM_BOT_TOKEN", "123:test-token")
os.environ.setdefault("TELEGRAM_GROUP_ID", "-1001234567890")
os.environ.setdefault("TELEGRAM_GROUP_URL", "https://t.me/test_group")
os.environ.setdefault("TELEGRAM_WEBHOOK_SECRET", "test-secret-which-is-long-enough")
os.environ.setdefault("SUPABASE_URL", "https://example.supabase.co")
os.environ.setdefault("SUPABASE_SERVICE_ROLE_KEY", "test-service-key")

# Import module and replace its database client before request tests.
MODULE_PATH = Path(__file__).parents[1] / "api" / "index.py"
spec = importlib.util.spec_from_file_location("legend_webhook", MODULE_PATH)
mod = importlib.util.module_from_spec(spec)
import sys
import types
# Stub Supabase for local tests; no live credentials or network calls are used.
fake_supabase = types.ModuleType("supabase")
fake_supabase.create_client = lambda *args, **kwargs: object()
sys.modules["supabase"] = fake_supabase
sys.modules[spec.name] = mod
spec.loader.exec_module(mod)


def test_valid_member_statuses():
    assert mod.valid_member({"status": "member"})
    assert mod.valid_member({"status": "administrator"})
    assert mod.valid_member({"status": "creator"})
    assert mod.valid_member({"status": "restricted", "is_member": True})
    assert not mod.valid_member({"status": "left"})
    assert not mod.valid_member({"status": "restricted", "is_member": False})


def test_webhook_has_secret_guard_and_routes():
    paths = {route.path for route in mod.app.routes}
    assert "/api/webhook" in paths
    assert "/api/health" in paths
    source = MODULE_PATH.read_text()
    assert "x-telegram-bot-api-secret-token" in source
    assert "challenge_answer" in source


def test_secret_guard_rejects_untrusted_webhook():
    from fastapi.testclient import TestClient
    client = TestClient(mod.app)
    response = client.post("/api/webhook", json={"update_id": 1})
    assert response.status_code == 403


def test_health_endpoint():
    from fastapi.testclient import TestClient
    response = TestClient(mod.app).get("/api/health")
    assert response.status_code == 200
    assert response.json()["ok"] is True


def test_schema_persists_challenge_for_serverless_requests():
    schema = (Path(__file__).parents[1] / "supabase" / "schema.sql").read_text()
    assert "challenge_answer text" in schema
    assert "challenge_expires_at timestamptz" in schema
