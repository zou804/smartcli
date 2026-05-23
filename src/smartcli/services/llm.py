import os
from openai import OpenAI
from dotenv import load_dotenv
from .prompts import PromptTemplate
from ..config import get_model_config

# 加载环境变量
load_dotenv()


class LLMService:
    """大模型服务"""

    def __init__(self, model_name: str = "deepseek-v4"):
        config = get_model_config(model_name)
        
        # 获取 API Key
        api_key = os.getenv(config["api_key_env"])
        if not api_key:
            raise ValueError(f"请设置环境变量 {config['api_key_env']}")
        
        self.config = config
        self.model = config["model"]
        self.max_tokens = config["max_tokens"]
        self.temperature = config["temperature"]
        self.api_key = api_key
        
        # 初始化 OpenAI 客户端
        self.client = OpenAI(
            api_key=api_key,
            base_url=config["base_url"]
        )

    def ask(self, question: str, role: str = "default") -> str:
        """向AI提问,支持不同角色"""
        prompts = {
            "default": "你是一个友好的助手，回答简洁有用",
            "code": PromptTemplate.code_assistant(),
            "summary": PromptTemplate.summarizer(),
        }
        system_prompt = prompts.get(role, prompts["default"])

        try:
            response = self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": question}
                ],
                temperature=self.temperature,
                max_tokens=self.max_tokens
            )
            return response.choices[0].message.content
        except Exception as e:
            return f"请求失败：{str(e)}"


# 测试
if __name__ == "__main__":
    llm = LLMService()
    print(llm.ask("python装饰器是什么？"))
