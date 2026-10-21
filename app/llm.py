"""模型抽象层（计划书 2.1 / T2.2）：用环境变量切换 Ollama 与 DeepSeek，业务代码不硬编码模型。

为什么要有这一层：
  开发期用本地 Ollama 免费、不占网；演示期一行配置切到 DeepSeek 云端效果好。
  把差异收敛在一个文件里，rag.py / main.py 不关心背后是谁。

约定：
  - LLM_PROVIDER=ollama   → ChatOllama(OLLAMA_MODEL)
  - LLM_PROVIDER=deepseek → ChatOpenAI(DEEPSEEK_MODEL, base_url=api.deepseek.com)
  - 模型名、地址、密钥全部来自 .env（config.settings），本文件不写死任何模型名。

关于 embedding 为什么直接调 Ollama HTTP 接口而不走 LangChain 的 OllamaEmbeddings：
  实测 langchain_ollama 的 embeddings 没有把 keep_alive 传下去，bge-m3 在每次请求
  之间会被 Ollama 卸载，检索前都要重新加载（单次 2.2 秒），首字延迟直接被顶到 5–6 秒。
  直连 /api/embed 并显式带 keep_alive 后，嵌入稳定在 0.18 秒、模型常驻。
  接口形态仍与 LangChain 兼容（embed_query / embed_documents），rag.py 无感。
"""
from __future__ import annotations

import json
import urllib.error
import urllib.request

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_ollama import ChatOllama
from langchain_openai import ChatOpenAI

from app.config import settings


def get_llm(temperature: float = 0.0, provider: str | None = None) -> BaseChatModel:
    """返回聊天模型实例。provider 显式传入时优先（支持界面上临时切云端/本地）。

    参数
        provider: "ollama" 或 "deepseek"；None 时用 .env 的 LLM_PROVIDER
    """
    provider = (provider or settings.llm_provider).lower()

    if provider == "ollama":
        return ChatOllama(
            model=settings.ollama_model,
            base_url=settings.ollama_base_url,
            temperature=temperature,
            # 常驻显存：默认 5 分钟就卸载，下次请求要重新加载（实测首字从 3s 退化到 20s）
            keep_alive=settings.ollama_keep_alive,
            num_ctx=settings.ollama_num_ctx,
        )

    if provider == "deepseek":
        if not settings.deepseek_api_key:
            raise ValueError(
                "LLM_PROVIDER=deepseek 但没有配置 DEEPSEEK_API_KEY，请先在 .env 中填写"
            )
        return ChatOpenAI(
            model=settings.deepseek_model,
            base_url=settings.deepseek_base_url,
            api_key=settings.deepseek_api_key,
            temperature=temperature,
        )

    raise ValueError(f"不支持的 LLM_PROVIDER：{provider}（只支持 ollama / deepseek）")


class OllamaEmbedder:
    """直连 Ollama /api/embed 的向量器，接口与 LangChain 的 Embeddings 一致。

    两个坑在这里一并处理：
      1. keep_alive 必须显式下发，否则模型会被卸载，每次检索多花 2.2 秒；
      2. bge-m3 对个别 token 会返回 500 NaN（实测 `sequence.` 触发），失败时逐词缩短重试。
    """

    def __init__(self, model: str, base_url: str, keep_alive: str = "30m",
                 num_gpu: int = 0, timeout: int = 120):
        self.model = model
        self.base_url = base_url.rstrip("/")
        self.keep_alive = keep_alive
        self.num_gpu = num_gpu
        self.timeout = timeout

    def _request(self, inputs: list[str]) -> list[list[float]]:
        payload = {
            "model": self.model,
            "input": inputs,
            "keep_alive": self.keep_alive,
            "options": {"num_gpu": self.num_gpu},
        }
        req = urllib.request.Request(
            f"{self.base_url}/api/embed",
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                return json.loads(resp.read())["embeddings"]
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", "replace")[:200]
            raise RuntimeError(f"Ollama 嵌入失败 {exc.code}：{detail}") from exc

    def _embed_one(self, text: str) -> list[float]:
        """单条嵌入；NaN/500 时从尾部逐词缩短重试（最多砍 1/3 词）。"""
        words = text.split()
        last_exc: Exception | None = None
        for cut in range(max(len(words) // 3, 1) + 1):
            frag = text if cut == 0 else " ".join(words[: len(words) - cut]).strip()
            if not frag:
                break
            try:
                return self._request([frag])[0]
            except Exception as exc:  # noqa: BLE001 - 逐个降级尝试
                last_exc = exc
        raise last_exc if last_exc else ValueError("空文本无法嵌入")

    def embed_query(self, text: str) -> list[float]:
        return self._embed_one(text)

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        try:
            return self._request(list(texts))
        except Exception:  # noqa: BLE001 - 一批里有坏样本时退化为逐条
            return [self._embed_one(t) for t in texts]


def get_embedder() -> OllamaEmbedder:
    """向量模型统一走 Ollama 的 bge-m3（计划书 v1.3 修订记录）。

    embedding 不随 provider 切换：DeepSeek 目前没有公开的 embedding 接口，
    而向量库里的 8,895 条数据就是用 bge-m3 生成的，换模型必须重建索引。
    """
    return OllamaEmbedder(
        model=settings.ollama_embed_model,
        base_url=settings.ollama_base_url,
        keep_alive=settings.ollama_keep_alive,
        num_gpu=settings.ollama_embed_num_gpu,
    )
