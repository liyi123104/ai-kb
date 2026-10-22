# 后端镜像：FastAPI + RAG（计划书 T5.1）
# 说明：
#   - 用 3.12-slim，与本地 .venv 的 Python 版本一致
#   - 依赖来自 requirements-docker.txt：由 requirements.txt 去掉 torch/scipy/scikit-learn
#     （代码里没有任何 import，embedding 走 Ollama，带上它们只会让镜像多出数 GB）
#   - Ollama 不在容器里：模型跑在宿主机上，容器通过 OLLAMA_BASE_URL 访问
# 基础镜像可替换：国内直连 Docker Hub 会超时，可用下面这种镜像站地址
#   docker compose build --build-arg BASE_IMAGE=docker.m.daocloud.io/library/python:3.12-slim
ARG BASE_IMAGE=python:3.12-slim
FROM ${BASE_IMAGE}

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    TZ=Asia/Shanghai

# 国内构建时走镜像源；需要走官方源可 --build-arg PIP_INDEX_URL=https://pypi.org/simple/
ARG PIP_INDEX_URL=https://mirrors.aliyun.com/pypi/simple/
ARG PIP_TRUSTED_HOST=mirrors.aliyun.com

WORKDIR /app

# 先复制依赖清单，利用 Docker 层缓存：改代码不必重装依赖
COPY requirements-docker.txt .
# 挂载 pip 缓存：构建失败重试时不用从头下载（国内网络容易读超时）
RUN --mount=type=cache,target=/root/.cache/pip \
    pip install -i "$PIP_INDEX_URL" --trusted-host "$PIP_TRUSTED_HOST" \
        --timeout 120 --retries 10 -r requirements-docker.txt

COPY app ./app
COPY scripts ./scripts
COPY .env.example ./.env.example

# 数据目录挂载点：向量库、SQLite、上传文件、临时目录
RUN mkdir -p /app/data/chroma /app/data/uploads /app/data/tmp

EXPOSE 8000

# 容器内以 0.0.0.0 监听，宿主机才能访问
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
