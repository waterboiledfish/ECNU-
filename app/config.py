"""运行配置：环境变量 + 可选 .env 文件。

所有配置带 ECNU_ 前缀。密钥类配置只保存在部署者环境中，
用户自己的模型 API Key 永远不进入本模块，也不写入数据库。
"""
from __future__ import annotations

import os
import secrets
from dataclasses import dataclass, field
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent


def load_dotenv(path: Path) -> None:
    """极简 .env 解析器：KEY=VALUE，忽略注释，不覆盖已有环境变量。"""
    if not path.is_file():
        return
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return
    for line in lines:
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        if key.startswith("export "):
            key = key[7:].strip()
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "'\"":
            value = value[1:-1]
        if key and key not in os.environ:
            os.environ[key] = value


load_dotenv(PROJECT_ROOT / ".env")


def _env(name: str, default: str = "") -> str:
    return os.environ.get(f"ECNU_{name}", default).strip()


def _env_bool(name: str, default: bool) -> bool:
    raw = _env(name, "true" if default else "false").lower()
    return raw in {"1", "true", "yes", "on"}


def _env_int(name: str, default: int) -> int:
    try:
        return int(_env(name, str(default)))
    except ValueError:
        return default


def _env_float(name: str, default: float) -> float:
    try:
        return float(_env(name, str(default)))
    except ValueError:
        return default


def _env_list(name: str, default: str = "") -> list[str]:
    raw = _env(name, default)
    return [x.strip() for x in raw.split(",") if x.strip()]


def _default_data_dir() -> Path:
    raw = _env("DATA_DIR")
    if raw:
        return Path(raw).expanduser().resolve()
    return (Path.home() / ".ecnu-assistant").resolve()


