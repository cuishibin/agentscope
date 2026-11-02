"""OpenJudge RelevanceGrader 使用示例。

演示如何使用 OpenJudge 框架评估一个"回答是否切题"：
1. 创建指向自建 vLLM 服务的 OpenAI 兼容模型客户端；
2. 初始化 RelevanceGrader 评分器；
3. 对一组 (query, response) 数据执行异步评估并输出结果。

uv pip install py-openjudge
"""

import asyncio

from openjudge.graders.common.relevance import RelevanceGrader
from openjudge.models import OpenAIChatModel

# 自建 vLLM 服务的 OpenAI 兼容端点
BASE_URL = "http://10.10.1.226:1120/v1"
API_KEY = "sk-local-7sypfDboh5VAUol7Qmvs7UAe"
MODEL_NAME = "glm-5.3"


async def main() -> None:
    """运行切题度评估示例。

    Raises:
        Exception: 模型调用失败或评估结果解析失败时向上抛出。
    """
    # 1. 创建模型客户端（指向自建 vLLM 服务）
    model = OpenAIChatModel(
        model=MODEL_NAME,
        api_key=API_KEY,
        base_url=BASE_URL,
    )
    # 2. 初始化评分器（评估回答是否切题）
    grader = RelevanceGrader(model=model)
    
    # 3. 准备数据
    data = {
        "query": "What is machine learning?",
        "response": "Machine learning is a subset of AI that enables computers to learn from data.",
    }
    
    # 4. 评估并打印结果
    result = await grader.aevaluate(**data)
    print(f"Score: {result.score}")   # 输出如 Score: 4
    print(f"Reason: {result.reason}")


if __name__ == "__main__":
    asyncio.run(main())
