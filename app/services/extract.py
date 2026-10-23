"""网页 / PDF / DOCX 文本抽取与安全的 URL 过滤。"""
from __future__ import annotations

import io
import os
import re
import shutil
import subprocess
import tempfile
import zipfile
from datetime import date, datetime
from pathlib import Path
from urllib.parse import urljoin, urlparse, urlunparse

import requests
from bs4 import BeautifulSoup

from ..config import settings

HTML_TYPES = {"text/html", "application/xhtml+xml"}
TEXT_TYPES = {"text/plain"}
PDF_TYPES = {"application/pdf"}
DOCX_TYPES = {
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "application/msword",
}

ALLOWED_EXTENSIONS = {"", ".html", ".htm", ".shtml", ".pdf", ".docx", ".doc", ".txt"}
BLOCKED_EXTENSIONS = {
    ".jpg", ".jpeg", ".png", ".gif", ".webp", ".svg", ".ico", ".css", ".js",
    ".zip", ".rar", ".7z", ".gz", ".tar", ".exe", ".apk", ".msi", ".mp4",
    ".mp3", ".avi", ".mov", ".wmv", ".xls", ".xlsx", ".ppt", ".pptx",
}


class FetchError(Exception):
    pass


def host_allowed(url: str, suffixes: list[str] | None = None) -> bool:
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        return False
    if parsed.username or parsed.password:
        return False
    host = parsed.hostname.lower()
    for suffix in suffixes or settings.crawl_allowed_suffixes:
        suffix = suffix.lower().lstrip(".")
        if host == suffix or host.endswith("." + suffix):
            return True
    return False


def normalize_url(base: str, href: str) -> str | None:
    if not href:
        return None
    href = href.strip()
    if href.startswith(("javascript:", "mailto:", "tel:", "#")):
        return None
    # 有些站点把整段 HTML 塞进 href（例如 <a href="<a href=...>"），这种链接必然 404
    if any(char in href for char in "<> \t\n"):
        return None
    # 有些站点把邮箱写成 href="name@domain"（没写 mailto:），别当页面去抓
    if "@" in href and not href.lower().startswith(("http://", "https://", "//")):
        return None
    absolute = urljoin(base, href)
    parsed = urlparse(absolute)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        return None
    if parsed.username or parsed.password:
        return None
    path = parsed.path or "/"
    if any(path.lower().endswith(ext) for ext in BLOCKED_EXTENSIONS):
        return None
    return urlunparse((parsed.scheme, parsed.netloc.lower(), path, "", parsed.query, ""))


def path_extension(url: str) -> str:
    path = urlparse(url).path.lower()
    for ext in ALLOWED_EXTENSIONS:
        if ext and path.endswith(ext):
            return ext
    return ""


def fetch(url: str, *, timeout: int | None = None, max_bytes: int = 8_000_000) -> dict:
    timeout = timeout or settings.crawl_timeout_seconds
    headers = {
        "User-Agent": settings.user_agent,
        "Accept": "text/html,application/xhtml+xml,application/pdf,text/plain;q=0.9,*/*;q=0.5",
        "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.6",
    }
    try:
        response = requests.get(
            url,
            headers=headers,
            timeout=timeout,
            allow_redirects=True,
            stream=True,
        )
    except requests.exceptions.SSLError:
        return _fetch_with_curl(url, timeout=timeout, max_bytes=max_bytes)
    except requests.RequestException as exc:
        message = str(exc)
        if "SSL" in message or "EOF occurred" in message:
            return _fetch_with_curl(url, timeout=timeout, max_bytes=max_bytes)
        raise FetchError(f"网络错误：{exc.__class__.__name__}") from None
    try:
        if response.status_code >= 400:
            raise FetchError(f"HTTP {response.status_code}")
        content_type = (response.headers.get("Content-Type") or "").split(";")[0].strip().lower()
        length = response.headers.get("Content-Length")
        if length and length.isdigit() and int(length) > max_bytes:
            raise FetchError("响应体过大")
        buffer = bytearray()
        for part in response.iter_content(65536):
            buffer.extend(part)
            if len(buffer) > max_bytes:
                raise FetchError("响应体过大")
        if not buffer:
            raise FetchError("空响应")
        return {
            "url": response.url,
            "status": response.status_code,
            "content_type": content_type,
            "charset": response.encoding or "utf-8",
            "data": bytes(buffer),
        }
    finally:
        response.close()


