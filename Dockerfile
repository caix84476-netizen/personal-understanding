# Glama 用它构建并运行 stdio MCP 服务器做安全扫描与可安装性验证。
# 本项目为 Python 3.10+ 纯标准库，无第三方运行依赖。
FROM python:3.13-slim

WORKDIR /app

# 只复制打包所需的文件（scripts/ 即 personal_understanding 包）
COPY pyproject.toml README.md ./
COPY scripts ./scripts

RUN pip install --no-cache-dir .

ENV PYTHONUNBUFFERED=1

# pyproject 里注册的 console 入口：personal-understanding -> personal_understanding.mcp_server:main
ENTRYPOINT ["personal-understanding"]
