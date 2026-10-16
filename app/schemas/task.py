from pydantic import BaseModel, Field
from typing import List, Optional

class ChallengeTaskInput(BaseModel):
    case_id: str = Field(..., description="题目唯一编号")
    function: str = Field(..., description="题型类别: Chat, Literature_Retrieval, Survey, Reproduction, Idea")
    title: str = Field(default="", description="题目标题")
    input: str = Field(..., description="任务描述与具体输入要求")
    materials: List[str] = Field(default_factory=list, description="允许使用的材料清单")
    constraints: List[str] = Field(default_factory=list, description="必须遵守的约束")
    expected_output: str = Field(default="", description="预期输出要求")
    output_schema_ref: str = Field(..., description="指定输出格式引用")
