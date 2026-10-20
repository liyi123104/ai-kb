# 后端镜像：FastAPI + RAG（计划书 T5.1）
# 说明：
#   - 用 3.12-slim，与本地 .venv 的 Python 版本一致
#   - 依赖全部来自 requirements.txt（精确锁版本，符合计划书 6.3）
#   - Ollama 不在容器里：模型跑在宿主机上，容器通过 OLLAMA_BASE_URL 访问
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    TZ=Asia/Shanghai

WORKDIR /app

# 先复制依赖清单，利用 Docker 层缓存：改代码不必重装依赖
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app ./app
COPY scripts ./scripts
COPY .env.example ./.env.example

# 数据目录挂载点：向量库、SQLite、上传文件、临时目录
RUN mkdir -p /app/data/chroma /app/data/uploads /app/data/tmp

EXPOSE 8000

# 容器内以 0.0.0.0 监听，宿主机才能访问
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
