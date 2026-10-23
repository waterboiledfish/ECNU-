"""推理模型空回复、索引非阻塞、B 站风控降级等健壮性用例。"""
from __future__ import annotations


class _FakeResponse:
    def __init__(self, payload: dict, status: int = 200):
        self._payload = payload
        self.status_code = status

    def json(self) -> dict:
        return self._payload


def _patch_post(monkeypatch, payload: dict, status: int = 200):
    from app.services import llm

    def fake_post(*args, **kwargs):
        return _FakeResponse(payload, status)

    monkeypatch.setattr(llm.requests, "post", fake_post)


def test_llm_uses_reasoning_content_when_content_empty(monkeypatch):
    from app.services import llm

    _patch_post(
        monkeypatch,
        {"choices": [{"message": {"content": "", "reasoning_content": "先分析一下，再给结论。"}}]},
    )
    text = llm.chat(
        [{"role": "user", "content": "你好"}],
        key="sk-1234567890abcdefghij",
        model="deepseek-reasoner",
    )
    assert text == "先分析一下，再给结论。"


def test_llm_raises_actionable_error_when_both_empty(monkeypatch):
    from app.services import llm

    _patch_post(monkeypatch, {"choices": [{"message": {"content": "   ", "reasoning_content": ""}}]})
    try:
        llm.chat(
            [{"role": "user", "content": "你好"}],
            key="sk-1234567890abcdefghij",
            model="deepseek-reasoner",
        )
    except llm.LLMError as exc:
        assert "空内容" in exc.message
        assert "推理模型" in exc.message
    else:
        raise AssertionError("空回复应当抛出 LLMError")


def test_index_fast_stats_never_builds(monkeypatch, auth):
    from app.services import index

    index.invalidate()
    monkeypatch.setattr(index, "build_index", lambda *a, **k: (_ for _ in ()).throw(AssertionError("不应同步建索引")))
    monkeypatch.setattr(index, "warmup_async", lambda: None)
    stats = index.stats(fast=True)
    assert stats["building"] is True
    assert stats["chunks"] == 0


def test_crawl_start_does_not_deadlock(auth):
    """曾经的 bug：start() 持锁调用 status()，普通 Lock 直接死锁，整站卡住。"""
    import time

    from app.services.crawler import CrawlManager

    manager = CrawlManager()
    manager._run = lambda run_id, sites: None  # 不真的联网
    result = manager.start([], None)
    assert result["running"] is True

    started = time.time()
    state = manager.status()
    assert time.time() - started < 2, "status() 读取不应被锁住"
    assert state["run_id"] == result["run_id"]
    assert state["running"] is True


def test_version_has_single_source(client):
    import app
    from app.config import settings

    assert app.__version__ == settings.version
    assert client.get("/api/health").json()["version"] == settings.version


def test_study_falls_back_when_bilibili_blocked(monkeypatch):
    from app.services import recs

    def blocked(*args, **kwargs):
        raise recs.BiliBlocked("412 risk control")

    monkeypatch.setattr(recs, "_search", blocked)
    payload = recs.recommend({"courses": ["线性代数"], "directions": []}, refresh=True)
    assert payload["mode"] == "fallback"
    assert payload["videos"] and payload["videos"][0]["url"].startswith("https://search.bilibili.com/")
    assert payload["searches"][0]["query"].startswith("线性代数")
    assert payload["cached"] is False
