import asyncio

from agentscope.agent import Agent, ReActConfig
from agentscope.credential import OpenAICredential
from agentscope.message import UserMsg
from agentscope.model import OpenAIChatModel
from agentscope.tool import Toolkit
from agentscope.mcp import MCPClient, HttpMCPConfig
from agentscope.state import AgentState
from agentscope.permission import PermissionContext, PermissionMode

# 兼容 OpenAI 协议的本地网关，通过 credential 携带 api_key 与 base_url
credential = OpenAICredential(
    api_key="sk-local-7sypfDboh5VAUol7Qmvs7UAe",
    base_url="http://10.10.1.226:1120/v1",
)

model = OpenAIChatModel(
    credential=credential,
    model="glm-5.3",
)

# dbhub MCP 客户端：通过 Streamable HTTP 连接 dbhub 服务，
# 获取 query/list_tables/describe_table/list_databases 等数据库工具
dbhub_mcp = MCPClient(
    name="dbhub",
    mcp_config=HttpMCPConfig(
        url="http://10.12.1.229:8080/mcp",
    ),
    # dbhub 为无状态 HTTP 服务，不需要维持会话状态
    is_stateful=False,
)


async def main() -> None:
    # 将 dbhub MCP 客户端注册到 Toolkit，由其管理工具的发现与调用
    toolkit = Toolkit(mcps=[dbhub_mcp])
    print(toolkit.__dict__)
    
    agent = Agent(
        name="Assistant",
        system_prompt="你是一个简洁的中文数据库助手，可查询 PostgreSQL 数据库。",
        model=model,
        toolkit=toolkit,
        # BYPASS：跳过工具执行权限确认（示例用途；生产环境请用更严格的模式）
        state=AgentState(
            permission_context=PermissionContext(
                mode=PermissionMode.BYPASS,
            ),
        ),
        # ReAct 循环的最大迭代次数（替代旧版 ReActAgent 的 max_iters 参数）
        react_config=ReActConfig(max_iters=50),
    )

    reply = await agent.reply(UserMsg("user", "当前系统有多少个用户"))
    print(reply)

    # 用完关闭 MCP 连接
    await dbhub_mcp.close()


asyncio.run(main())
