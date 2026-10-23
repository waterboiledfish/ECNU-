"""登录：本地演示、学校 CAS、学校 OIDC。

原则：
- 本项目永远不接触、不存储学号和密码；凭据只在学校统一认证页面输入。
- 服务端只保存认证系统返回的稳定标识（sso_subject），用于关联本应用账号。
- dev 模式仅用于本地体验，界面上会明确标注。
"""
from __future__ import annotations

import base64
import hashlib
import json
import secrets
import time
import urllib.parse
from datetime import timedelta

import requests
from fastapi import APIRouter, HTTPException, Request, Response
from fastapi.responses import RedirectResponse
from pydantic import BaseModel

from ..config import settings
from ..db import db, jdumps, jloads
from ..security import (
    DEVICE_COOKIE,
    STATE_COOKIE,
    clear_session_cookie,
    client_ip,
    create_session,
    enforce_rate,
    is_admin_subject,
    load_user,
    optional_user,
    public_user,
    revoke_session,
    set_session_cookie,
)
from ..timeutil import iso, now_utc

router = APIRouter(prefix="/api/auth", tags=["auth"])

_OIDC_CACHE: dict[str, object] = {"data": None, "expires": 0.0}


class DevLogin(BaseModel):
    nickname: str = ""


def auth_meta() -> dict[str, object]:
    return {
        "mode": settings.auth_mode,
        "label": settings.auth_label,
        "configured": settings.auth_configured,
        "dev_login": settings.auth_mode == "dev" and settings.dev_login_enabled,
        "portal_url": settings.portal_url,
        "notice": (
            "当前为本地演示登录，未连接学校统一身份认证。"
            if settings.auth_mode == "dev"
            else "登录由学校统一身份认证完成，本应用不接触、不保存学号和密码。"
        ),
    }


def _client(request: Request) -> tuple[str, str]:
    ip = client_ip(request)
    ua = request.headers.get("user-agent", "")
    return ip, ua


def _unique_nickname(conn, base: str) -> str:
    base = (base or "新同学").strip()[:12] or "新同学"
    candidate = base
    for _ in range(20):
        row = conn.execute("SELECT 1 FROM users WHERE nickname = ?", (candidate,)).fetchone()
        if not row:
            return candidate
        candidate = f"{base}{secrets.randbelow(90) + 10}"
    return f"同学{secrets.token_hex(2)}"


def _upsert_sso_user(
    conn, provider: str, subject: str, nickname_hint: str = ""
) -> dict:
    full_subject = f"{provider}:{subject}"
    row = conn.execute("SELECT * FROM users WHERE sso_subject = ?", (full_subject,)).fetchone()
    now = iso(now_utc())
    if row:
        conn.execute("UPDATE users SET last_login_at = ? WHERE id = ?", (now, int(row["id"])))
        user = load_user(conn, int(row["id"]))
        assert user is not None
        return user
    nickname = _unique_nickname(conn, nickname_hint or "ECNUer")
    role = "admin" if is_admin_subject(full_subject) else "user"
    cur = conn.execute(
        "INSERT INTO users (sso_subject, sso_provider, nickname, role, created_at, last_login_at) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (full_subject, provider, nickname, role, now, now),
    )
    user = load_user(conn, int(cur.lastrowid))
    assert user is not None
    return user


def _login_payload(user: dict, csrf: str) -> dict:
    payload = public_user(user)
    payload["csrf"] = csrf
    payload["directions"] = user.get("directions", [])
    payload["courses"] = user.get("courses", [])
    payload["settings"] = user.get("settings", {})
    payload["is_admin"] = user.get("role") == "admin"
    return payload


@router.get("/config")
def get_auth_config():
    return auth_meta()


@router.get("/me")
def me(request: Request):
    user = optional_user(request)
    if not user:
        return {"authenticated": False, "user": None, "csrf": None, "auth": auth_meta()}
    return {
        "authenticated": True,
        "user": _login_payload(user, user.get("csrf", "")),
        "csrf": user.get("csrf", ""),
        "auth": auth_meta(),
    }