@dataclass
class Settings:
    """应用配置。实例在进程内只读使用。"""

    data_dir: Path = field(default_factory=_default_data_dir)
    host: str = field(default_factory=lambda: _env("HOST", "127.0.0.1"))
    port: int = field(default_factory=lambda: _env_int("PORT", 8765))
    public_base_url: str = field(
        default_factory=lambda: _env("PUBLIC_BASE_URL", "http://127.0.0.1:8765").rstrip("/")
    )
    timezone: str = field(default_factory=lambda: _env("TIMEZONE", "Asia/Shanghai"))
    cookie_secure: bool = field(default_factory=lambda: _env_bool("COOKIE_SECURE", False))
    secret_key: str = field(default_factory=lambda: _env("SECRET_KEY"))

    # 登录
    auth_mode: str = field(default_factory=lambda: _env("AUTH_MODE", "dev").lower())
    dev_login_enabled: bool = field(default_factory=lambda: _env_bool("DEV_LOGIN_ENABLED", True))
    admin_subjects: list[str] = field(default_factory=lambda: _env_list("ADMIN_SUBJECTS"))

    cas_base_url: str = field(default_factory=lambda: _env("CAS_BASE_URL").rstrip("/"))
    cas_login_path: str = field(default_factory=lambda: _env("CAS_LOGIN_PATH", "/cas/login"))
    cas_validate_path: str = field(
        default_factory=lambda: _env("CAS_VALIDATE_PATH", "/cas/serviceValidate")
    )
    cas_service_url: str = field(default_factory=lambda: _env("CAS_SERVICE_URL").rstrip("/"))

    oidc_issuer: str = field(default_factory=lambda: _env("OIDC_ISSUER").rstrip("/"))
    oidc_client_id: str = field(default_factory=lambda: _env("OIDC_CLIENT_ID"))
    oidc_client_secret: str = field(default_factory=lambda: _env("OIDC_CLIENT_SECRET"))
    oidc_redirect_uri: str = field(default_factory=lambda: _env("OIDC_REDIRECT_URI"))
    oidc_scope: str = field(default_factory=lambda: _env("OIDC_SCOPE", "openid profile"))

    # 模型默认值（用户 Key 不在此）
    llm_base_url: str = field(
        default_factory=lambda: _env("LLM_BASE_URL", "https://api.openai.com/v1").rstrip("/")
    )
    llm_model: str = field(default_factory=lambda: _env("LLM_MODEL", "gpt-4.1-mini"))

    moderation_base_url: str = field(
        default_factory=lambda: _env("MODERATION_BASE_URL").rstrip("/")
    )
    moderation_api_key: str = field(default_factory=lambda: _env("MODERATION_API_KEY"))
    moderation_model: str = field(default_factory=lambda: _env("MODERATION_MODEL"))
    moderation_fail_mode: str = field(
        default_factory=lambda: _env("MODERATION_FAIL_MODE", "review").lower()
    )

    tavily_api_key: str = field(default_factory=lambda: _env("TAVILY_API_KEY"))
    news_cache_minutes: int = field(default_factory=lambda: _env_int("NEWS_CACHE_MINUTES", 20))
    openalex_mailto: str = field(default_factory=lambda: _env("OPENALEX_MAILTO"))

    # 采集
    crawl_max_pages_per_site: int = field(
        default_factory=lambda: _env_int("CRAWL_MAX_PAGES_PER_SITE", 30)
    )
    crawl_max_depth: int = field(default_factory=lambda: _env_int("CRAWL_MAX_DEPTH", 3))
    crawl_delay_seconds: float = field(
        default_factory=lambda: _env_float("CRAWL_DELAY_SECONDS", 1.0)
    )
    crawl_timeout_seconds: int = field(
        default_factory=lambda: _env_int("CRAWL_TIMEOUT_SECONDS", 15)
    )
    crawl_allowed_suffixes: list[str] = field(
        default_factory=lambda: _env_list("CRAWL_ALLOWED_SUFFIXES", "ecnu.edu.cn")
    )
    allow_user_crawl: bool = field(default_factory=lambda: _env_bool("ALLOW_USER_CRAWL", True))

    portal_url: str = field(
        default_factory=lambda: _env(
            "PORTAL_URL", "https://portal2023.ecnu.edu.cn/portal/home"
        )
    )

    # 常量
    app_name: str = "ECNU 小助手"
    version: str = "1.0.1"
    max_body_bytes: int = 1_200_000
    session_ttl_days: int = 30
    max_upload_bytes: int = 600_000
    user_agent: str = "ECNU-Assistant/1.0 (+https://github.com/waterboiledfish/ECNU-)"

    def __post_init__(self) -> None:
        self.data_dir = Path(self.data_dir)
        self.data_dir.mkdir(parents=True, exist_ok=True)
        (self.data_dir / "avatars").mkdir(exist_ok=True)
        (self.data_dir / "popups").mkdir(exist_ok=True)
        if not self.secret_key:
            self.secret_key = self._load_or_create_secret()

    @property
    def db_path(self) -> Path:
        return self.data_dir / "assistant.db"

    @property
    def avatar_dir(self) -> Path:
        return self.data_dir / "avatars"

    @property
    def popup_dir(self) -> Path:
        return self.data_dir / "popups"

    def _load_or_create_secret(self) -> str:
        path = self.data_dir / "secret.key"
        try:
            existing = path.read_text(encoding="utf-8").strip()
            if existing:
                return existing
        except OSError:
            pass
        value = secrets.token_hex(32)
        try:
            path.write_text(value, encoding="utf-8")
        except OSError:
            pass
        return value

    @property
    def auth_configured(self) -> bool:
        if self.auth_mode == "cas":
            return bool(self.cas_base_url)
        if self.auth_mode == "oidc":
            return bool(self.oidc_issuer and self.oidc_client_id and self.oidc_redirect_uri)
        return self.dev_login_enabled

    @property
    def auth_label(self) -> str:
        return {"cas": "学校统一身份认证 (CAS)", "oidc": "学校统一身份认证 (OIDC)"}.get(
            self.auth_mode, "本地演示模式"
        )


settings = Settings()
