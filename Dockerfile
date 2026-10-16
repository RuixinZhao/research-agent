# syntax=docker/dockerfile:1
FROM agenthack/base:1.1.1

LABEL maintainer="ResearchAgentTeam"
LABEL version="1.0.0"

USER root

# 设置工作目录
WORKDIR /app

# 安装仅需增补的轻量级纯净依赖（严格禁止安装重型 PyTorch/Transformers）
COPY requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r /app/requirements.txt

# 复制工程源码
COPY app /app/app
COPY server.py /app/server.py

# 保证非 root 用户 agent 拥有 /app 的完整操作权限
RUN chown -R agent:agent /app

# 切换回官方要求的受限非 root 账号
USER agent

# 暴露平台通信端口
EXPOSE 8080

# 覆盖官方报错 CMD，启动生产级 Uvicorn 服务
CMD ["uvicorn", "server:app", "--host", "0.0.0.0", "--port", "8080", "--workers", "1", "--access-log"]
