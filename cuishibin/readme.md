uv pip install -e ".[service]"

docker run -d --name redis -p 6379:6379 redis:7-alpine

cd agentscope/examples/web_ui

# 启动 webui
pnpm install
pnpm dev