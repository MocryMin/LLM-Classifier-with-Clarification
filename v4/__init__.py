"""
v4 - V4 两阶段渐进式注入意图路由层
==================================
接口与 V3 一致: from v4.entrance import entrance; entrance(messages)

内核: Layer_1 (Flash + 名称定义摘要 -> top-k) + Layer_2 (Flash + k 候选完整描述 -> top-1)
类别定义与辅助信息从 V3 prompter 生成的 prompt.txt 中解析。
用户须提供自己的 DeepSeek API key (环境变量 DEEPSEEK_API_KEY 或 entrance(api_key=...))。
"""

from .entrance import entrance

__all__ = ["entrance"]
