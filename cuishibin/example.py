from agentscope.agent import Agent
from agentscope.console import launch_console
from agentscope.tool import Toolkit, Bash, Grep, Glob, Read, Write, Edit
from agentscope.credential import DashScopeCredential
from agentscope.model import DashScopeChatModel

import os, asyncio


async def main() -> None:
    agent = Agent(
        name="Friday",
        system_prompt="You're a helpful assistant named Friday.",
        model=DashScopeChatModel(
            credential=DashScopeCredential(
              api_key=os.environ["DASHSCOPE_API_KEY"]
            ),
            model="qwen3.6-plus",
        ),
        toolkit=Toolkit(
            tools=[
                Bash(),
                Grep(),
                Glob(),
                Read(),
                Write(),
                Edit(),
            ]
        ),
    )

    # 在终端中与智能体对话 —— 流式输出、工具调用确认、
    # Ctrl+C 中断均已内置处理
    await launch_console(agent)

asyncio.run(main())