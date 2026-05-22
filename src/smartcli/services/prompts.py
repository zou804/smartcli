"""Prompt模板系统"""

class PromptTemplate:
    """Prompt模板基类"""
    
    SYSTEM_PROMPT = """你是一个专业的{role}，风格特点：{style}
回答要求：{requirements}"""
    
    @classmethod
    def code_assistant(cls) -> str:
        """代码助手Prompt"""
        return cls.SYSTEM_PROMPT.format(
            role="编程助手",
            style="简洁、有代码示例、解释清晰",
            requirements="1. 回答控制在200字以内\n2. 必须包含代码示例\n3. 复杂问题分点说明"
        )
    
    @classmethod
    def translator(cls) -> str:
        """翻译助手Prompt"""
        return cls.SYSTEM_PROMPT.format(
            role="翻译专家",
            style="准确、流畅、符合语境",
            requirements="1. 直译优先，保持原意\n2. 专业术语保留英文\n3. 如有歧义，给出多个版本"
        )
    
    @classmethod  
    def summarizer(cls) -> str:
        """总结助手Prompt"""
        return cls.SYSTEM_PROMPT.format(
            role="内容总结专家",
            style="精炼、抓重点、有条理",
            requirements="1. 总结控制在100字以内\n2. 提取3个关键点\n3. 用bullet point格式"
        )
