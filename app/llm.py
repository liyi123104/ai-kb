"""模型抽象层（计划书 2.1 / T2.2）：用环境变量切换 Ollama 与 DeepSeek，业务代码不硬编码模型。

为什么要有这一层：
  开发期用本地 Ollama 免费、不占网；演示期一行配置切到 DeepSeek 云端效果好。
  把差异收敛在一个文件里，rag.py / main.py 不关心背后是谁。

约定：
  - LLM_PROVIDER=ollama   → ChatOllama(OLLAMA_MODEL)
  - LLM_PROVIDER=deepseek → ChatOpenAI(DEEPSEEK_MODEL, base_url=api.deepseek.com)
  - 模型名、地址、密钥全部来自 .env（config.settings），本文件不写死任何模型名。
"""
from __future__ import annotations

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_ollama import ChatOllama, OllamaEmbeddings
from langchain_openai import ChatOpenAI

from app.config import settings


def get_llm(temperature: float = 0.0) -> BaseChatModel:
    """按配置返回聊天模型实例。provider 不认识时抛 ValueError，不静默兜底。"""
    provider = settings.llm_provider.lower()

    if provider == "ollama":
        return ChatOllama(
            model=settings.ollama_model,
            base_url=settings.ollama_base_url,
            temperature=temperature,
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


class SafeOllamaEmbeddings(OllamaEmbeddings):
    """给 Ollama 的 bge-m3 加一层兜底。

    实测问题：某些输入会让 Ollama 返回 500 `failed to encode response: json:
    unsupported value: NaN`。同一个句子，前 12 个词可以嵌入，加上第 13 个词
    （如 `sequence.`）就失败 —— 是模型/tokenizer 层的个别坏 token，不是长度限制。
    如果不兜底，用户问一句恰好含坏 token 的话，整次检索就直接 500。

    策略：整体失败时，逐个样本重试；单个样本仍失败则从尾部逐词缩短，最多砍掉 1/3
    的词。检索查询少一两个尾词几乎不影响语义，但能保证服务不整体失败。
    """

    def _embed_single(self, text: str, as_query: bool) -> list[float]:
        words = text.split()
        last_exc: Exception | None = None
        max_cut = max(len(words) // 3, 1)
        for cut in range(max_cut + 1):
            frag = text if cut == 0 else " ".join(words[: len(words) - cut]).strip()
            if not frag:
                break
            try:
                if as_query:
                    return super().embed_query(frag)
                return super().embed_documents([frag])[0]
            except Exception as exc:  # noqa: BLE001 - 逐个降级尝试
                last_exc = exc
        if last_exc:
            raise last_exc
        raise ValueError("空文本无法嵌入")

    def embed_query(self, text: str) -> list[float]:
        try:
            return super().embed_query(text)
        except Exception:  # noqa: BLE001
            return self._embed_single(text, as_query=True)

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        try:
            return super().embed_documents(texts)
        except Exception:  # noqa: BLE001 - 一批里可能只有个别样本是坏的
            return [self._embed_single(t, as_query=False) for t in texts]


def get_embedder() -> OllamaEmbeddings:
    """向量模型统一走 Ollama 的 bge-m3（计划书 v1.3 修订记录）。

    embedding 不随 provider 切换：DeepSeek 目前没有公开的 embedding 接口，
    而向量库里的 8895 条数据就是用 bge-m3 生成的，换模型必须重建索引。
    这里返回带兜底的子类，避免个别坏 token 让整次检索失败。
    """
    return SafeOllamaEmbeddings(
        model=settings.ollama_embed_model,
        base_url=settings.ollama_base_url,
    )
