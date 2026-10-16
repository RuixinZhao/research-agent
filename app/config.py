import os
from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    HOST: str = "0.0.0.0"
    PORT: int = 8080
    
    # 平台注入环境变量（优先读取环境与 .env，默认使用 DeepSeek 规范）
    CHALLENGE_LLM_BASE_URL: str = "https://api.deepseek.com/v1"
    CHALLENGE_LLM_API_KEY: str = "EMPTY"
    CHALLENGE_LLM_MODEL: str = "deepseek-chat"
    CHALLENGE_SESSION_ID: str = "default_session"
    RESEARCH_WORKSPACE_TEAM: str = "team"
    
    # 路径配置
    WORKSPACE_OUTPUT: str = "/output"
    PAPERS_DIR: str = "/data/papers"
    EXPERIMENTS_DIR: str = "/data/experiments"
    
    # 保护超时
    TASK_TIMEOUT_SECONDS: int = 150

settings = Settings()
