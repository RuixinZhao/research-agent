import os
import uvicorn
from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import JSONResponse
from app.config import settings
from app.schemas.task import ChallengeTaskInput

app = FastAPI(title="Research-Agent", version="1.1.1")

# 动态按需加载 handlers 容器
_HANDLERS = {}

def get_handler(func_type: str):
    global _HANDLERS
    if func_type not in _HANDLERS:
        if func_type == "Chat":
            from app.handlers.chat_handler import ChatHandler
            _HANDLERS[func_type] = ChatHandler()
        elif func_type == "Literature_Retrieval":
            from app.handlers.retrieval_handler import RetrievalHandler
            _HANDLERS[func_type] = RetrievalHandler()
        elif func_type == "Survey":
            from app.handlers.survey_handler import SurveyHandler
            _HANDLERS[func_type] = SurveyHandler()
        elif func_type == "Reproduction":
            from app.handlers.reproduction_handler import ReproductionHandler
            _HANDLERS[func_type] = ReproductionHandler()
        elif func_type == "Idea":
            from app.handlers.idea_handler import IdeaHandler
            _HANDLERS[func_type] = IdeaHandler()
        else:
            raise ValueError(f"Unknown function: {func_type}")
    return _HANDLERS[func_type]

@app.get("/health")
def health():
    return {"status": "ok"}

@app.post("/solve")
async def solve(request: Request):
    try:
        raw_data = await request.json()
        task = ChallengeTaskInput(**raw_data)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Invalid Task Schema: {str(e)}")

    session_id = request.headers.get("X-Session-ID", settings.CHALLENGE_SESSION_ID)
    
    try:
        handler = get_handler(task.function)
        from app.core.circuit_breaker import TaskTimeoutGuard
        with TaskTimeoutGuard(case_id=task.case_id, timeout_seconds=settings.TASK_TIMEOUT_SECONDS):
            result_dict = handler.handle(task, session_id=session_id)
            return JSONResponse(content=result_dict)
    except Exception as e:
        # 异常兜底防护
        return JSONResponse(
            status_code=500,
            content={"case_id": task.case_id, "error": str(e), "status": "failed"}
        )

if __name__ == "__main__":
    uvicorn.run("server:app", host=settings.HOST, port=settings.PORT, workers=1)
