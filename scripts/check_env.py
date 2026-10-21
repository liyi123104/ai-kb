"""换设备 / 首次启动前的环境自检。

回答"换台电脑能不能直接跑"：本项目连的是本机 Ollama（127.0.0.1:11434），
换个设备只要装好 Ollama 并拉了同名模型就能用；这个脚本把"缺什么、怎么补"直接打出来。

用法：.venv\\Scripts\\python.exe scripts\\check_env.py
"""
from __future__ import annotations

import json
import sys
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app.config import settings  # noqa: E402

OK, WARN, BAD = "  [OK]  ", "  [警告]", "  [缺失]"


def http_json(url: str, timeout: int = 10):
    with urllib.request.urlopen(url, timeout=timeout) as resp:
        return json.loads(resp.read())


def check_python() -> bool:
    print(f"{OK}Python {sys.version.split()[0]}  ({sys.executable})")
    return True


def check_ollama() -> tuple[bool, list[str]]:
    """返回（Ollama 是否可用, 本机已有模型名列表）。"""
    try:
        ver = http_json(f"{settings.ollama_base_url}/api/version")["version"]
        tags = http_json(f"{settings.ollama_base_url}/api/tags")["models"]
        names = [m["name"] for m in tags]
        print(f"{OK}Ollama {ver} 可达：{settings.ollama_base_url}")
        print(f"         本机已有模型：{', '.join(names) if names else '（空）'}")
        return True, names
    except Exception as exc:  # noqa: BLE001
        print(f"{BAD}连不上 Ollama（{settings.ollama_base_url}）：{exc}")
        print("         解决办法：装 Ollama（https://ollama.com/）后启动，再跑本脚本")
        return False, []


def check_models(names: list[str]) -> bool:
    """检查 .env 里指定的生成/向量模型是否在本机。"""
    ok = True
    pairs = [
        ("生成模型", settings.ollama_model),
        ("向量模型", settings.ollama_embed_model),
    ]
    for label, want in pairs:
        # 带 tag 的必须精确匹配（qwen2.5:14b 不能当成 qwen2.5:7b）；
        # 不带 tag 的（如 bge-m3）允许本机任意 tag。
        if ":" in want:
            hit = want in names
        else:
            hit = any(n.split(":")[0] == want for n in names)
        if hit:
            print(f"{OK}{label} {want} 已就位")
        else:
            ok = False
            print(f"{BAD}{label} {want} 不在本机")
            print(f"         解决办法：ollama pull {want}")
    return ok


def check_vectorstore() -> bool:
    """向量库是否已有数据；换设备时如果没有，要么带上完整包，要么重新入库。"""
    db = settings.chroma_dir / "chroma.sqlite3"
    if not db.exists():
        print(f"{WARN}向量库为空（{settings.chroma_dir}）")
        print("         解决办法：拷入 data/chroma（完整包已含），或重新入库：")
        print("           python scripts/04_store.py")
        return False
    try:
        import chromadb

        client = chromadb.PersistentClient(path=str(settings.chroma_dir))
        names = [c.name for c in client.list_collections()]
        if settings.collection not in names:
            print(f"{WARN}向量库里没有集合 {settings.collection}（现有：{names}）")
            return False
        count = client.get_collection(settings.collection).count()
        print(f"{OK}向量库 {settings.collection}：{count} 条")
        return count > 0
    except Exception as exc:  # noqa: BLE001
        print(f"{WARN}向量库读取失败：{exc}")
        return False


def check_materials() -> bool:
    mats = settings.ROOT / "materials" if hasattr(settings, "ROOT") else ROOT / "materials"
    files = sorted(mats.glob("*")) if mats.exists() else []
    files = [f for f in files if f.is_file()]
    if files:
        print(f"{OK}语料目录：{len(files)} 个文件")
        return True
    print(f"{WARN}语料目录为空（{mats}）")
    print("         只影响「重新入库」，不影响已有向量库的问答")
    return False


def check_frontend() -> bool:
    nm = ROOT / "web" / "node_modules"
    if nm.exists():
        print(f"{OK}前端依赖已安装")
        return True
    print(f"{WARN}前端依赖缺失（web/node_modules）")
    print("         解决办法：cd web && npm install --registry=https://registry.npmmirror.com")
    return False


def check_env_file() -> None:
    env = ROOT / ".env"
    if env.exists():
        print(f"{OK}.env 已存在")
    else:
        print(f"{WARN}.env 不存在 —— 复制模板后按需修改：copy .env.example .env")


def main() -> int:
    print("=" * 56)
    print("AI 学习资料知识库 · 环境自检")
    print("=" * 56)
    check_python()
    check_env_file()
    print(f"         当前配置：provider={settings.llm_provider}  "
          f"本地模型={settings.ollama_model}  向量={settings.ollama_embed_model}")

    online, names = check_ollama()
    models_ok = check_models(names) if online else False

    if settings.llm_provider == "deepseek":
        key = settings.deepseek_api_key
        if key and key != "sk-xxxx":
            print(f"{OK}云端 DeepSeek Key 已配置（{settings.deepseek_model}）")
        else:
            print(f"{BAD}provider=deepseek 但没有有效 DEEPSEEK_API_KEY")
            print("         解决办法：在 .env 里填 DEEPSEEK_API_KEY，或把 LLM_PROVIDER 改回 ollama")

    store_ok = check_vectorstore()
    check_materials()
    front_ok = check_frontend()

    print("-" * 56)
    if online and models_ok and store_ok:
        print("结论：可以运行。启动方式：双击 start.bat")
        code = 0
    elif not online:
        print("结论：跑不起来 —— 先装并启动 Ollama")
        code = 2
    elif not models_ok:
        print("结论：模型不全 —— 按上面的 ollama pull 补齐即可")
        code = 3
    else:
        print("结论：可以问答，但向量库为空 —— 需拷入 data/chroma 或重新入库")
        code = 4
    print(f"（前端依赖：{'已装' if front_ok else '缺，需 npm install'}）")
    return code


if __name__ == "__main__":
    raise SystemExit(main())
