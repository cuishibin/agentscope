# AgentScope Docker 镜像服务设计文档

> **版本：v1**（定稿，2026-11-01）
>
> 依据：[docker打包声明.md](file:///d:/30-develop/github/agentscope/docker/docker打包声明.md)

## 1. 背景与目标

将 AgentScope 智能体服务（后端 + 前端）打包为 Docker 镜像，通过 docker-compose 一键启动。核心目标：

1. 以 `python:3.11-slim` 为基础镜像，镜像尽量精简；
2. 构建过程使用 pnpm；
3. **配置持久化**：容器重启后，大模型配置、已安装的 MCP 服务、Skill 等信息不丢失。

**决策记录**：前端运行模式采用 **方案 B（build 产物模式）**——构建期完成 `pnpm build`，运行期仅承载静态产物与 Express 生产进程；弃用方案 A（dev 模式），理由：启动慢（每次 `pnpm install` + 实时编译）、镜像臃肿（携带 Vite/nodemon/ts-node 等开发依赖）、多暴露一个 5173 端口。

## 2. 服务构成

| 服务 | 目录 | 运行命令 | 端口 |
| --- | --- | --- | --- |
| 智能体服务后端 | `examples/agent_service` | `uvicorn main:app --host 0.0.0.0 --port 8000` | 8000 |
| 智能体服务前端 | `examples/web_ui` | `node backend/dist/index.js`（Express 同时托管 `frontend/dist` 静态文件） | 3000 |

### 2.1 端口职责澄清

- **8000**：`examples/agent_service/main.py` 启动的 FastAPI，是核心业务服务，承载 Agent、会话、MCP、Skill、知识库等全部 API；前端通过 `localStorage.server_url` 从浏览器直连该端口（见 [client.ts](file:///d:/30-develop/github/agentscope/examples/web_ui/frontend/src/api/client.ts#L3)）；
- **3000**：`examples/web_ui/backend` 的 Express 服务。原实现仅有 `/api/health`（见 [index.ts](file:///d:/30-develop/github/agentscope/examples/web_ui/backend/src/index.ts)），方案 B 中扩展为同时托管前端静态产物，成为页面入口；
- 两者**不是同一个服务**，3000 是 web_ui 自带的薄 Node 层，8000 才是业务核心。

后端依赖说明（来自 [main.py](file:///d:/30-develop/github/agentscope/examples/agent_service/main.py)）：

- **RedisStorage**：当前硬编码 `localhost:6379`，所有会话、Agent、MCP、Skill 等配置均存于 Redis —— 这是持久化的关键，compose 中需引入 Redis 服务；
- **LocalWorkspaceManager**：工作区默认落在 `examples/agent_service/workspaces`，含长期记忆、Agent 产物，需要挂载为数据卷；
- **QdrantStore(location=":memory:")**：知识库向量存储当前为内存态，重启即失——本次设计改为**嵌入式本地文件模式**（落盘到 `qdrant_storage/` 并挂卷持久化，见 §5.1），不引入独立 Qdrant 容器（`qdrant-client` 库自带嵌入式引擎，`.[full]` 已含 `vdb-qdrant` extra）；
- 默认 MCP `playwright` 依赖 `npx`，运行镜像需包含 Node.js；
- 可选环境变量：`AMAP_API_KEY`、`CLAWHUB_API_TOKEN`。

## 3. 总体架构

```
┌──────────────────────────── docker-compose ────────────────────────────┐
│                                                                        │
│  ┌──────────────────┐      ┌──────────────────────┐   ┌────────────┐  │
│  │ agent-service    │      │ web-ui               │   │ redis      │  │
│  │ FastAPI :8000    │      │ Express :3000        │   │ redis:7-   │  │
│  │ (python:3.11-    │      │  ├ /api/health       │   │ alpine     │  │
│  │  slim + node22)  │      │  └ frontend/dist 静态 │   │ :6379      │  │
│  └───────┬──────────┘      └──────────┬───────────┘   └─────┬──────┘  │
│          │  RedisStorage              │                     │         │
│          └────────────────────────────┴─────────────────────┘         │
│                                                                        │
│  数据卷:                                                               │
│   - agentscope_redis_data → /data                     (配置/会话元数据) │
│   - agentscope_workspaces → /app/.../workspaces       (工作区/长期记忆) │
│   - agentscope_qdrant     → /app/.../qdrant_storage   (知识库向量)     │
└────────────────────────────────────────────────────────────────────────┘

请求链路:
  浏览器 ──> :3000  Express (页面 + 静态资源 + /api/health)
  浏览器 ──> :8000  FastAPI  (server_url 直连，业务 API / SSE 流)
```

- **单镜像双容器**：一个多阶段构建镜像，`agent-service` 与 `web-ui` 各起一个容器，职责清晰、可独立扩缩；
- **Redis 独立容器**：后端 `RedisStorage` 通过环境变量 `REDIS_HOST=redis` 连接（见 §5.3）。

## 4. 镜像设计（多阶段 Dockerfile，方案 B）

### 4.1 阶段划分

```dockerfile
# ============ 阶段 1：前端构建（builder） ============
FROM node:22-slim AS web-builder

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
RUN pnpm build   # = build:frontend (tsc -b && vite build) + build:backend (tsc)
# 生成 backend 的自包含生产目录：pnpm workspace 下 backend/node_modules
# 内是指向根 node_modules/.pnpm 的符号链接，直接拷贝会得到断链；
# pnpm deploy 会解析链接并只保留生产依赖，产出可独立运行的目录。
# 注意执行顺序：先 build 再 deploy，dist/ 才会被带入 deploy 产物；
# 实施时验证 /deploy/backend/dist/index.js 存在，缺失则补 cp。
RUN pnpm deploy --filter=backend --prod /deploy/backend

# ============ 阶段 2：运行时镜像 ============
FROM python:3.11-slim

# Node 22 为运行必需：playwright MCP 经 npx 拉起，web-ui 容器运行 node 进程。
# 优化：直接从官方 node 镜像拷贝二进制，避免 NodeSource apt 源残留，且与
# 构建阶段 Node 版本天然一致（比 apt 安装小且干净）。
COPY --from=node:22-slim /usr/local/bin/node /usr/local/bin/node
COPY --from=node:22-slim /usr/local/lib/node_modules /usr/local/lib/node_modules
# npx 是 node 镜像内的符号链接，需保留可执行位
RUN ln -s /usr/local/lib/node_modules/npm/bin/npx-cli.js /usr/local/bin/npx \
    && ln -s /usr/local/lib/node_modules/npm/bin/npm-cli.js /usr/local/bin/npm

# uv 安装器：比 pip 快一个量级，无需额外缓存挂载
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

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
```

### 4.2 要点说明

- **pnpm 只出现在构建阶段**：满足声明"使用 pnpm"的要求，同时运行镜像不携带 pnpm store 与 devDependencies，体积可控；pnpm 版本固定（`10.18.3`，与 pnpm-workspace.yaml 的 10.x 语法对齐）保证构建可复现，并以 `HUSKY=0` 禁用 prepare 钩子（构建上下文无 `.git`）；
- **源码安装 agentscope**：PyPI 最新 2.0.10 落后本地 main 分支（2.0.12dev）且 extras 结构已分叉，`main.py` 的 `agentscope.app` 系列导入在 PyPI 版本不可用，必须 `COPY src` 后 `uv pip install ".[full]"`；待 PyPI 追平（≥2.0.12）可切换为 PyPI 安装以省去拷贝源码；
- **Node 22 双重必要性**：运行期 `npx @playwright/mcp@latest`（后端默认 MCP）与 `node backend/dist/index.js`（web-ui 容器进程）均需要 Node；运行镜像直接从 `node:22-slim` 拷贝二进制，避免 NodeSource apt 源残留；
- **backend 依赖裁剪**：`pnpm deploy --filter=backend --prod` 生成自包含生产目录（解析 workspace 符号链接、仅保留 express/cors 生产依赖），运行镜像直接整体拷入，规避断链问题；
- **layer 缓存**：依赖清单单独前置 COPY，源码变更不触发 `pnpm install` 重跑；
- **非 root 用户**（可选加固）：创建 `appuser` 运行，挂载卷时注意属主。

### 4.3 源码改动清单（方案 B 需要）

| # | 文件 | 改动 | 说明 |
| --- | --- | --- | --- |
| 1 | `examples/web_ui/backend/src/index.ts` | 增加 `express.static` 托管 `frontend/dist` + SPA fallback | 使 Express 单进程同时提供页面与 API，替代 Vite dev server |
| 2 | `examples/agent_service/main.py` | `RedisStorage(host=os.getenv("REDIS_HOST","localhost"), port=int(os.getenv("REDIS_PORT",6379)))` | 指向 compose 内 redis 服务 |
| 3 | `examples/agent_service/main.py` | `QdrantStore(path=...)` 由 `:memory:` 改为本地目录 `qdrant_storage/`（注意是 `path` 参数而非 `location`） | 知识库向量数据持久化，重启不丢（见 §5.1） |

`backend/src/index.ts` 改动示意（约 6 行，含注释）：

```ts
import path from 'path';
// 静态产物路径：dist/index.js 的 __dirname 为 backend/dist，
// 向上两级回到 web_ui 根，再进入 frontend/dist。
// 路径可用 FRONTEND_DIST 环境变量覆盖（容器/本地部署更灵活）。
const frontendDist =
	process.env.FRONTEND_DIST ??
	path.resolve(__dirname, '../../frontend/dist');
app.use(express.static(frontendDist));
// SPA fallback：非 /api 路径统一回退到 index.html，交给前端路由
// （用中间件而非路径正则，规避 Express 版本间正则行为差异）
app.use((req, res, next) => {
	if (req.method === 'GET' && !req.path.startsWith('/api')) {
		res.sendFile(path.join(frontendDist, 'index.html'));
		return;
	}
	next();
});
```

## 5. 持久化设计（核心诉求）

声明指出"重启后配置信息丢失"是痛点，持久化拆解为两块：

### 5.1 需持久化的数据

| 数据 | 存储位置 | 持久化方式 |
| --- | --- | --- |
| 大模型配置、MCP 安装记录、Skill、Agent、会话元数据 | Redis（RedisStorage） | Redis 容器数据卷 `agentscope_redis_data` |
| 工作区文件、长期记忆（Markdown）、Agent 产物 | `agent_service/workspaces/` | 命名卷 `agentscope_workspaces` |
| 知识库向量数据 | `agent_service/qdrant_storage/`（嵌入式本地文件模式） | 命名卷 `agentscope_qdrant` |

（方案 A 中的 `pnpm-store` 卷在方案 B 下不再需要：构建期已完成安装，运行期无安装动作。）

**Qdrant 持久化改造**：`main.py` 中 `QdrantStore(location=":memory:")` 改为本地文件模式，向量数据随卷落盘：

```python
# 嵌入式持久化：向量数据落盘到 qdrant_storage/（容器内挂卷），重启不丢。
# 注意参数用 path 而非 location：location 仅接受 ":memory:" 或服务 URL，
# path 才是"本地目录的落盘实例"模式（见 QdrantStore.__init__ 签名）。
vector_store = QdrantStore(
    path=os.path.join(
        os.path.dirname(os.path.abspath(__file__)),
        "qdrant_storage",
    ),
)
```

### 5.2 docker-compose 数据卷

```yaml
volumes:
  agentscope_redis_data:   # Redis AOF 持久化
  agentscope_workspaces:   # LocalWorkspaceManager 工作区
  agentscope_qdrant:       # Qdrant 嵌入式向量存储落盘
```

Redis 需开启持久化：`command: redis-server --appendonly yes`。

### 5.3 后端连接 Redis 的适配

`main.py` 中 `RedisStorage(host="localhost", port=6379)` 为硬编码。设计采用**环境变量化**（改动 2 行，收益最大）：

```python
storage = RedisStorage(
    host=os.getenv("REDIS_HOST", "localhost"),
    port=int(os.getenv("REDIS_PORT", "6379")),
)
```

compose 中设置 `REDIS_HOST=redis`，本地裸跑不受影响（默认值仍为 localhost）。

### 5.4 重启策略

所有服务设置 `restart: unless-stopped`，宿主机/容器重启后自动拉起，数据由卷保证不丢。

## 6. docker-compose.yml 设计

```yaml
services:
  redis:
    image: redis:7-alpine
    command: redis-server --appendonly yes   # AOF 持久化，重启不丢
    volumes:
      - agentscope_redis_data:/data
    healthcheck:                             # 确保 FastAPI 启动时 Redis 已就绪
      test: ["CMD", "redis-cli", "ping"]
      interval: 5s
      timeout: 3s
      retries: 5
    restart: unless-stopped

  agent-service:                       # 智能体服务后端（FastAPI）
    build:
      context: ../..
      dockerfile: docker/build/Dockerfile
    command: uvicorn main:app --host 0.0.0.0 --port 8000
    working_dir: /app/agent_service
    environment:
      - REDIS_HOST=redis
      - AMAP_API_KEY=${AMAP_API_KEY:-}
      - CLAWHUB_API_TOKEN=${CLAWHUB_API_TOKEN:-}
    volumes:
      - agentscope_workspaces:/app/agent_service/workspaces
      - agentscope_qdrant:/app/agent_service/qdrant_storage
    ports:
      - "8000:8000"
    depends_on:
      redis:
        condition: service_healthy      # 等待 Redis 就绪，避免启动即连失败
    restart: unless-stopped

  web-ui:                             # 智能体服务前端（Express + 静态产物）
    build:
      context: ../..
      dockerfile: docker/build/Dockerfile
    command: node dist/index.js
    working_dir: /app/web_ui/backend
    environment:
      - PORT=3000
    ports:
      - "3000:3000"
    restart: unless-stopped

volumes:
  agentscope_redis_data:   # 显式命名，避免多 compose 项目间卷混淆
  agentscope_workspaces:
  agentscope_qdrant:       # Qdrant 嵌入式向量存储落盘
```

说明：

- 构建上下文为仓库根目录（需拷贝 `pyproject.toml` 与 `examples/`），compose 与 Dockerfile 位于 `docker/build/`，故 `context: ../..`、`dockerfile: docker/build/Dockerfile`；
- `uvicorn main:app` 以 CLI 方式启动而非 `python main.py`，规避 main.py 中 `reload=True`（Linux 下热重载不适合生产）；
- 3000 承载页面必须对外；8000 承载业务 API 且前端从浏览器直连，也必须对外。

## 7. 端口与网络

| 端口 | 服务 | 用途 | 对外 |
| --- | --- | --- | --- |
| 8000 | agent-service | FastAPI 业务 API / SSE 流 | 是（前端 server_url 直连） |
| 3000 | web-ui | 页面入口 + 静态资源 + /api/health | 是 |
| 6379 | redis | RedisStorage 存储 | 否（仅 compose 内部） |

容器间通过 compose 默认 bridge 网络以服务名互访。

**首次使用流程**：浏览器打开 `http://<宿主机>:3000` → setup 页配置 `server_url` 为 `http://<宿主机>:8000` → 前端业务请求经浏览器直达 FastAPI。

## 8. 目录结构（产出物）

设计与生成物分离存放：

```
docker/
├── docker打包声明.md      # 需求输入（原始声明）
├── docs/                  # 设计文档目录
│   └── docker设计文档_v1.md  # 本文档（v1）
└── build/                 # 生成物目录（Docker 构建相关文件）
    ├── Dockerfile         # 多阶段：web-builder(node22+pnpm) → runtime(python3.11-slim+node22)
    ├── docker-compose.yml # redis / agent-service / web-ui 三服务
    ├── .env.example       # AMAP_API_KEY / CLAWHUB_API_TOKEN 等环境变量样例
    └── .dockerignore      # 排除 .git、docker/docs、**/node_modules、examples/agent_service/workspaces、examples/agent_service/qdrant_storage、**/dist 等
```

## 9. 风险与注意事项

1. ~~Qdrant 内存向量库~~：已改嵌入式本地文件模式并挂卷持久化（§5.1）；如后续出现多实例并发写入，再演进为独立 Qdrant 容器（`QdrantStore(url=...)`）；
2. **InMemoryMessageBus**：多进程/生产部署建议启用 `RedisMessageBus`（main.py 中已有注释说明）；
3. **硬编码 MCP**：`dbhub` 指向 `http://10.12.1.229:8080/mcp` 内网地址，容器化后需网络可达，建议环境变量化；
4. **playwright MCP**：运行时经 npx 拉取 `@playwright/mcp@latest`，容器内需可访问 npm registry；如需离线/加速，可在镜像内预装该包并改为本地命令；
5. ~~SPA fallback 正则~~：已改为中间件写法（§4.3），规避 Express 版本间路径正则行为差异，实施时验证子路径刷新场景；
6. **前端构建 Node 版本**：frontend 依赖较新（vite 8、typescript 6），构建阶段固定 `node:22-slim`；
7. **构建上下文体积**：上下文为仓库根目录，`.dockerignore` 必须精确排除 `docker/docs/`、`**/node_modules`、`examples/agent_service/workspaces/`、`examples/agent_service/qdrant_storage/`、`**/dist`、`.git`，否则构建上传缓慢；其中 `docker/docs/` 用于排除本次设计文档目录，避免误写成仓库根 `docs/`；排除 `.git` 与 husky prepare 的冲突已通过 `HUSKY=0` 解决；
8. **server_url 与跨域**：前端从浏览器直连 8000，main.py 已配置 `CORSMiddleware(allow_origins=["*"])`，无跨域障碍；但浏览器直连要求 8000 对用户网络可达，反向代理场景（nginx 统一入口）作为演进项。

## 10. 实施步骤（验收清单）

1. [ ] 改动 `backend/src/index.ts`：静态托管 + SPA fallback（§4.3）；
2. [ ] 改动 `main.py`：RedisStorage 地址环境变量化（§5.3）+ QdrantStore 本地文件化（§5.1）；
3. [ ] 编写 `docker/build/Dockerfile`（多阶段，§4.1）；
4. [ ] 编写 `docker/build/docker-compose.yml`（§6）；
5. [ ] 编写 `docker/build/.env.example` 与 `docker/build/.dockerignore`（排除项至少含 `docker/docs/`、`examples/agent_service/workspaces/`、`examples/agent_service/qdrant_storage/`、`**/node_modules`、`**/dist`、`.git`）；
6. [ ] 本地验证 Express 托管：`pnpm build && node backend/dist/index.js`，访问 :3000 页面正常；
7. [ ] 构建验证：`docker compose up -d --build`，访问 http://localhost:3000 出页面、setup 页配置 8000 后功能正常；
8. [ ] 持久化验证：在 UI 中配置模型、安装 MCP/Skill、创建知识库并上传文档 → `docker compose restart` → 配置与知识库检索均正常；
9. [ ] （演进）RedisMessageBus、nginx 统一入口 + 路径前缀、独立 Qdrant 容器。

## 11. 实施记录（2026-11-01）

本次开发已按本文档完成实施，涉及以下源文件改动（均向后兼容，本地裸跑行为不变）：

| # | 文件 | 改动内容 | 对应章节 |
| --- | --- | --- | --- |
| 1 | [examples/web_ui/backend/src/index.ts](file:///d:/30-develop/github/agentscope/examples/web_ui/backend/src/index.ts) | 新增 `path` 导入；增加 `express.static` 托管 `frontend/dist`（支持 `FRONTEND_DIST` 环境变量覆盖）+ SPA fallback 中间件（非 `/api` 的 GET 请求回退 `index.html`） | §4.3 改动 1 |
| 2 | [examples/agent_service/main.py](file:///d:/30-develop/github/agentscope/examples/agent_service/main.py) | `RedisStorage` 地址改为环境变量化：`host=os.getenv("REDIS_HOST", "localhost")`、`port=int(os.getenv("REDIS_PORT", "6379"))` | §5.3 / §4.3 改动 2 |
| 3 | [examples/agent_service/main.py](file:///d:/30-develop/github/agentscope/examples/agent_service/main.py) | `QdrantStore(location=":memory:")` 改为 `QdrantStore(path=<main.py 同目录>/qdrant_storage)`，嵌入式本地文件模式落盘 | §5.1 / §4.3 改动 3 |

新增产出物（非源码改动，均在 `docker/build/` 下）：

- `docker/build/Dockerfile`：多阶段构建（§4.1）；
- `docker/build/docker-compose.yml`：redis / agent-service / web-ui 三服务（§6）；
- `docker/build/.env.example`：环境变量样例；
- `docker/build/Dockerfile.dockerignore`：**与 §8 设计的偏差**——`.dockerignore` 仅在构建上下文根（仓库根）生效，为避免污染仓库根，改用 BuildKit 的 Dockerfile 专属 ignore（`<Dockerfile 名>.dockerignore`，与 Dockerfile 同目录，优先级更高），排除内容与 §8 要求一致。
