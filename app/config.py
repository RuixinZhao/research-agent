import os
from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    HOST: str = "0.0.0.0"
    PORT: int = 8080
    
    # 平台注入环境变量（优先读取 PLATFORM_*，其次 CHALLENGE_*，默认使用 DeepSeek 规范）
    PLATFORM_LLM_URL: str = ""
    PLATFORM_API_KEY: str = ""
    PLATFORM_LLM_MODEL: str = ""
    PLATFORM_SESSION_ID: str = ""

    CHALLENGE_LLM_BASE_URL: str = "https://api.deepseek.com/v1"
    CHALLENGE_LLM_API_KEY: str = "EMPTY"
    CHALLENGE_LLM_MODEL: str = "deepseek-chat"
    CHALLENGE_SESSION_ID: str = "default_session"
    RESEARCH_WORKSPACE_TEAM: str = "team"

    @property
    def effective_llm_base_url(self) -> str:
        return (
            os.environ.get("PLATFORM_LLM_URL")
            or self.PLATFORM_LLM_URL
            or os.environ.get("CHALLENGE_LLM_BASE_URL")
            or self.CHALLENGE_LLM_BASE_URL
        )

    @property
    def effective_llm_api_key(self) -> str:
        return (
            os.environ.get("PLATFORM_API_KEY")
            or self.PLATFORM_API_KEY
            or os.environ.get("CHALLENGE_LLM_API_KEY")
            or self.CHALLENGE_LLM_API_KEY
        )

    @property
    def effective_llm_model(self) -> str:
        return (
            os.environ.get("PLATFORM_LLM_MODEL")
            or self.PLATFORM_LLM_MODEL
            or os.environ.get("CHALLENGE_LLM_MODEL")
            or self.CHALLENGE_LLM_MODEL
        )

    @property
    def effective_session_id(self) -> str:
        return (
            os.environ.get("PLATFORM_SESSION_ID")
            or self.PLATFORM_SESSION_ID
            or os.environ.get("CHALLENGE_SESSION_ID")
            or self.CHALLENGE_SESSION_ID
        )
    
    # 路径配置
    WORKSPACE_OUTPUT: str = os.environ.get("RESEARCH_RESULT_ROOT", "/output")
    PAPERS_DIR: str = "/data/papers"
    EXPERIMENTS_DIR: str = "/data/experiments"
    
    # 保护超时（平台总时限 180s，设置 175s 留足落盘与响应余量）
    TASK_TIMEOUT_SECONDS: int = 175


settings = Settings()
