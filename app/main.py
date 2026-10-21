"""FastAPI 入口（计划书 6.1 / T2.1、T2.3-T2.6）。

职责：HTTP 层只做参数校验与转发；RAG 逻辑在 app/rag.py，模型选择在 app/llm.py，
对话落库在 app/db.py。每个模块只做一件事（计划书 6.3 单一职责）。

启动：
    .\\.venv\\Scripts\\python.exe -m app.main
    或 uvicorn app.main:app --reload

接口（计划书 6.2）：
    GET    /health                  健康检查
    POST   /upload                  上传文件 → 解析/切片/嵌入/入库
    POST   /chat                    问答（非流式，落库）
    POST   /chat/stream             问答（SSE 流式）
    GET    /files                   已上传文件列表
    DELETE /files/{name}            删除文件及其向量
    GET    /sessions                会话列表（T2.6 补充，用于取回历史）
    GET    /sessions/{id}           按会话 ID 取回历史消息
"""
from __future__ import annotations

import json
from pathlib import Path

from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from app import db, rag
from app.config import settings

app = FastAPI(title="AI 学习资料知识库", version="0.1.0")

# 建表放在模块导入时执行（幂等）：这样无论是 uvicorn 启动、`python -m app.main`，
# 还是测试里用 TestClient(app) 直接导入，数据库结构都已经就绪。
db.init_db()

ALLOWED_SUFFIXES = rag.SUPPORTED_SUFFIXES
MAX_UPLOAD_MB = 100


@app.on_event("startup")
def warm_up_models() -> None:
    """启动后预热模型，并周期性保活（后台线程，不阻塞启动）。

    为什么需要：
      1) Ollama 首次加载 7B 模型要十几秒，不预热的话第一个用户请求的首字延迟会从
         3 秒退化到 10–20 秒，直接违反「首字 ≤3 秒」的目标；
      2) 实测 keep_alive 对 embeddings 接口不生效，bge-m3 闲置几十秒就被卸载，每次
         检索都要重新加载 2.7 秒 —— 所以这里每 4 分钟轻点一次，把两个模型摁在显存里。
    预热/保活失败不致命（比如 Ollama 没启动），只打日志，服务照常起来。
    """
    import threading
    import time

    def _loop() -> None:
        import json as _json
        import urllib.request

        from app.config import settings as _s
        from app.llm import get_embedder

        embedder = get_embedder()

        def _keep_chat_alive() -> None:
            # 关键：用 num_predict=0 的 generate 调用把模型摁在显存里，但不产生任何 token。
            # 之前用 llm.invoke("ping") 会覆盖 Ollama 的 prompt 缓存，导致下一次真实请求
            # 要重新做 prompt 求值（实测首 token 从 0.5s 掉到 3.5s）。
            payload = {"model": _s.ollama_model, "prompt": "",
                       "keep_alive": _s.ollama_keep_alive,
                       "options": {"num_predict": 0}}
            req = urllib.request.Request(
                _s.ollama_base_url.rstrip("/") + "/api/generate",
                data=_json.dumps(payload).encode(),
                headers={"Content-Type": "application/json"})
            urllib.request.urlopen(req, timeout=120).read()

        keep_chat = _s.llm_provider.lower() == "ollama"
        while True:
            try:
                embedder.embed_query("保活")
                # 只有本地生成时才需要保活聊天模型；云端生成时保活它会白占 4.4GB 显存，
                # 把向量模型挤出 GPU（实测导致每次检索多花 2 秒）。
                if keep_chat:
                    _keep_chat_alive()
                print(f"[warmup] 保活完成（chat={'on' if keep_chat else 'off'}）", flush=True)
            except Exception as exc:  # noqa: BLE001 - 预热失败不应影响服务
                print(f"[warmup] 预热跳过：{exc}", flush=True)
            time.sleep(240)  # 4 分钟一次，短于 Ollama 默认 5 分钟卸载阈值

    threading.Thread(target=_loop, daemon=True).start()


class ChatRequest(BaseModel):
    question: str = Field(..., min_length=1, description="用户问题")
    session_id: str | None = Field(default=None, description="会话 ID，留空则新建")
    history: list[dict] | None = Field(default=None, description="历史消息（可选，前端回传）")


@app.get("/health")
def health() -> dict:
    """健康检查：同时报告向量库条数与当前模型配置，方便排查。"""
    try:
        count = rag.collection_count()
    except Exception as exc:  # noqa: BLE001 - 向量库打不开时也要能返回状态
        return {"status": "degraded", "error": str(exc)}
    return {"status": "ok", "chunks": count, "provider": settings.llm_provider,
            "chat_model": settings.ollama_model if settings.llm_provider == "ollama"
            else settings.deepseek_model}


@app.post("/upload")
async def upload(file: UploadFile = File(...)) -> dict:
    """接收文件 → 解析切片嵌入入库 → 返回文件名与切片数。"""
    filename = Path(file.filename or "").name  # 防目录穿越
    suffix = Path(filename).suffix.lower()
    if suffix not in ALLOWED_SUFFIXES:
        raise HTTPException(status_code=400,
                            detail=f"不支持的文件类型：{suffix or '无扩展名'}（支持 pdf/docx/md/txt）")

    target = settings.uploads_dir / filename
    size = 0
    try:
        with target.open("wb") as out:
            while chunk := await file.read(1024 * 1024):
                size += len(chunk)
                if size > MAX_UPLOAD_MB * 1024 * 1024:
                    out.close()
                    target.unlink(missing_ok=True)
                    raise HTTPException(status_code=413, detail=f"文件超过 {MAX_UPLOAD_MB}MB")
                out.write(chunk)
    except HTTPException:
        raise
    except OSError as exc:
        raise HTTPException(status_code=500, detail=f"保存文件失败：{exc}") from exc

    try:
        result = rag.ingest_file(target)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=f"入库失败：{exc}") from exc

    return {"filename": result["filename"], "chunks": result["chunks"], "size": result["size"]}


