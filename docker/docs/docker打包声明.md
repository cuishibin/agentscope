生成agentscope的docker镜像服务

1、基础镜像使用python:3.11-slim
2、安装pnpm
3、使用docker-compose启动服务，重启后配置信息丢，如果大模型配置、已安装的mcp服务，skill等。


核心诉求：
1、将下面两个服务打包进去
服务1：智能体服务后端
git clone -b main https://github.com/agentscope-ai/agentscope.git
cd agentscope/examples/agent_service

# 启动智能体服务后端
python main.py

服务2：智能体服务前端
cd agentscope/examples/web_ui

# 启动 webui
pnpm install
pnpm dev

