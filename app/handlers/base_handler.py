from abc import ABC, abstractmethod
from typing import Dict, Any
from app.schemas.task import ChallengeTaskInput
from app.core.file_writer import SecureFileWriter
from app.core.llm_gateway import LLMGatewayClient
from app.config import settings

class BaseHandler(ABC):
    """业务处理器统一抽象基类"""
    def __init__(self):
        self.file_writer = SecureFileWriter()
        self.llm = LLMGatewayClient()

    @property
    def team_name(self) -> str:
        return self.file_writer.team_name


    @abstractmethod
    def handle(self, task: ChallengeTaskInput, session_id: str) -> Dict[str, Any]:
        """子类必须实现的执行入口"""
        pass