def _fetch_with_curl(url: str, *, timeout: int, max_bytes: int) -> dict:
    """Python/OpenSSL 被部分校园 WAF 拒绝时，退回系统 curl（Schannel/系统 CA）。

    curl 默认校验证书；不添加 -k。URL 作为参数传递，不经过 shell。
    """
    curl = shutil.which("curl")
    if not curl:
        raise FetchError("TLS 握手失败，且系统未安装 curl，无法回退抓取")
    fd, path = tempfile.mkstemp(prefix="ecnu-fetch-", suffix=".bin")
    os.close(fd)
    try:
        command = [
            curl,
            "-sS",
            "-L",
            "--max-redirs",
            "5",
            "--compressed",
            "--max-time",
            str(max(5, timeout)),
            "--max-filesize",
            str(max_bytes),
            "-A",
            settings.user_agent,
            "-o",
            path,
            "-w",
            "%{http_code}\t%{content_type}\t%{url_effective}",
            url,
        ]
        try:
            result = subprocess.run(
                command,
                capture_output=True,
                text=True,
                timeout=max(10, timeout + 5),
                encoding="utf-8",
                errors="replace",
            )
        except subprocess.TimeoutExpired:
            raise FetchError("请求超时") from None
        meta = (result.stdout or "").strip().split("\t")
        code = meta[0] if meta else "0"
        content_type = (meta[1] if len(meta) > 1 else "").split(";")[0].strip().lower()
        final_url = meta[2] if len(meta) > 2 else url
        if result.returncode != 0 or not code.isdigit() or int(code) >= 400:
            raise FetchError(f"curl 抓取失败（HTTP {code}）")
        data = Path(path).read_bytes()
        if not data:
            raise FetchError("空响应")
        if len(data) > max_bytes:
            raise FetchError("响应体过大")
        return {
            "url": final_url,
            "status": int(code),
            "content_type": content_type,
            "charset": "utf-8",
            "data": data,
        }
    finally:
        try:
            os.unlink(path)
        except OSError:
            pass


def _clean_text(text: str) -> str:
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = re.sub(r"[ \t\u00a0]+", " ", text)
    lines = [line.strip() for line in text.split("\n")]
    output: list[str] = []
    blank = 0
    for line in lines:
        if not line:
            blank += 1
            if blank <= 1 and output:
                output.append("")
            continue
        blank = 0
        output.append(line)
    return "\n".join(output).strip()


_DECLARED_CHARSET = re.compile(rb"charset\s*=\s*[\"']?([\w-]+)", re.I)
# 这些编码永远不会解码失败，但会产出乱码：不能直接信
_WEAK_CHARSETS = {"", "iso-8859-1", "latin-1", "latin1", "ascii", "us-ascii"}


def _decode(data: bytes, charset: str) -> str:
    declared = (charset or "").strip().lower()
    if declared in _WEAK_CHARSETS:
        # HTTP 头没写 charset 时 requests 会给 ISO-8859-1，此时以页面 <meta charset> 为准
        match = _DECLARED_CHARSET.search(data[:4096])
        if match:
            candidate = match.group(1).decode("ascii", "ignore").strip().lower()
            if candidate and candidate not in _WEAK_CHARSETS:
                declared = candidate
    order = [declared] if declared and declared not in _WEAK_CHARSETS else []
    for encoding in [*order, "utf-8", "gb18030", "gbk"]:
        try:
            return data.decode(encoding)
        except (LookupError, UnicodeDecodeError):
            continue
    return data.decode("utf-8", "ignore")


def parse_date(value: str | None) -> str | None:
    if not value:
        return None
    raw = str(value).strip()
    match = re.search(r"(20\d{2})[-年/.](\d{1,2})[-月/.](\d{1,2})", raw)
    if match:
        year, month, day = (int(x) for x in match.groups())
        try:
            return date(year, month, day).isoformat()
        except ValueError:
            return None
    match = re.search(r"(20\d{2})-(\d{1,2})-(\d{1,2})", raw)
    if match:
        try:
            return date(*(int(x) for x in match.groups())).isoformat()
        except ValueError:
            return None
    return None


def html_to_content(data: bytes, url: str, charset: str = "utf-8") -> dict:
    html = _decode(data, charset)
    soup = BeautifulSoup(html, "html.parser")
    title = ""
    og_title = soup.find("meta", attrs={"property": "og:title"})
    if og_title and og_title.get("content"):
        title = og_title["content"].strip()
    if not title and soup.title and soup.title.string:
        title = soup.title.string.strip()
    if not title:
        h1 = soup.find("h1")
        title = h1.get_text(" ", strip=True) if h1 else ""

    published = None
    for attrs in (
        {"property": "article:published_time"},
        {"name": "publishdate"},
        {"name": "pubdate"},
        {"name": "date"},
        {"itemprop": "datePublished"},
    ):
        node = soup.find("meta", attrs=attrs)
        if node and node.get("content"):
            published = parse_date(node["content"])
            if published:
                break
    if not published:
        time_node = soup.find("time")
        if time_node:
            published = parse_date(time_node.get("datetime") or time_node.get_text(" ", strip=True))

    for tag in soup(["script", "style", "noscript", "svg", "iframe", "form", "nav", "footer"]):
        tag.decompose()
    container = None
    for selector in ("article", "main", "#content", ".content", ".article", ".v_news_content", ".wp_articlecontent"):
        container = soup.select_one(selector)
        if container is not None and len(container.get_text(strip=True)) > 200:
            break
        container = None
    root = container if container is not None else (soup.body or soup)
    text = _clean_text(root.get_text("\n"))
    if not published:
        published = parse_date(text[:2000])
    links: list[str] = []
    link_items: list[dict[str, str]] = []
    for anchor in soup.find_all("a", href=True):
        absolute = normalize_url(url, anchor["href"])
        if absolute and absolute not in links:
            links.append(absolute)
            link_items.append({"url": absolute, "text": anchor.get_text(" ", strip=True)[:120]})
    return {
        "title": title[:200] or urlparse(url).path,
        "text": text[:200_000],
        "published_at": published,
        "links": links[:400],
        "link_items": link_items[:400],
        "kind": "html",
    }


