import os, time, re, sys
sys.path.insert(0, "/Users/zhaoruixin/Desktop/research-agent")

os.environ['CHALLENGE_LLM_BASE_URL'] = 'https://api.deepseek.com/v1'
os.environ['CHALLENGE_LLM_API_KEY'] = 'sk-b40a8c91ae3e4ad7a2d6a57c745c60c2'
os.environ['CHALLENGE_LLM_MODEL'] = 'deepseek-chat'

from app.handlers.idea_handler import IdeaHandler, REQUIRED_SLOT_DEFINITIONS
from app.schemas.task import ChallengeTaskInput

handler = IdeaHandler()
task = ChallengeTaskInput(
    case_id="live-E-01",
    function="Idea",
    title="基于注意力机制的长文本理解创新方案",
    input="请针对 Transformer 长文本注意力效率问题，生成一个可行的研究创新方案，包含实验设计、基准选择和评估指标体系。方案需要考虑在 8GB 显存内可运行的约束。",
    materials=["attention_efficient.pdf", "longformer_paper.pdf"],
    constraints=["方案必须可在8GB显存内运行", "实验需要包含消融研究"],
    expected_output="",
    output_schema_ref="IdeaOutput"
)

start = time.time()
result = handler.handle(task, "live-e-test-session")
elapsed = time.time() - start

markdown = result['markdown']

# 验证 8 大槽位覆盖率
missing_slots = []
for std_heading, pattern in REQUIRED_SLOT_DEFINITIONS:
    if not re.search(pattern, markdown, re.IGNORECASE):
        missing_slots.append(std_heading)

# 检查第 6 槽是否有"模拟观察"相关措辞
slot6_match = re.search(r'##\s*(?:6\.?)?\s*.*(?:复现瓶颈|观察边界).*\n([\s\S]*?)(?=##|\Z)', markdown, re.IGNORECASE)
slot6_content = slot6_match.group(1)[:200] if slot6_match else ""
has_simulated_obs = bool(re.search(r'模拟观察|假设|待验证|理论推断', slot6_content))
has_definitive_claims = bool(re.search(r'实验证明|结果表明|我们发现.*%|准确率达到', slot6_content))

print(f"=== Live E 类测试结果 ===")
print(f"响应耗时：{elapsed:.1f}s")
print(f"内容长度：{len(markdown)} 字符")
print(f"长度达标（>800）：{len(markdown) > 800}")
print(f"缺失槽位：{missing_slots}")
print(f"8 大槽位 100% 覆盖：{len(missing_slots) == 0}")
print(f"第6槽含模拟观察措辞：{has_simulated_obs}")
print(f"第6槽含确定性陈述（危险）：{has_definitive_claims}")
print("--- 内容前 600 字符预览 ---")
print(markdown[:600])
