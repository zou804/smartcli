"""模型配置"""

AVAILABLE_MODELS = {
    # DeepSeek
    "deepseek-v4": {
        "provider": "deepseek",
        "model": "deepseek-v4-pro",
        "base_url": "https://api.deepseek.com",
        "api_key_env": "DEEPSEEK_API_KEY",
        "max_tokens": 800,
        "temperature": 0.7
    },
    "deepseek-flash": {
        "provider": "deepseek",
        "model": "deepseek-v4-flash",
        "base_url": "https://api.deepseek.com",
        "api_key_env": "DEEPSEEK_API_KEY",
        "max_tokens": 500,
        "temperature": 0.7
    },
    # 智谱AI GLM
    "glm-5.1": {
        "provider": "glm",
        "model": "glm-5.1",
        "base_url": "https://open.bigmodel.cn/api/paas/v4",
        "api_key_env": "GLM_API_KEY",
        "max_tokens": 1024,
        "temperature": 0.7
    }
}

DEFAULT_MODEL = "deepseek-v4"


def get_model_config(model_name: str):
    """获取模型配置"""
    return AVAILABLE_MODELS.get(model_name, AVAILABLE_MODELS[DEFAULT_MODEL])
