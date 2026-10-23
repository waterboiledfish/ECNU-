"""测试夹具：每个测试使用独立 SQLite 数据库，不访问外部网络。"""
from __future__ import annotations

import os
import shutil
import tempfile
import uuid
from pathlib import Path

import pytest

TEST_DATA_DIR = Path(tempfile.mkdtemp(prefix="ecnu-pytest-"))
os.environ["ECNU_DATA_DIR"] = str(TEST_DATA_DIR)
os.environ["ECNU_AUTH_MODE"] = "dev"
os.environ["ECNU_DEV_LOGIN_ENABLED"] = "true"
os.environ["ECNU_COOKIE_SECURE"] = "false"
os.environ["ECNU_TIMEZONE"] = "Asia/Shanghai"


@pytest.fixture(scope="session", autouse=True)
def _cleanup_session():
    yield
    shutil.rmtree(TEST_DATA_DIR, ignore_errors=True)


@pytest.fixture()
def client(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient

    from app.config import settings
    from app.db import init_db
    from app.security import limiter
    from app.services import index

    data = tmp_path / "data"
    (data / "avatars").mkdir(parents=True, exist_ok=True)
    (data / "popups").mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(settings, "data_dir", data)
    monkeypatch.setattr(settings, "auth_mode", "dev")
    monkeypatch.setattr(settings, "dev_login_enabled", True)
    monkeypatch.setattr(settings, "moderation_api_key", "")
    monkeypatch.setattr(settings, "tavily_api_key", "")
    limiter._hits.clear()
    init_db()
    index.invalidate()
    from app.main import app

    with TestClient(app) as test_client:
        yield test_client


def login(client, nickname: str = "测试同学") -> tuple[dict, dict]:
    response = client.post("/api/auth/dev-login", json={"nickname": nickname})
    assert response.status_code == 200, response.text
    data = response.json()
    return data, {"X-CSRF-Token": data["csrf"]}


@pytest.fixture()
def auth(client):
    data, headers = login(client)
    return {"client": client, "user": data["user"], "csrf": data["csrf"], "headers": headers}


def create_user_session(nickname: str, role: str = "user") -> tuple[int, str, str]:
    """直接创建第二位用户及其会话，返回 (id, token, csrf)。"""
    from app.db import db
    from app.security import create_session
    from app.timeutil import now_iso

    with db() as conn:
        cursor = conn.execute(
            "INSERT INTO users (sso_subject, sso_provider, nickname, role, created_at) "
            "VALUES (?, 'test', ?, ?, ?)",
            (f"test:{uuid.uuid4().hex}", nickname, role, now_iso()),
        )
        user_id = int(cursor.lastrowid)
        token, csrf = create_session(conn, user_id)
    return user_id, token, csrf


def client_for_session(token: str):
    from fastapi.testclient import TestClient

    from app.main import app

    other = TestClient(app)
    other.cookies.set("ecnu_session", token)
    return other


@pytest.fixture()
def second_user(auth):
    user_id, token, csrf = create_user_session("第二位同学")
    other = client_for_session(token)
    yield {"client": other, "user_id": user_id, "headers": {"X-CSRF-Token": csrf}, "csrf": csrf}
    other.close()
