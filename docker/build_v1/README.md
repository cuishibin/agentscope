# AgentScope Docker 构建与验证指南

> 依据：[docker设计文档_v1.md](../docs/docker设计文档_v1.md)
>
> 适用：`docker/build/` 下的 Dockerfile 与 docker-compose.yml

## 一、前置条件

| 依赖 | 说明 |
| --- | --- |
| Docker Engine ≥ 24（含 BuildKit） | `Dockerfile.dockerignore` 依赖 BuildKit 的 Dockerfile 专属 ignore 特性 |
| Docker Compose v2 | 使用 `docker compose`（带空格）子命令 |
| 外网访问 | 构建需拉取基础镜像与 npm/PyPI 包；运行期 `npx @playwright/mcp@latest` 也需访问 npm registry |
| 磁盘空间 ≥ 5GB | 镜像含 Python + Node 双运行时 |

> Windows 下建议在 PowerShell 7 中执行；确认 BuildKit 已启用：`docker buildx version`。

## 二、目录结构

```
docker/
├── docs/                       # 设计文档（已排除出构建上下文）
└── build/                      # 本目录
    ├── Dockerfile              # 多阶段：web-builder(node22+pnpm) → runtime(python3.11-slim+node22)
    ├── Dockerfile.dockerignore # 构建上下文排除规则（仓库根视角）
    ├── docker-compose.yml      # redis / agent-service / web-ui 三服务
    └── .env.example            # 环境变量样例
```

构建上下文为**仓库根目录**（`context: ../..`），需拷贝 `pyproject.toml`、`src/`、`examples/` 等。

## 三、构建与启动

```powershell
cd docker/build

# 1. 准备环境变量（均为可选项，可留空）
Copy-Item .env.example .env

# 2. 构建并后台启动（首次构建约需数分钟）
docker compose up -d --build
```

### 环境变量说明（.env）

| 变量 | 必填 | 用途 |
| --- | --- | --- |
| `AMAP_API_KEY` | 否 | 高德地图 MCP，配置后自动挂载 |
| `CLAWHUB_API_TOKEN` | 否 | ClawHub Skill 市场，仅提升速率限制 |

大模型的 API Key **不在 .env 中配置**——启动后在 Web UI 的「凭证」页面填写，存于 Redis（持久化）。

## 四、验证清单

### 4.1 容器状态

```powershell
docker compose ps
```

预期：`redis`（healthy）、`agent-service`、`web-ui` 三容器均 running。

```powershell
# 排查后端问题（常见：Redis 连接、npx 拉取 playwright MCP 需外网）
docker compose logs agent-service
docker compose logs web-ui
```

### 4.2 页面与 API

| 检查项 | 操作 | 预期 |
| --- | --- | --- |
| 前端页面 | 打开 http://localhost:3000 | 出现页面（非 404） |
| SPA 子路径刷新 | 访问 http://localhost:3000/chat 后刷新 | 页面正常，不 404 |
| web-ui 健康检查 | http://localhost:3000/api/health | `{"status":"ok"}` |
| 后端 API | http://localhost:8000/docs | FastAPI Swagger 页面 |

### 4.3 首次配置（setup 流程）

1. 浏览器打开 `http://localhost:3000`；
2. setup 页将 `server_url` 配置为 `http://<宿主机IP>:8000`（本机即 `http://localhost:8000`）；
3. 「凭证」页面配置大模型 API Key；
4. 聊天页创建会话、选择模型、发送消息，确认流式回复正常；
5. 安装一个 MCP / Skill，创建知识库并上传文档，确认可检索。

### 4.4 持久化验证（核心诉求）

```powershell
docker compose restart
```

重启后逐一确认不丢：

- [ ] 模型凭证配置（凭证页仍列出已配的 API Key）
- [ ] 会话历史与模型选择
- [ ] 已安装的 MCP / Skill
- [ ] 知识库及其文档可继续检索

数据落点（`docker volume ls` 中的三个命名卷）：

| 卷 | 容器路径 | 内容 |
| --- | --- | --- |
| `agentscope_redis_data` | redis:/data | 模型配置、会话、MCP/Skill 记录（AOF） |
| `agentscope_workspaces` | agent-service:/app/agent_service/workspaces | 工作区、长期记忆 |
| `agentscope_qdrant` | agent-service:/app/agent_service/qdrant_storage | 知识库向量数据 |

## 五、常用运维命令

```powershell
docker compose up -d --build   # 改代码后重建并启动
docker compose logs -f agent-service   # 跟踪后端日志
docker compose restart        # 重启（验证持久化）
docker compose down           # 停止并移除容器（卷保留，数据不丢）
docker compose down -v        # ⚠️ 连同数据卷一起删除（清空全部配置）
```

## 六、常见问题

| 现象 | 原因与处理 |
| --- | --- |
| agent-service 启动即退出，日志报 Redis 连接失败 | 检查 redis 容器是否 healthy；compose 已配置 `depends_on: service_healthy`，若仍失败查看 `docker compose logs redis` |
| playwright MCP 拉起失败 | 容器内 `npx` 需访问 npm registry；离线环境可在镜像内预装 `@playwright/mcp` 并改造 main.py 中的启动命令 |
| `docker compose ps` 中 redis 非 healthy | 等待 healthcheck（5s 间隔 × 5 次）；持续失败则 `docker compose logs redis` 排查 |
| 前端页面 404 | 确认构建日志中 `pnpm build` 成功且 `frontend/dist` 已生成 |
| 8000 接口浏览器连不上 | server_url 需用宿主机可达地址；远程服务器部署时填 `http://<服务器IP>:8000` 而非 localhost |
| dbhub MCP 不可用 | main.py 中硬编码内网地址 `10.12.1.229:8080`，需容器网络可达（已知设计约束，见设计文档 §9） |

## 七、清空重来

```powershell
docker compose down -v      # 删除容器与全部数据卷
# 可选：删除镜像
docker image rm $(docker images --filter "label=com.docker.compose.project=agentscope" -q)
```