@router.post("/dev-login")
def dev_login(payload: DevLogin, request: Request, response: Response):
    if settings.auth_mode != "dev" or not settings.dev_login_enabled:
        raise HTTPException(status_code=403, detail="演示登录未开启")
    enforce_rate(request, "dev-login", 12, 300)
    device = request.cookies.get(DEVICE_COOKIE)
    fresh_device = not device
    if not device:
        device = secrets.token_urlsafe(24)
        response.set_cookie(
            DEVICE_COOKIE,
            device,
            max_age=365 * 86400,
            httponly=True,
            samesite="lax",
            secure=settings.cookie_secure,
            path="/",
        )
    ip, ua = _client(request)
    with db() as conn:
        user = _upsert_sso_user(conn, "dev", device, payload.nickname)
        token, csrf = create_session(conn, int(user["id"]), ip, ua)
        if fresh_device and not user.get("nickname"):
            pass
    set_session_cookie(response, token)
    return {
        "authenticated": True,
        "user": _login_payload(user, csrf),
        "csrf": csrf,
        "auth": auth_meta(),
    }


@router.post("/logout")
def logout(request: Request, response: Response):
    token = request.cookies.get("ecnu_session")
    if token:
        with db() as conn:
            revoke_session(conn, token)
    clear_session_cookie(response)
    response.delete_cookie(STATE_COOKIE, path="/")
    return {"ok": True}


# ---------------------------------------------------------------- CAS
def _cas_service(request: Request, state: str = "") -> str:
    base = settings.cas_service_url or f"{settings.public_base_url}/api/auth/cas/callback"
    if state:
        sep = "&" if "?" in base else "?"
        return f"{base}{sep}state={urllib.parse.quote(state)}"
    return base


def _cas_validate(ticket: str, service: str) -> str:
    url = f"{settings.cas_base_url}{settings.cas_validate_path}"
    params = {"service": service, "ticket": ticket, "format": "JSON"}
    response = requests.get(
        url,
        params=params,
        timeout=12,
        headers={"User-Agent": settings.user_agent, "Accept": "application/json, application/xml"},
    )
    response.raise_for_status()
    text = response.text.strip()
    if not text:
        raise ValueError("CAS 返回空响应")
    try:
        data = response.json()
        success = (
            data.get("serviceResponse", {}).get("authenticationSuccess")
            or data.get("authenticationSuccess")
        )
        if success and success.get("user"):
            return str(success["user"])
        raise ValueError("CAS 认证失败")
    except json.JSONDecodeError:
        import xml.etree.ElementTree as ET

        root = ET.fromstring(text)
        for node in root.iter():
            if node.tag.endswith("user") and node.text:
                return node.text.strip()
        raise ValueError("无法解析 CAS 响应") from None


@router.get("/cas/login")
def cas_login(request: Request):
    if settings.auth_mode != "cas" or not settings.cas_base_url:
        raise HTTPException(status_code=503, detail="学校统一认证尚未配置")
    enforce_rate(request, "cas-login", 20, 300)
    state = secrets.token_urlsafe(24)
    service = _cas_service(request, state)
    login_url = f"{settings.cas_base_url}{settings.cas_login_path}"
    target = f"{login_url}?service={urllib.parse.quote(service, safe='')}"
    redirect = RedirectResponse(target, status_code=302)
    redirect.set_cookie(
        STATE_COOKIE,
        state,
        max_age=600,
        httponly=True,
        samesite="lax",
        secure=settings.cookie_secure,
        path="/",
    )
    return redirect


@router.get("/cas/callback")
def cas_callback(request: Request, ticket: str = "", state: str = ""):
    if not ticket:
        return _sso_error("缺少认证票据")
    expected = request.cookies.get(STATE_COOKIE, "")
    if not expected or not state or not secrets.compare_digest(expected, state):
        return _sso_error("登录状态校验失败，请重新登录")
    service = _cas_service(request, state)
    try:
        principal = _cas_validate(ticket, service)
    except requests.RequestException:
        return _sso_error("无法连接学校认证服务，请稍后重试")
    except ValueError:
        return _sso_error("学校认证未通过，请重新登录")
    ip, ua = _client(request)
    with db() as conn:
        user = _upsert_sso_user(conn, "cas", principal, "ECNUer")
        token, _csrf = create_session(conn, int(user["id"]), ip, ua)
    redirect = RedirectResponse("/", status_code=303)
    set_session_cookie(redirect, token)
    redirect.delete_cookie(STATE_COOKIE, path="/")
    return redirect


# ---------------------------------------------------------------- OIDC
def _discovery() -> dict:
    if _OIDC_CACHE["data"] and float(_OIDC_CACHE["expires"]) > time.time():
        return _OIDC_CACHE["data"]  # type: ignore[return-value]
    if not settings.oidc_issuer:
        raise HTTPException(status_code=503, detail="OIDC 尚未配置")
    url = f"{settings.oidc_issuer}/.well-known/openid-configuration"
    response = requests.get(url, timeout=12, headers={"User-Agent": settings.user_agent})
    response.raise_for_status()
    data = response.json()
    for key in ("authorization_endpoint", "token_endpoint"):
        if not data.get(key):
            raise ValueError(f"OIDC 配置缺少 {key}")
    _OIDC_CACHE["data"] = data
    _OIDC_CACHE["expires"] = time.time() + 3600
    return data


