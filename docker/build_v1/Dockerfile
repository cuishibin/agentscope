# ============ 阶段 1：前端构建（builder） ============
FROM node:22-slim AS web-builder

# 构建容器内网络代理（可选）：RUN 指令不走 Docker daemon 的代理设置，
# 需通过 build-arg 单独注入。使用方式：
#   docker compose build --build-arg HTTPS_PROXY=http://host.docker.internal:7890
# 注意地址用 host.docker.internal 而非 127.0.0.1（容器内的 localhost
# 是容器自身）。声明为 ARG 而非 ENV，避免代理配置残留在镜像元数据中；
# pnpm/corepack 会读取标准 http_proxy/https_proxy 环境变量。
ARG HTTP_PROXY
ARG HTTPS_PROXY
ARG NO_PROXY=localhost,127.0.0.1

# 通过 corepack 启用 pnpm（声明要求使用 pnpm）。
# 版本必须固定，保证构建可复现、lockfile 兼容性不漂移。
# 固定为 pnpm 10：pnpm-workspace.yaml 使用了 minimumReleaseAge /
# allowBuilds 等 pnpm 10 语法，用 pnpm 9 会导致字段被忽略、行为
# 与开发者本地不一致（lockfileVersion 9.0 与 pnpm 10 兼容）。
RUN corepack enable && corepack prepare pnpm@10.18.3 --activate

# 构建上下文无 .git（.dockerignore 排除），husky 的 prepare 钩子会失败，禁用之
ENV HUSKY=0

WORKDIR /build
# 先拷依赖清单，利用 Docker layer 缓存加速重建
COPY examples/web_ui/package.json examples/web_ui/pnpm-lock.yaml \
     examples/web_ui/pnpm-workspace.yaml ./
COPY examples/web_ui/frontend/package.json ./frontend/
COPY examples/web_ui/backend/package.json ./backend/
RUN pnpm install --frozen-lockfile

# 拷源码并构建
COPY examples/web_ui/ .
# pnpm build = build:frontend (tsc -b && vite build) + build:backend (tsc)
RUN pnpm build
# 生成 backend 的自包含生产目录：pnpm workspace 下 backend/node_modules
# 内是指向根 node_modules/.pnpm 的符号链接，直接拷贝会得到断链；
# pnpm deploy 会解析链接并只保留生产依赖，产出可独立运行的目录。
# 注意执行顺序：先 build 再 deploy，dist/ 才会被带入 deploy 产物。
# --legacy：pnpm 10 起默认仅支持 "inject-workspace-packages=true" 的
# workspace，本仓库未启用注入模式，需 --legacy 回退到 pnpm 9 的
# deploy 行为（拷贝并解析符号链接、仅保留生产依赖）。
# 实施时验证 /deploy/backend/dist/index.js 存在，缺失则补 cp。
RUN pnpm deploy --legacy --filter=backend --prod /deploy/backend \
    && test -f /deploy/backend/dist/index.js

# ============ 阶段 2：运行时镜像 ============
FROM python:3.11-slim

# Node 22 为运行必需：playwright MCP 经 npx 拉起，web-ui 容器运行 node 进程。
# 优化：直接从官方 node 镜像拷贝二进制，避免 NodeSource apt 源残留，且与
# 构建阶段 Node 版本天然一致（比 apt 安装小且干净）。
COPY --from=node:22-slim /usr/local/bin/node /usr/local/bin/node
COPY --from=node:22-slim /usr/local/lib/node_modules /usr/local/lib/node_modules
# npx/npm 是 node 镜像内的符号链接/入口脚本，需手动补齐到 PATH
RUN ln -s /usr/local/lib/node_modules/npm/bin/npx-cli.js /usr/local/bin/npx \
    && ln -s /usr/local/lib/node_modules/npm/bin/npm-cli.js /usr/local/bin/npm

# uv 安装器：比 pip 快一个量级，无需额外缓存挂载。
# 经 PyPI 安装而非 COPY --from=ghcr.io/astral-sh/uv：ghcr.io 在部分
# 网络环境不可达（IPv6 路由不通），PyPI 可通过 UV_INDEX_URL /
# pip 镜像加速，兼容性更好。
# 版本固定，保证构建可复现。
RUN pip install --no-cache-dir uv==0.9.5

WORKDIR /app
# 源码安装 agentscope（不用 PyPI：PyPI 最新 2.0.10 落后本地 main 分支
# 2.0.12dev，且 extras 结构已分叉，main.py 的 agentscope.app 系列导入
# 在 PyPI 版本上不可用，必须随仓库源码安装）。
# 注意：pyproject 声明 readme = "README.md"、License-File 需要 LICENSE，
# 版本为 dynamic（来自 src/agentscope/_version.py），构建元数据需要这些文件。
COPY pyproject.toml README.md LICENSE ./
COPY src ./src
# main.py 依赖 RedisStorage/QdrantStore/channels 等，均在 extras 中，装 full
RUN uv pip install --system ".[full]" && rm -rf /root/.cache/uv

# 智能体服务后端
COPY examples/agent_service ./agent_service

# 前端生产产物：静态页面 + Express 编译产物
COPY --from=web-builder /build/frontend/dist ./web_ui/frontend/dist
# backend 自包含生产目录（pnpm deploy 产物：dist + 真实 node_modules）
COPY --from=web-builder /deploy/backend ./web_ui/backend

EXPOSE 8000 3000
