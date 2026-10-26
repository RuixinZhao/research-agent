FROM agenthack/base:1.1.1

LABEL maintainer="ResearchAgentTeam"
LABEL version="1.3.0"

USER root

# 设置工作目录
WORKDIR /app

# 安装仅需增补的轻量级纯净依赖（严格禁止安装重型 PyTorch/Transformers）
COPY requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r /app/requirements.txt

# 复制工程源码与关键材料
COPY app /app/app
COPY server.py /app/server.py
COPY model_source.py /app/model_source.py
COPY research-experiments-v1 /app/research-experiments-v1
COPY research-experiments-20261020-source-v1-local /app/research-experiments-20261020-source-v1-local

# 预创建各级产物目录并授予 agent 用户完全读写执行权限，严防沙箱写入 PermissionError
RUN mkdir -p /output /app/data /app/data/expert /app/data/figure /app/data/work \
    && chown -R agent:agent /app /output \
    && chmod -R 777 /output /app/data

# 切换回官方要求的受限非 root 账号
USER agent

# 暴露平台通信端口
EXPOSE 8080

# 覆盖官方报错 CMD，启动生产级 Uvicorn 服务
CMD ["uvicorn", "server:app", "--host", "0.0.0.0", "--port", "8080", "--workers", "1", "--access-log"]
