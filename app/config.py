import os
from pydantic_settings import BaseSettings

class Settings(BaseSettings):
    HOST: str = "0.0.0.0"
    PORT: int = 8080
    
    # 平台注入环境变量
    CHALLENGE_LLM_BASE_URL: str = os.environ.get("CHALLENGE_LLM_BASE_URL", "http://127.0.0.1:8000/v1")
    CHALLENGE_LLM_API_KEY: str = os.environ.get("CHALLENGE_LLM_API_KEY", "EMPTY")
    CHALLENGE_LLM_MODEL: str = os.environ.get("CHALLENGE_LLM_MODEL", "gpt-4o-mini")
    CHALLENGE_SESSION_ID: str = os.environ.get("CHALLENGE_SESSION_ID", "default_session")
    RESEARCH_WORKSPACE_TEAM: str = os.environ.get("RESEARCH_WORKSPACE_TEAM", "team")
    
    # 路径配置
    WORKSPACE_OUTPUT: str = "/output"
    PAPERS_DIR: str = "/data/papers"
    EXPERIMENTS_DIR: str = "/data/experiments"
    
    # 保护超时
    TASK_TIMEOUT_SECONDS: int = 150

settings = Settings()