def pdf_to_content(data: bytes, url: str) -> dict:
    try:
        from pypdf import PdfReader
    except ImportError:  # pragma: no cover
        raise FetchError("未安装 pypdf，无法解析 PDF") from None
    try:
        reader = PdfReader(io.BytesIO(data))
    except Exception:
        raise FetchError("PDF 解析失败，文件可能损坏") from None
    pages: list[str] = []
    for page in reader.pages[:80]:
        try:
            pages.append(page.extract_text() or "")
        except Exception:
            continue
    text = _clean_text("\n".join(pages))
    if len(text) < 40:
        raise FetchError("PDF 未提取到文字（可能是扫描件）")
    title = ""
    try:
        meta = reader.metadata or {}
        title = str(meta.get("/Title") or "").strip()
        published = parse_date(str(meta.get("/CreationDate") or ""))
    except Exception:
        published = None
    if not published:
        published = parse_date(text[:1000])
    return {
        "title": title[:200] or urlparse(url).path.rsplit("/", 1)[-1],
        "text": text[:200_000],
        "published_at": published,
        "links": [],
        "kind": "pdf",
    }


def docx_to_content(data: bytes, url: str) -> dict:
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            xml = archive.read("word/document.xml").decode("utf-8", "ignore")
    except (zipfile.BadZipFile, KeyError):
        raise FetchError("DOCX 解析失败") from None
    from xml.etree import ElementTree as ET

    ns = {"w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main"}
    try:
        root = ET.fromstring(xml)
    except ET.ParseError:
        raise FetchError("DOCX 文档结构异常") from None
    paragraphs = []
    for para in root.findall(".//w:p", ns):
        texts = [node.text or "" for node in para.findall(".//w:t", ns)]
        if texts:
            paragraphs.append("".join(texts))
    text = _clean_text("\n".join(paragraphs))
    if not text:
        raise FetchError("DOCX 未提取到文字")
    return {
        "title": urlparse(url).path.rsplit("/", 1)[-1],
        "text": text[:200_000],
        "published_at": parse_date(text[:1000]),
        "links": [],
        "kind": "docx",
    }


def text_to_content(data: bytes, url: str, charset: str = "utf-8") -> dict:
    text = _clean_text(_decode(data, charset))
    return {
        "title": urlparse(url).path.rsplit("/", 1)[-1],
        "text": text[:200_000],
        "published_at": parse_date(text[:1000]),
        "links": [],
        "kind": "text",
    }


def extract(url: str, content_type: str, data: bytes, charset: str = "utf-8") -> dict:
    ctype = (content_type or "").lower()
    ext = path_extension(url)
    if ctype in PDF_TYPES or ext == ".pdf":
        return pdf_to_content(data, url)
    if ctype in DOCX_TYPES or ext in {".docx", ".doc"}:
        if ext == ".doc":
            raise FetchError("暂不支持旧版 .doc，请提供 PDF 或 DOCX")
        return docx_to_content(data, url)
    if ctype in TEXT_TYPES or ext == ".txt":
        return text_to_content(data, url, charset)
    return html_to_content(data, url, charset)


def chunk_text(text: str, size: int = 700, overlap: int = 1) -> list[str]:
    paragraphs = [p.strip() for p in re.split(r"\n+", text) if p.strip()]
    if not paragraphs:
        return []
    chunks: list[str] = []
    current: list[str] = []
    current_len = 0
    for para in paragraphs:
        if len(para) > size:
            if current:
                chunks.append("\n".join(current))
                current, current_len = [], 0
            step = max(200, size - 100)
            for start in range(0, len(para), step):
                chunks.append(para[start : start + size])
        elif current_len + len(para) > size and current:
            chunks.append("\n".join(current))
            current = current[-overlap:] if overlap else []
            current_len = sum(len(x) for x in current)
            current.append(para)
            current_len += len(para)
        else:
            current.append(para)
            current_len += len(para)
    if current:
        chunks.append("\n".join(current))
    return [c for c in chunks if c.strip()]


def now_date() -> str:
    return datetime.now().date().isoformat()
