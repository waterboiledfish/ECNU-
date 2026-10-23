"""中英文检索分词：中文二元组 + 英文单词，无需额外词表依赖。"""
from __future__ import annotations

import re
import unicodedata

_TOKEN_RE = re.compile(r"[a-zA-Z0-9_+#.@-]+|[\u3400-\u4dbf\u4e00-\u9fff]+")

EN_STOP = {
    "the", "a", "an", "and", "or", "of", "to", "in", "on", "for", "with",
    "is", "are", "was", "were", "be", "been", "it", "this", "that", "these",
    "those", "as", "at", "by", "from", "we", "you", "they", "he", "she", "i",
    "do", "does", "did", "can", "could", "will", "would", "should", "may",
    "not", "no", "yes", "how", "what", "which", "who", "whom", "when", "where",
    "why", "about", "into", "than", "then", "so", "if", "but", "also", "more",
    "most", "some", "any", "all", "each", "other", "such", "only", "own", "too",
}

CN_STOP = {
    "的", "了", "和", "是", "在", "有", "我", "你", "他", "她", "它", "这", "那",
    "吗", "呢", "吧", "啊", "与", "及", "或", "等", "就", "都", "也", "而", "被",
    "把", "对", "从", "到", "为", "以", "于", "之", "其", "中", "上", "下", "不",
    "很", "更", "请", "问", "如何", "怎么", "怎样", "哪些", "是否", "可以",
    "我们", "你们", "他们", "这个", "那个", "如果", "因为", "所以", "但是", "并且",
    "一个", "一些", "时候", "现在", "已经", "还是", "以及", "关于", "通过",
}


def normalize(text: str) -> str:
    return unicodedata.normalize("NFKC", text or "").lower()


def tokenize(text: str) -> list[str]:
    out: list[str] = []
    for match in _TOKEN_RE.finditer(normalize(text)):
        chunk = match.group(0)
        if chunk[0].isascii():
            if len(chunk) >= 2 and chunk not in EN_STOP:
                out.append(chunk[:40])
            continue
        run = chunk[:120]
        if len(run) == 1:
            if run not in CN_STOP:
                out.append(run)
            continue
        for i in range(len(run) - 1):
            bigram = run[i : i + 2]
            if bigram not in CN_STOP:
                out.append(bigram)
        if len(run) <= 4 and run not in CN_STOP:
            out.append(run)
    return out


def query_terms(text: str) -> list[str]:
    """检索用去重词项；保留顺序。"""
    seen: set[str] = set()
    result: list[str] = []
    for token in tokenize(text):
        if token not in seen:
            seen.add(token)
            result.append(token)
    return result


def highlight_terms(text: str) -> list[str]:
    return [t for t in query_terms(text) if len(t) >= 2][:12]
