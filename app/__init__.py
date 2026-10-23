"""ECNU 小助手 —— 面向华东师范大学学生的本地优先 AI 助手。"""

from .config import settings as _settings

# 版本号只维护一处：config.Settings.version（健康检查、OpenAPI 文档、日志都读它）
__version__ = _settings.version

__all__ = ["__version__"]