@app.post("/chat")
def chat(req: ChatRequest) -> dict:
    """问答（非流式）：返回答案 + 出处，并把这一轮写入 SQLite。"""
    if not req.question.strip():
        raise HTTPException(status_code=400, detail="问题不能为空")
    try:
        result = rag.answer(req.question)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=f"生成失败：{exc}") from exc

    session_id = db.save_turn(req.session_id or "", req.question, result["answer"],
                              result["sources"], rag.now_iso())
    return {"answer": result["answer"], "sources": result["sources"], "session_id": session_id}


@app.post("/chat/stream")
def chat_stream(req: ChatRequest) -> StreamingResponse:
    """问答（SSE 流式）：先推出处，再逐块推答案，最后推结束标记；整轮落库。"""
    if not req.question.strip():
        raise HTTPException(status_code=400, detail="问题不能为空")

    def event_stream():
        collected: list[str] = []
        sources: list[dict] = []
        try:
            import time as _t
            _t0 = _t.perf_counter()
            hits = rag.retrieve(req.question)
            print(f"[chat] retrieve {_t.perf_counter() - _t0:.2f}s, hits={len(hits)}", flush=True)
            sources = rag.make_sources(hits)
            yield f"event: sources\ndata: {json.dumps(sources, ensure_ascii=False)}\n\n"

            best_score = max((1 - float(d) for _, d in hits), default=0.0)
            if not hits or best_score < settings.score_gate:
                collected.append(rag.NO_ANSWER)
                yield f"event: token\ndata: {json.dumps(rag.NO_ANSWER, ensure_ascii=False)}\n\n"
            else:
                prompt = rag.PROMPT_TEMPLATE.format(context=rag.format_context(hits),
                                                    question=req.question)
                from app.llm import get_llm

                _t1 = _t.perf_counter()
                for piece in get_llm().stream(prompt):
                    text = piece.content if isinstance(piece.content, str) else str(piece.content)
                    if text:
                        if not collected:
                            print(f"[chat] first token {_t.perf_counter() - _t1:.2f}s", flush=True)
                        collected.append(text)
                        yield f"event: token\ndata: {json.dumps(text, ensure_ascii=False)}\n\n"

            session_id = db.save_turn(req.session_id or "", req.question,
                                      "".join(collected), sources, rag.now_iso())
            yield f"event: done\ndata: {json.dumps({'session_id': session_id}, ensure_ascii=False)}\n\n"
        except Exception as exc:  # noqa: BLE001 - 流里出错也要给前端一个可读事件
            yield f"event: error\ndata: {json.dumps(str(exc), ensure_ascii=False)}\n\n"

    return StreamingResponse(event_stream(), media_type="text/event-stream")


@app.get("/files")
def list_files() -> list[dict]:
    """已上传文件列表：文件名、大小、上传时间、切片数。

    语料既可能来自 /upload（在 data/uploads），也可能是 scripts 批量入库的
    materials 目录，因此两处都查；都找不到时 size/uploaded_at 返回 null。
    """
    vs = rag.get_vectorstore()
    data = vs._collection.get(include=["metadatas"])  # noqa: SLF001
    counts: dict[str, int] = {}
    for md in data.get("metadatas", []):
        counts[md["source"]] = counts.get(md["source"], 0) + 1

    root = settings.data_dir.parent
    files = []
    for name, chunks in sorted(counts.items()):
        stored = None
        for candidate in (settings.uploads_dir / name, root / "materials" / name):
            if candidate.exists():
                stored = candidate
                break
        stat = stored.stat() if stored else None
        files.append({
            "name": name,
            "size": stat.st_size if stat else None,
            "uploaded_at": (rag.now_iso() if stat else None),
            "chunks": chunks,
        })
    return files


@app.delete("/files/{name}")
def delete_file(name: str) -> dict:
    """删除文件：向量与磁盘文件一起删。"""
    safe = Path(name).name
    removed = rag.delete_file(safe)
    deleted_file = False
    for candidate in (settings.uploads_dir / safe, settings.data_dir.parent / "materials" / safe):
        if candidate.exists():
            candidate.unlink()
            deleted_file = True
    if removed == 0 and not deleted_file:
        raise HTTPException(status_code=404, detail=f"没有这个文件：{safe}")
    return {"ok": True, "removed_chunks": removed}


@app.get("/sessions")
def sessions() -> list[dict]:
    """会话列表（最近的在前）。"""
    return db.list_sessions()


@app.get("/sessions/{session_id}")
def session_history(session_id: str) -> dict:
    """按会话 ID 取回历史消息（T2.6 验收：可按会话 ID 取回历史）。"""
    messages = db.get_history(session_id)
    if not messages:
        raise HTTPException(status_code=404, detail=f"没有这个会话：{session_id}")
    return {"session_id": session_id, "messages": messages}


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("app.main:app", host=settings.host, port=settings.port, reload=False)
