import os
from openai import OpenAI
from dotenv import load_dotenv

#加载环境变量
load_dotenv()

class LLMService:
    """大模型服务"""
    def __init__(self):
        self.client = OpenAI(
            api_key = os.getenv("DEEPSEEK_API_KEY"),
            base_url = "https://api.deepseek.com"
        )
        self.model = "deepseek-v4-pro"

    def ask(self,question:str):
        """向AI提问"""
        try:
            response = self.client.chat.completions.create(
                model = self.model,
                messages = [
                    {"role":"system","content":"你是一个简洁助手，回答控制在100字以内"},
                    {"role":"user","content":question}
                ],
                temperature = 0.7,
                max_tokens = 500
            )
            return response.choices[0].message.content
        except Exception as e:
            return f"请求失败：{str(e)}"

#测试
if __name__ == "__main__":
    llm = LLMService()
    print(llm.ask("python装饰器是什么？"))
