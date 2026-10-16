from pydantic import BaseModel, Field
from typing import List, Optional

class ChatOutput(BaseModel):
    case_id: str
    answer: str
    clarifying_question: str

class PaperItem(BaseModel):
    filename: str
    reason: str

class RetrievalOutput(BaseModel):
    case_id: str
    papers: List[PaperItem]

class SurveyOutput(BaseModel):
    case_id: str
    path: str
    markdown: str

class MetricItem(BaseModel):
    name: str
    unit: str
    reference: Optional[float] = None
    observed: Optional[float] = None
    relative_error: Optional[float] = None

class FigureItem(BaseModel):
    path: str
    caption: str
    x_label: str
    y_label: str
    legend: str

class ReproductionOutput(BaseModel):
    case_id: str
    status: str
    metrics: List[MetricItem]
    figures: List[FigureItem]

class IdeaOutput(BaseModel):
    case_id: str
    path: str
    markdown: str

# 兼容性别名
ChatResponseSchema = ChatOutput
IdeaResponseSchema = IdeaOutput

