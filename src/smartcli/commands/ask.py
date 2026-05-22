from ..services.llm import LLMService
def handle_ask(question:str):
    """处理AI问答命令"""
    print(f"思考中:{question[:50]}")
    llm = LLMService()
    answer = llm.ask(question)
    print(f"\n回答:{answer}") 

def handle_chat():
    """持续对话模式"""
    llm = LLMService()
    print("开始对话模式")
    print("输入'exit'退出对话")
    while True:
        user_input = input("你：").strip()
        if user_input.lower() in ["exit","quit","q"]:
            print("再见")
            break
        print(f"思考中...")
        answer = llm.ask(user_input)
        print(f"AI：{answer}")