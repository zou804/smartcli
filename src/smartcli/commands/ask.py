from ..services.llm import LLMService


def handle_ask(question: str, role: str = "default", model: str = "deepseek-v4"):
    """处理AI问答命令"""
    role_names = {
        "default": "默认",
        "code": "代码助手",
        "translate": "翻译助手",
        "summary": "总结助手"
    }
    print(f"角色：{role_names.get(role, role)}")
    print(f"模型：{model}")
    llm = LLMService(model_name=model)
    answer = llm.ask(question, role=role)
    print(f"\n回答：{answer}")


def handle_chat(model: str = "deepseek-v4"):
    """持续对话模式"""
    llm = LLMService(model_name=model)
    print("开始对话模式")
    print("输入'exit'退出对话")
    while True:
        user_input = input("你：").strip()
        if user_input.lower() in ["exit", "quit", "q"]:
            print("再见")
            break
        print(f"思考中...")
        answer = llm.ask(user_input)
        print(f"AI：{answer}")
