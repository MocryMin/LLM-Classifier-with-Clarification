"""
llm.py - DeepSeek API 客户端
============================
**用户必须提供自己的 API key**, 本模块不内置任何 key。
按如下顺序解析 key:
  1. 调用时显式传入 api_key=
  2. 环境变量 DEEPSEEK_API_KEY
  3. 环境变量 DS_API_KEY
都没有则抛 RuntimeError, 指引获取方式。

获取 key: https://platform.deepseek.com/api_keys
"""

import os
import time
import random
from openai import OpenAI

DEFAULT_BASE_URL = "https://api.deepseek.com"
DEFAULT_FLASH = "deepseek-v4-flash"
DEFAULT_PRO = "deepseek-v4-pro"


def resolve_api_key(api_key: str | None = None) -> str:
    if api_key:
        return api_key
    env = os.environ.get("DEEPSEEK_API_KEY") or os.environ.get("DS_API_KEY")
    if env:
        return env
    raise RuntimeError(
        "未提供 DeepSeek API key。请:\n"
        "  (1) 设置环境变量 DEEPSEEK_API_KEY=<your-key>, 或\n"
        "  (2) 调用时传入 entrance(messages, api_key=<your-key>)\n"
        "获取 key: https://platform.deepseek.com/api_keys"
    )


class LLMClient:
    """DeepSeek 客户端, 带 429 退避与重试。"""

    def __init__(self, api_key: str | None = None, base_url: str | None = None):
        self.api_key = resolve_api_key(api_key)
        self.base_url = base_url or DEFAULT_BASE_URL
        self.client = OpenAI(api_key=self.api_key, base_url=self.base_url)

    def call(
        self,
        messages: list[dict],
        model: str = DEFAULT_FLASH,
        temperature: float = 0.1,
        thinking: str = "disabled",
        max_tokens: int = 4096,
        max_retries: int = 4,
    ) -> str:
        """调用 chat completion, 返回 content 文本(空串=重试耗尽)。"""
        for attempt in range(max_retries):
            try:
                resp = self.client.chat.completions.create(
                    model=model,
                    messages=messages,
                    temperature=temperature,
                    max_tokens=max_tokens,
                    extra_body={"thinking": {"type": thinking}},
                )
                content = (resp.choices[0].message.content or "").strip()
                if content:
                    return content
                if attempt < max_retries - 1:
                    time.sleep(1)
            except Exception as e:
                err = str(e)
                if "429" in err or "rate" in err.lower():
                    wait = 2 ** (attempt + 1) + random.uniform(0, 1)
                    time.sleep(wait)
                elif attempt < max_retries - 1:
                    time.sleep(2 ** attempt + random.uniform(0, 0.5))
                else:
                    raise
        return ""
