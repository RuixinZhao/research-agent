import os
import sys
import time
import re
from dotenv import load_dotenv

load_dotenv()

# Ensure environment variables
os.environ.setdefault('CHALLENGE_LLM_BASE_URL', 'https://api.deepseek.com/v1')
os.environ.setdefault('CHALLENGE_LLM_MODEL', 'deepseek-chat')

from app.handlers.survey_handler import SurveyHandler
from app.schemas.task import ChallengeTaskInput

def main():
    print("=== 开始执行 Live DeepSeek C 类端到端测试（零 PDF 引用 Fallback 模式）===")
    start_time = time.time()
    
    handler = SurveyHandler()
    task = ChallengeTaskInput(
        case_id="live-C-01",
        function="Survey",
        title="大语言模型推理加速综述",
        input="请综述当前大语言模型推理加速的主要技术路线，包括量化、蒸馏、投机解码等方法",
        materials=[],  # 无 PDF，测试 fallback 模式
        constraints=[],
        expected_output="",
        output_schema_ref="SurveyOutput"
    )

    result = handler.handle(task, "live-test-session")
    elapsed = time.time() - start_time
    md = result.get("markdown", "")
    
    print(f"执行耗时: {elapsed:.2f} 秒")
    print(f"输出文件路径: {result.get('path')}")
    print(f"综述字符总长度: {len(md)} 字")
    
    # 核心指标验证
    spurious = re.findall(r'\[\d+,\s*p\.\d+\]|\[\d+\]|<<DOC_\d+_PAGE_\d+_CHUNK_\d+>>', md)
    print(f"幻觉引用检查: {spurious}")
    assert len(spurious) == 0, f"发现非法引用: {spurious}"
    assert len(md) >= 800, f"字数不足 800 字: {len(md)}"
    assert "## 参考文献" in md, "未找到 ## 参考文献 章节"
    assert "暂无可溯源文献材料" in md, "未找到 '暂无可溯源文献材料' 规范声明"
    assert "> *注：本综述基于领域通用知识" in md, "未找到通用知识声明注记"
    
    headings = re.findall(r'##\s+[^\n]+', md)
    print(f"检测到的二级标题列表 ({len(headings)} 个):")
    for h in headings:
        print(f"  - {h}")
    assert len(headings) >= 4, f"标题层级不足 4 个: {len(headings)}"
    
    print("\n[SUCCESS] Live DeepSeek C 类任务端到端验证 100% 通过！无引用幻觉风险！")

if __name__ == "__main__":
    main()
