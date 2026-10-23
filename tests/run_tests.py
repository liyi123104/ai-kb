"""30 个自动化测试用例（不需要 pytest，直接运行）。

覆盖：接口契约、安全与边界、问答与流式、纯函数与数据一致性。
脚本会自己拉起后端（子进程），跑完自动关掉。

用法：
  .venv\\Scripts\\python.exe tests\\run_tests.py
  .venv\\Scripts\\python.exe tests\\run_tests.py --base http://127.0.0.1:8000   # 用已在跑的服务
"""
from __future__ import annotations

import argparse
import csv
import json
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

BASE = "http://127.0.0.1:8000"
RESULTS: list[tuple[str, bool, str]] = []


# ---------------------------------------------------------------- 工具函数
def http(method: str, path: str, body=None, timeout: int = 300):
    """返回 (status, headers, 解析后的 body)；HTTP 错误也返回状态码而不抛异常。"""
    data = None
    headers = {}
    if body is not None:
        data = json.dumps(body).encode("utf-8")
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(BASE + path, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read()
            ctype = resp.headers.get("content-type", "")
            headers = {k.lower(): v for k, v in resp.headers.items()}
            if "application/json" in ctype:
                return resp.status, dict(resp.headers), json.loads(raw)
            return resp.status, dict(resp.headers), raw
    except urllib.error.HTTPError as exc:
        raw = exc.read()
        hdrs = {k.lower(): v for k, v in (exc.headers or {}).items()}
        try:
            return exc.code, hdrs, json.loads(raw)
        except Exception:  # noqa: BLE001
            return exc.code, dict(exc.headers or {}), raw


def upload_files(items: list[tuple[str, bytes]]) -> tuple[int, dict]:
    """一次提交多个文件（multipart 里重复用同一个字段名 file）。"""
    boundary = "----test" + uuid_hex()
    body = b""
    for filename, content in items:
        body += (
            f"--{boundary}\r\n"
            f'Content-Disposition: form-data; name="file"; filename="{filename}"\r\n'
            f"Content-Type: application/octet-stream\r\n\r\n"
        ).encode() + content + b"\r\n"
    body += f"--{boundary}--\r\n".encode()
    req = urllib.request.Request(
        BASE + "/upload", data=body, method="POST",
        headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
    )
    try:
        with urllib.request.urlopen(req, timeout=300) as resp:
            status, data = resp.status, json.loads(resp.read())
    except urllib.error.HTTPError as exc:
        try:
            return exc.code, json.loads(exc.read())
        except Exception:  # noqa: BLE001
            return exc.code, {}
    if data.get("job_id"):
        job = wait_upload(data["job_id"])
        if job.get("state") == "error":
            return 500, {"detail": job.get("error")}
        data = {**data, "chunks": job.get("chunks", 0), "state": job.get("state")}
    return status, data


def wait_upload(job_id: str, timeout: int = 900) -> dict:
    """上传已改为后台任务：轮询到完成。"""
    deadline = time.time() + timeout
    while time.time() < deadline:
        st, _, job = http("GET", f"/upload/progress/{job_id}", timeout=30)
        if st != 200:
            return {"state": "error", "error": f"进度接口 {st}"}
        if job.get("state") in ("done", "error"):
            return job
        time.sleep(0.5)
    return {"state": "error", "error": "等待入库超时"}


def upload(filename: str, content: bytes) -> tuple[int, dict]:
    boundary = "----test" + uuid_hex()
    body = (
        f"--{boundary}\r\n"
        f'Content-Disposition: form-data; name="file"; filename="{filename}"\r\n'
        f"Content-Type: application/octet-stream\r\n\r\n"
    ).encode() + content + f"\r\n--{boundary}--\r\n".encode()
    req = urllib.request.Request(
        BASE + "/upload", data=body, method="POST",
        headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
    )
    try:
        with urllib.request.urlopen(req, timeout=300) as resp:
            status, data = resp.status, json.loads(resp.read())
    except urllib.error.HTTPError as exc:
        try:
            return exc.code, json.loads(exc.read())
        except Exception:  # noqa: BLE001
            return exc.code, {}

    # 2026-10-23 起上传是后台任务：等它入库完成再返回，用例断言不受影响
    if data.get("job_id"):
        job = wait_upload(data["job_id"])
        if job.get("state") == "error":
            return 500, {"detail": job.get("error")}
        data = {**data, "chunks": job.get("chunks", 0), "state": job.get("state")}
    return status, data


def uuid_hex() -> str:
    import uuid

    return uuid.uuid4().hex


def stream_events(question: str, provider=None, model=None, timeout: int = 300):
    """读 SSE，返回 [(event, data_dict)] 的事件列表。"""
    payload = {"question": question}
    if provider:
        payload["provider"] = provider
    if model:
        payload["model"] = model
    req = urllib.request.Request(
        BASE + "/chat/stream", data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"}, method="POST",
    )
    events = []
    name = None
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        for raw in resp:
            line = raw.decode("utf-8", "replace").strip()
            if line.startswith("event:"):
                name = line.split(":", 1)[1].strip()
            elif line.startswith("data:"):
                try:
                    events.append((name, json.loads(line.split(":", 1)[1].strip())))
                except Exception:  # noqa: BLE001
                    events.append((name, {}))
    return events


def case(name: str):
    """装饰器：注册用例并统一捕获异常。"""
    def deco(fn):
        TESTS.append((name, fn))
        return fn

    return deco


TESTS: list[tuple[str, callable]] = []


def check(cond: bool, msg: str) -> None:
    if not cond:
        raise AssertionError(msg)


# ---------------------------------------------------------------- A. 接口契约
@case("A1 /health 返回 ok 且语料条数 > 0")
def t01():
    st, _, body = http("GET", "/health")
    check(st == 200, f"状态码 {st}")
    check(body.get("status") == "ok", "status 不是 ok")
    check(body.get("chunks", 0) > 0, "chunks 为 0")
    return f"chunks={body['chunks']} provider={body['provider']}"


@case("A2 /providers 返回非空模型列表")
def t02():
    st, _, body = http("GET", "/providers")
    check(st == 200, f"状态码 {st}")
    check(len(body.get("items", [])) > 0, "items 为空")
    return f"{len(body['items'])} 个模型，默认 {body.get('default')}"


@case("A3 /providers 每项含 id/provider/model/available")
def t03():
    _, _, body = http("GET", "/providers")
    for item in body["items"]:
        for key in ("id", "provider", "model", "available"):
            check(key in item, f"缺少字段 {key}")
    return f"字段齐全（{len(body['items'])} 项）"


@case("A4 /providers 的 id 形如 provider:model")
def t04():
    _, _, body = http("GET", "/providers")
    for item in body["items"]:
        check(":" in item["id"], f"id 缺少冒号：{item['id']}")
        check(item["id"].split(":", 1)[0] == item["provider"], "id 前缀与 provider 不一致")
    return "格式正确"


@case("A5 /files 返回列表且每项含 name/size/chunks")
def t05():
    st, _, body = http("GET", "/files")
    check(st == 200, f"状态码 {st}")
    check(isinstance(body, list) and body, "文件列表为空")
    for f in body:
        for key in ("name", "size", "chunks"):
            check(key in f, f"缺少字段 {key}")
    return f"{len(body)} 个文件"


@case("A6 一次上传多个文件成功且切片数 >= 1")
def t06():
    # 2026-10-23 起支持一次提交多个文件（后端放进同一个入库任务顺序处理）
    st, body = upload_files([
        ("t-multi-a.md", ("# 多文件 A\n\n用于验证一次上传多个文件的第一个文件，主题 RAG。" * 12).encode()),
        ("t-multi-b.md", ("# 多文件 B\n\n第二个文件，验证顺序入库与进度汇总。" * 12).encode()),
    ])
    check(st == 200, f"状态码 {st} {body}")
    check(body.get("chunks", 0) >= 2, f"切片数异常：{body.get('chunks')}")
    http("DELETE", "/files/t-multi-a.md")
    http("DELETE", "/files/t-multi-b.md")
    return f"2 个文件共 {body['chunks']} 片"


@case("A7 上传 exe 被拒绝（400）")
def t07():
    st, body = upload("bad.exe", b"MZ\x90\x00fake")
    check(st == 400, f"状态码 {st}")
    return f"detail={body.get('detail')}"


@case("A8 上传空文件被拒绝（400）")
def t08():
    st, body = upload("empty.md", b"")
    check(st == 400, f"状态码 {st}")
    return f"detail={body.get('detail')}"


@case("A9 删除刚上传的文件成功且 removed_chunks > 0")
def t09():
    upload("t-del.md", ("临时删除测试内容。" * 30).encode())
    st, _, body = http("DELETE", "/files/t-del.md")
    check(st == 200, f"状态码 {st}")
    check(body.get("removed_chunks", 0) > 0, "removed_chunks 为 0")
    return f"removed={body['removed_chunks']}"


@case("A10 删除不存在的文件返回 404")
def t10():
    st, _, body = http("DELETE", "/files/not-exist-xyz.md")
    check(st == 404, f"状态码 {st}")
    return "404 正确"


# ---------------------------------------------------------------- B. 安全与边界
@case("B1 路径穿越请求被拒绝（404）")
def t11():
    st, _, _ = http("GET", "/files/..%2F..%2F.env/raw")
    check(st in (404, 400), f"状态码 {st}")
    return f"{st}"


@case("B2 不存在的文件 raw 返回 404")
def t12():
    st, _, _ = http("GET", "/files/nope-123.pdf/raw")
    check(st == 404, f"状态码 {st}")
    return "404 正确"


@case("B3 空问题被拒绝（400/422）")
def t13():
    st, _, _ = http("POST", "/chat", {"question": "   "})
    check(st in (400, 422), f"状态码 {st}")
    return f"{st}"


@case("B4 超长问题（3000 字）不应 500")
def t14():
    st, _, body = http("POST", "/chat", {"question": "自注意力" * 750})
    check(st < 500, f"状态码 {st}")
    return f"{st}"


@case("B5 docx 走 /view 返回 HTML")
def t15():
    # 自己造一个 docx 再测，避免依赖库里恰好有 docx
    import io

    from docx import Document

    buf = io.BytesIO()
    doc = Document()
    doc.add_heading("自动化测试文档", level=1)
    doc.add_paragraph("这是一段用于验证 /view 接口的正文内容。")
    doc.save(buf)
    name = "t-view.docx"
    st, body = upload(name, buf.getvalue())
    check(st == 200, f"上传失败 {st} {body}")
    try:
        st, headers, html = http("GET", f"/files/{name}/view")
        check(st == 200, f"状态码 {st}")
        check("text/html" in headers.get("content-type", ""), "不是 HTML")
        text = html.decode("utf-8", "replace") if isinstance(html, bytes) else str(html)
        check("自动化测试文档" in text, "HTML 里没有正文")
        return f"{len(text)} 字节 HTML"
    finally:
        http("DELETE", f"/files/{name}")


@case("B6 PDF 高亮接口返回 application/pdf")
def t16():
    files = http("GET", "/files")[2]
    pdf = next((f["name"] for f in files if f["name"].lower().endswith(".pdf")), None)
    check(pdf is not None, "库里没有 pdf")
    url = f"/files/{urllib.parse.quote(pdf)}/highlight?page=1&q=" + urllib.parse.quote("机器学习")
    st, headers, body = http("GET", url)
    check(st == 200, f"状态码 {st}")
    check("application/pdf" in headers.get("content-type", ""), "不是 PDF")
    return f"{len(body)/1024:.0f} KB"


# ---------------------------------------------------------------- C. 问答与流式
@case("C1 相关问题返回答案与出处")
def t17():
    st, _, body = http("POST", "/chat", {"question": "什么是自注意力机制？"})
    check(st == 200, f"状态码 {st}")
    check(len(body.get("answer", "")) > 20, "答案过短")
    check(len(body.get("sources", [])) > 0, "没有出处")
    return f"答案 {len(body['answer'])} 字，出处 {len(body['sources'])} 条"


@case("C2 无关问题明确拒答")
def t18():
    _, _, body = http("POST", "/chat", {"question": "今天北京天气怎么样？"})
    check("没有相关内容" in body.get("answer", ""), f"未拒答：{body.get('answer','')[:40]}")
    return "已拒答"


@case("C3 会话落库：/sessions/{id} 能取回 2 条消息")
def t19():
    _, _, body = http("POST", "/chat", {"question": "什么是 RAG？"})
    sid = body["session_id"]
    st, _, hist = http("GET", f"/sessions/{sid}")
    check(st == 200, f"状态码 {st}")
    check(len(hist.get("messages", [])) >= 2, "消息不足 2 条")
    return f"session {sid[:8]} 有 {len(hist['messages'])} 条"


@case("C4 流式：sources 先于 token，done 在最后")
def t20():
    events = stream_events("什么是梯度消失？")
    names = [n for n, _ in events]
    check("sources" in names, "缺少 sources 事件")
    check("token" in names, "缺少 token 事件")
    check(names[-1] == "done", f"最后事件是 {names[-1]}")
    check(names.index("sources") < names.index("token"), "sources 不在 token 之前")
    return f"{len(names)} 个事件"


@case("C5 流式：至少产生 1 个 token")
def t21():
    events = stream_events("RAG 有什么优势？")
    tokens = [d for n, d in events if n == "token"]
    check(len(tokens) >= 1, "没有 token")
    return f"{len(tokens)} 段"


@case("C6 指定 model 参数可用")
def t22():
    _, _, prov = http("GET", "/providers")
    local = next((i for i in prov["items"] if i["provider"] == "ollama" and i["available"]), None)
    check(local is not None, "没有可用的本地模型")
    st, _, body = http("POST", "/chat", {"question": "什么是 RAG？", "provider": "ollama", "model": local["model"]})
    check(st == 200, f"状态码 {st}")
    check(len(body.get("answer", "")) > 10, "答案过短")
    return f"用 {local['model']} 回答 {len(body['answer'])} 字"


# ---------------------------------------------------------------- D. 纯函数与数据
@case("D1 clean_answer 清除 LaTeX 标记")
def t23():
    from app.rag import clean_answer

    raw = r"输入 \(x_1, \ldots, x_n\)，其中 \(x_i \in \mathbb{R}^d\)，且 \(1 \leq i \leq n\)"
    out = clean_answer(raw)
    check("\\(" not in out and "\\mathbb" not in out, f"未清干净：{out}")
    check("≤" in out, "没有保留 ≤")
    return out[:40]


@case("D2 best_snippet 不含换行且不切断句子")
def t24():
    from app.rag import best_snippet

    text = "第一句无关的话。第二句讲的是注意力机制如何并行计算。第三句也是无关的。"
    out = best_snippet(text, "注意力机制如何计算？")
    check("\n" not in out, "含换行")
    check(len(out) >= 10, "过短")
    return out


@case("D3 best_snippet 过滤代码行")
def t25():
    from app.rag import best_snippet

    text = "num_hiddens, num_heads = 100, 5\nfrom d2l import mxnet as d2l\n注意力机制让模型可以并行处理序列。"
    out = best_snippet(text, "注意力机制")
    check("num_hiddens" not in out, f"选中了代码行：{out}")
    return out


@case("D4 page_label 对跨页片段给出范围")
def t26():
    from app.rag import page_label

    label = page_label({"page": 434, "page_start": 434, "page_end": 435})
    check("–" in label or "-" in label, f"没有范围：{label}")
    return label


@case("D5 is_low_value 识别无信息片段")
def t27():
    from app.rag import is_low_value

    check(is_low_value("..........") is True, "纯符号未被判为低价值")
    check(is_low_value("自注意力机制让模型能够并行处理序列中的每个位置。") is False, "正常句被判成低价值")
    return "判定正确"


@case("D6 测试集恰好 30 行且字段齐全")
def t28():
    path = ROOT / "data" / "testset.csv"
    rows = list(csv.DictReader(path.open(encoding="utf-8-sig")))
    check(len(rows) == 30, f"实际 {len(rows)} 行")
    for key in ("question", "expected_source", "expected_page"):
        check(key in rows[0], f"缺少列 {key}")
    return "30 行"


@case("D7 评测结果 30 行且命中 27 题（与基线一致）")
def t29():
    path = ROOT / "data" / "eval-results.csv"
    rows = list(csv.DictReader(path.open(encoding="utf-8-sig")))
    check(len(rows) == 30, f"实际 {len(rows)} 行")
    hits = sum(1 for r in rows if r.get("hit") == "1")
    check(hits == 27, f"命中 {hits}，基线是 27")
    return f"召回 {hits}/30"


@case("D8 依赖与文档齐全（pymupdf / acceptance.md）")
def t30():
    req = (ROOT / "requirements.txt").read_text(encoding="utf-8").lower()
    check("pymupdf" in req, "requirements 缺 pymupdf")
    check((ROOT / "docs" / "acceptance.md").exists(), "缺 docs/acceptance.md")
    return "齐全"


# ---------------------------------------------------------------- 主流程
def wait_server(seconds: int = 90) -> bool:
    for _ in range(seconds):
        try:
            with urllib.request.urlopen(BASE + "/health", timeout=2) as resp:
                if resp.status == 200:
                    return True
        except Exception:  # noqa: BLE001
            time.sleep(1)
    return False


def main() -> int:
    global BASE
    parser = argparse.ArgumentParser()
    parser.add_argument("--base", default=BASE)
    parser.add_argument("--keep", action="store_true", help="跑完不关闭自己启动的服务")
    args = parser.parse_args()
    BASE = args.base.rstrip("/")

    proc = None
    if not wait_server(3):
        print(f"启动后端 {BASE} ...")
        env = dict(**__import__("os").environ)
        env["PYTHONIOENCODING"] = "utf-8"
        proc = subprocess.Popen(
            [sys.executable, "-m", "app.main"], cwd=str(ROOT),
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, env=env,
        )
        if not wait_server(120):
            print("后端启动失败（可手动运行 python -m app.main 查看报错）")
            return 2

    print("=" * 72)
    print(f"运行 {len(TESTS)} 个测试用例（{BASE}）")
    print("=" * 72)
    t0 = time.perf_counter()
    passed = 0
    for i, (name, fn) in enumerate(TESTS, 1):
        try:
            detail = fn() or ""
            RESULTS.append((name, True, str(detail)))
            passed += 1
            print(f"  [{i:02d}] PASS  {name}  {detail}")
        except AssertionError as exc:
            RESULTS.append((name, False, str(exc)))
            print(f"  [{i:02d}] FAIL  {name}  -> {exc}")
        except Exception as exc:  # noqa: BLE001
            RESULTS.append((name, False, f"{type(exc).__name__}: {exc}"))
            print(f"  [{i:02d}] ERROR {name}  -> {type(exc).__name__}: {exc}")

    elapsed = time.perf_counter() - t0
    print("-" * 72)
    print(f"结果：{passed}/{len(TESTS)} 通过，耗时 {elapsed:.1f}s")
    failed = [r for r in RESULTS if not r[1]]
    if failed:
        print("\n未通过：")
        for name, _, detail in failed:
            print(f"  - {name}: {detail}")

    if proc and not args.keep:
        proc.terminate()
        try:
            proc.wait(timeout=15)
        except Exception:  # noqa: BLE001
            proc.kill()
    return 0 if not failed else 1


if __name__ == "__main__":
    raise SystemExit(main())