def _oidc_redirect_uri() -> str:
    return settings.oidc_redirect_uri or f"{settings.public_base_url}/api/auth/oidc/callback"


@router.get("/oidc/login")
def oidc_login(request: Request):
    if settings.auth_mode != "oidc":
        raise HTTPException(status_code=503, detail="OIDC 登录未启用")
    enforce_rate(request, "oidc-login", 20, 300)
    try:
        discovery = _discovery()
    except (requests.RequestException, ValueError):
        raise HTTPException(status_code=502, detail="无法加载学校 OIDC 配置") from None
    state = secrets.token_urlsafe(24)
    verifier = secrets.token_urlsafe(48)
    challenge = base64.urlsafe_b64encode(
        hashlib.sha256(verifier.encode("ascii")).digest()
    ).decode("ascii").rstrip("=")
    with db() as conn:
        conn.execute(
            "INSERT INTO auth_states (state, payload, created_at, expires_at) VALUES (?, ?, ?, ?)",
            (
                state,
                jdumps({"verifier": verifier, "next": "/"}),
                iso(now_utc()),
                iso(now_utc() + timedelta(minutes=10)),
            ),
        )
    params = {
        "response_type": "code",
        "client_id": settings.oidc_client_id,
        "redirect_uri": _oidc_redirect_uri(),
        "scope": settings.oidc_scope,
        "state": state,
        "code_challenge": challenge,
        "code_challenge_method": "S256",
    }
    return RedirectResponse(
        f"{discovery['authorization_endpoint']}?{urllib.parse.urlencode(params)}",
        status_code=302,
    )


@router.get("/oidc/callback")
def oidc_callback(request: Request, code: str = "", state: str = "", error: str = ""):
    if error:
        return _sso_error("学校认证未通过，请重新登录")
    if not code or not state:
        return _sso_error("认证回调参数不完整")
    with db() as conn:
        row = conn.execute(
            "SELECT * FROM auth_states WHERE state = ? AND expires_at > ?",
            (state, iso(now_utc())),
        ).fetchone()
        if not row:
            return _sso_error("登录状态已失效，请重新登录")
        payload = jloads(row["payload"], {})
        conn.execute("DELETE FROM auth_states WHERE state = ?", (state,))
    try:
        discovery = _discovery()
        data = {
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": _oidc_redirect_uri(),
            "client_id": settings.oidc_client_id,
            "code_verifier": payload.get("verifier", ""),
        }
        auth = None
        if settings.oidc_client_secret:
            auth = (settings.oidc_client_id, settings.oidc_client_secret)
        token_response = requests.post(
            discovery["token_endpoint"],
            data=data,
            auth=auth,
            timeout=15,
            headers={"User-Agent": settings.user_agent},
        )
        token_response.raise_for_status()
        tokens = token_response.json()
        access_token = tokens.get("access_token")
        if not access_token:
            raise ValueError("OIDC 未返回 access_token")
        userinfo_endpoint = discovery.get("userinfo_endpoint")
        if not userinfo_endpoint:
            raise ValueError("OIDC 缺少 userinfo_endpoint，出于安全考虑不再继续")
        info = requests.get(
            userinfo_endpoint,
            headers={"Authorization": f"Bearer {access_token}", "User-Agent": settings.user_agent},
            timeout=12,
        )
        info.raise_for_status()
        profile = info.json()
        subject = str(profile.get("sub") or profile.get("preferred_username") or "")
        if not subject:
            raise ValueError("OIDC 用户信息缺少 sub")
        nickname = str(profile.get("name") or profile.get("preferred_username") or "ECNUer")
    except (requests.RequestException, ValueError, KeyError):
        return _sso_error("学校认证信息校验失败，请稍后重试")
    ip, ua = _client(request)
    with db() as conn:
        user = _upsert_sso_user(conn, "oidc", subject, nickname[:12])
        token, _csrf = create_session(conn, int(user["id"]), ip, ua)
    redirect = RedirectResponse(payload.get("next") or "/", status_code=303)
    set_session_cookie(redirect, token)
    return redirect


def _sso_error(message: str) -> RedirectResponse:
    target = "/?auth_error=" + urllib.parse.quote(message)
    redirect = RedirectResponse(target, status_code=303)
    redirect.delete_cookie(STATE_COOKIE, path="/")
    return redirect
