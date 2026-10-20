"""T3.1 Streamlit 临时界面：上传资料 + 提问 + 出处展示（调用已完成的 FastAPI 后端）。

这是阶段 A 的临时脚手架，只验证「上传 → 提问 → 看到出处」这条链路；
第 4-5 周会被 Vue3 产品界面替换（计划书第 2 节）。

启动：
    .\\.venv\\Scripts\\python.exe -m streamlit run ui_streamlit.py
"""
import requests
import streamlit as st

API = "http://127.0.0.1:8000"

st.set_page_config(page_title="AI 学习资料知识库", page_icon="📚", layout="wide")
st.title("📚 AI 学习资料知识库（临时界面）")

with st.sidebar:
    st.subheader("上传资料")
    up = st.file_uploader("选择文件", type=["pdf", "docx", "md", "txt"])
    if up and st.button("上传并入库"):
        with st.spinner("解析、切片、嵌入中…（大文件较慢）"):
            try:
                r = requests.post(f"{API}/upload", files={"file": (up.name, up.getvalue())}, timeout=600)
                st.success(f"{r.json()['filename']} 入库 {r.json()['chunks']} 片") if r.ok else st.error(r.text)
            except requests.RequestException as exc:
                st.error(f"后端没启动或连接失败：{exc}")

    st.divider()
    st.subheader("已入库文件")
    try:
        files = requests.get(f"{API}/files", timeout=10).json()
        st.caption(f"共 {len(files)} 个文件")
        for f in files:
            st.write(f"· {f['name']}（{f['chunks']} 片）")
    except requests.RequestException:
        st.warning("读不到文件列表，后端可能没启动")

if "messages" not in st.session_state:
    st.session_state.messages = []

for m in st.session_state.messages:
    with st.chat_message(m["role"]):
        st.markdown(m["content"])
        for s in m.get("sources", []):
            st.caption(f"出处：{s['file']} · PDF p.{s['page_label']} · 相似度 {s['score']}")

question = st.chat_input("问点什么，例如：什么是自注意力机制？")
if question:
    st.session_state.messages.append({"role": "user", "content": question})
    with st.chat_message("user"):
        st.markdown(question)

    with st.chat_message("assistant"):
        with st.spinner("检索并生成中…"):
            try:
                resp = requests.post(f"{API}/chat", json={"question": question}, timeout=300)
                data = resp.json() if resp.ok else {"answer": f"请求失败：{resp.text}", "sources": []}
            except requests.RequestException as exc:
                data = {"answer": f"后端连接失败：{exc}", "sources": []}
        st.markdown(data["answer"])
        for s in data["sources"]:
            st.caption(f"出处：{s['file']} · PDF p.{s['page_label']} · 相似度 {s['score']}")

    st.session_state.messages.append(
        {"role": "assistant", "content": data["answer"], "sources": data["sources"]})
