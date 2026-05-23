"""模型配置"""

AVAILABLE_MODELS = {
    # DeepSeek
    "deepseek-v4": {
        "provider": "deepseek",
        "model": "deepseek-4.0",
        "base_url": "https://api.deepseek.com",
        "api_key": "DEEPSEEK_API_KEY",
        "max_tokens": 800,
        "temperature": 0.7
    },
    # GLM
    "glm-5.1": {
        "provider": "glm",
        "model": "glm-5.1",
        "base_url": "https://maas-api.cn-huabei-1.xf-yun.com/v2",
        "api_key": "GLM_API_KEY",
        "max_tokens": 1024,
        "temperature": 0.7
    }
}

DEFAULT_MODEL = "deepseek-v4"


def get_model_config(model_name: str):
    """获取模型配置"""
    return AVAILABLE_MODELS.get(model_name, AVAILABLE_MODELS[DEFAULT_MODEL])
