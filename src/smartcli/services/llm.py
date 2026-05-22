import os
from openai import OpenAI
from dotenv import load_dotenv
from .prompts import PromptTemplate


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

    def ask(self,question:str,role:str ="default")->str:
        """向AI提问,支持不同角色"""
        #获取不同角色的Prompt
        prompts = {
            "default":"你是一个友好的助手，回答简洁有用",\
            "code":PromptTemplate.code_assistant(),
            "summary":PromptTemplate.summarizer(),
        }
        system_prompt = prompts.get(role,prompts["default"])

        try:
            response = self.client.chat.completions.create(
                model = self.model,
                messages = [
                    {"role":"system","content":system_prompt},
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
