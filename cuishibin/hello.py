"""Simple AgentScope hello-world example adapted to the new Agent API.

Note: In this version of AgentScope:
- The standalone `ReActAgent` class has been merged into the base `Agent`
  class, and the ReAct loop parameters (e.g. `max_iters`) are configured
  via `ReActConfig`.
- Models are now authenticated via `Credential` objects, and the model
  name is passed through the `model` argument.
"""
import asyncio

from agentscope.agent import Agent, ReActConfig
from agentscope.credential import OpenAICredential
from agentscope.message import UserMsg
from agentscope.model import OpenAIChatModel

# 兼容 OpenAI 协议的本地网关，通过 credential 携带 api_key 与 base_url
credential = OpenAICredential(
    api_key="sk-local-7sypfDboh5VAUol7Qmvs7UAe",
    base_url="http://10.10.1.226:1120/v1",
)

model = OpenAIChatModel(
    credential=credential,
    model="glm-5.3",
)

agent = Agent(
    name="Assistant",
    system_prompt="你是一个简洁的中文助手。",
    model=model,
    # ReAct 循环的最大迭代次数（替代旧版 ReActAgent 的 max_iters 参数）
    react_config=ReActConfig(max_iters=50),
)


async def main() -> None:
    """Run the agent with a greeting and print its reply.

    Returns:
        None
    """
    reply = await agent.reply(UserMsg("user", "你好，介绍一下你自己"))
    print(reply)


asyncio.run(main())
