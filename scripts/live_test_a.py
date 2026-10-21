import os, sys
from dotenv import load_dotenv

load_dotenv()
sys.path.insert(0, "/Users/zhaoruixin/Desktop/research-agent")

os.environ.setdefault('CHALLENGE_LLM_BASE_URL', os.getenv('CHALLENGE_LLM_BASE_URL', 'https://api.deepseek.com/v1'))
os.environ.setdefault('CHALLENGE_LLM_MODEL', os.getenv('CHALLENGE_LLM_MODEL', 'deepseek-chat'))

from app.handlers.chat_handler import ChatHandler
from app.schemas.task import ChallengeTaskInput

handler = ChatHandler()

# 场景 1：科研专业问题，期望专业解答
task1 = ChallengeTaskInput(
    case_id="live-A-01", function="Chat", title="LoRA 原理",
    input="请详细解释 LoRA（Low-Rank Adaptation）微调的数学原理和相比全参数微调的工程优势",
    materials=[], constraints=[], expected_output="", output_schema_ref="ChatOutput"
)
result1 = handler.handle(task1, "live-a-test-1")
print("=== 场景 1：科研专业问题 ===")
print(f"回答长度：{len(result1['answer'])} 字符")
print(f"回答前 300 字符：{result1['answer'][:300]}")
print()

# 场景 2：范围外问题，期望触发澄清/拒绝，而非真的回答
task2 = ChallengeTaskInput(
    case_id="live-A-02", function="Chat", title="写诗",
    input="帮我写一首关于春天的诗，要押韵",
    materials=[], constraints=[], expected_output="", output_schema_ref="ChatOutput"
)
result2 = handler.handle(task2, "live-a-test-2")
print("=== 场景 2：范围外问题（应触发澄清）===")
print(f"回答前 300 字符：{result2['answer'][:300]}")

# 验证：回答中应含有"超出范围"或"科研"等边界说明措辞
import re
boundary_words = re.findall(r'超出|范围|科研助手|不在|专业范围|无法', result2['answer'])
print(f"边界限定措辞检测：{boundary_words}")
print(f"范围限定触发：{len(boundary_words) > 0}")
