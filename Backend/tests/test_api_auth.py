import os
from contextlib import contextmanager

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.api import routes


class FakeCursor:
    def __init__(self):
        self.last_query = ""
        self.last_params = ()

    def execute(self, query, params=()):
        self.last_query = " ".join(str(query).split())
        self.last_params = params

    def fetchone(self):
        query = self.last_query
        if "SELECT value_int FROM prisma_config WHERE key = 'ai_enabled'" in query:
            return {"value_int": 1}
        if "SELECT bankroll_apres FROM historique_paris" in query:
            return {"bankroll_apres": 19000}
        if "SELECT score_prisma, score_zeus, dette_zeus" in query:
            return {
                "score_prisma": 200,
                "score_zeus": 0,
                "dette_zeus": 0,
                "total_emprunte_zeus": 0,
                "stop_loss_override": False,
            }
        return None

    def fetchall(self):
        return []

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False


class FakeConnection:
    def __init__(self):
        self.cursor_obj = FakeCursor()

    def cursor(self):
        return self.cursor_obj

    def commit(self):
        pass

    def rollback(self):
        pass

    def close(self):
        pass


@contextmanager
def fake_db_connection(*args, **kwargs):
    yield FakeConnection()


@pytest.fixture()
def client(monkeypatch):
    app = FastAPI()
    routes.register_routes(app)

    monkeypatch.setattr(routes, "get_db_connection", fake_db_connection)
    monkeypatch.setattr(routes, "get_active_session", lambda: {"id": 7, "current_day": 12, "capital_initial": 20000})
    monkeypatch.setattr(routes, "get_zeus_bankroll", lambda: 19000)
    monkeypatch.setattr(routes, "get_prisma_bankroll", lambda: 21000)

    return TestClient(app)


def test_get_settings_ai_is_public(client, monkeypatch):
    monkeypatch.setenv("ADMIN_SECRET_KEY", "super-secret")

    response = client.get("/settings/ai")

    assert response.status_code == 200
    assert response.json() == {"enabled": True}


def test_post_settings_ai_requires_admin_header(client, monkeypatch):
    monkeypatch.setenv("ADMIN_SECRET_KEY", "super-secret")

    response = client.post("/settings/ai", json={"enabled": False})

    assert response.status_code == 403
    assert "X-Admin-Key" in response.json()["detail"]


def test_post_settings_ai_rejects_body_secret_key_without_header(client, monkeypatch):
    monkeypatch.setenv("ADMIN_SECRET_KEY", "super-secret")

    response = client.post("/settings/ai", json={"enabled": False, "secret_key": "super-secret"})

    assert response.status_code == 403


def test_post_settings_ai_accepts_valid_admin_header(client, monkeypatch):
    monkeypatch.setenv("ADMIN_SECRET_KEY", "super-secret")

    response = client.post(
        "/settings/ai",
        json={"enabled": False},
        headers={"X-Admin-Key": "super-secret"},
    )

    assert response.status_code == 200
    assert response.json() == {"status": "success", "enabled": False}


def test_protected_write_route_returns_503_when_admin_secret_missing(client, monkeypatch):
    monkeypatch.delenv("ADMIN_SECRET_KEY", raising=False)

    response = client.post("/settings/prisma-ml", json={"ensemble_enabled": True})

    assert response.status_code == 503
    assert "ADMIN_SECRET_KEY" in response.json()["detail"]


def test_zeus_borrow_requires_valid_admin_header(client, monkeypatch):
    monkeypatch.setenv("ADMIN_SECRET_KEY", "super-secret")
    called = {}

    def fake_update_zeus_bankroll(value, conn=None):
        called["value"] = value

    monkeypatch.setattr("src.core.zeus_finance.update_zeus_bankroll", fake_update_zeus_bankroll)

    response = client.post(
        "/zeus/borrow",
        json={"amount": 1000},
        headers={"X-Admin-Key": "super-secret"},
    )

    assert response.status_code == 200
    assert response.json()["new_bankroll"] == 20000
    assert called["value"] == 20000


def test_admin_route_uses_same_header_auth(client, monkeypatch):
    monkeypatch.setenv("ADMIN_SECRET_KEY", "super-secret")
    called = {}

    def fake_audit(journee, session_id):
        called["journee"] = journee
        called["session_id"] = session_id

    monkeypatch.setattr("src.analysis.ai_booster.perform_cycle_audit_async", fake_audit)

    response = client.post(
        "/admin/audit/trigger",
        json={"journee": 15},
        headers={"X-Admin-Key": "super-secret"},
    )

    assert response.status_code == 200
    assert called == {"journee": 15, "session_id": 7}
