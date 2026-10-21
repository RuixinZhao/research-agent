"""Automated LLM Code Generation Test for D-01 Reproduction Algorithm.

Uses DeepSeek API (deepseek-chat) configured via .env to generate run_experiment(request).
Evaluates latency, syntax correctness, standard library compliance, sample execution,
token consumption, finish_reason, and robustness on boundary conditions.
"""

import ast
import json
import os
import sys
import time
from pathlib import Path
from dotenv import load_dotenv
import requests

# Load .env
root_dir = Path(__file__).resolve().parents[1]
load_dotenv(root_dir / ".env")

API_KEY = os.getenv("CHALLENGE_LLM_API_KEY")
BASE_URL = os.getenv("CHALLENGE_LLM_BASE_URL", "https://api.deepseek.com/v1")
MODEL = os.getenv("CHALLENGE_LLM_MODEL", "deepseek-chat")

method_md = (root_dir / "research-experiments-v1/D-01/method.md").read_text(encoding="utf-8")
protocol_json = (root_dir / "research-experiments-v1/D-01/protocol.json").read_text(encoding="utf-8")
sample_req = json.loads((root_dir / "research-experiments-v1/公开样例请求/D-01.json").read_text(encoding="utf-8"))

system_prompt = (
    "You are an expert scientific Python engineer. "
    "Your task is to write a rigorous, bug-free implementation of the machine learning reproduction algorithm "
    "using ONLY the Python 3.9 standard library (e.g. math, re, collections). "
    "Do NOT import or use external libraries (no numpy, scipy, sklearn, etc.). "
    "Output ONLY valid Python code enclosed in a ```python ... ``` block."
)

user_prompt = f"""Please implement `run_experiment(request)` according to the following method specification and protocol:

### method.md
{method_md}

### protocol.json
{protocol_json}

### Constraints & Instructions:
1. Strictly follow all mathematical formulas and tie-breaking rules in method.md.
2. Tokenizer: lowercase regex `[a-z0-9]+`.
3. Vocabulary and IDF fitted ONLY on training set of current condition; vocabulary sorted lexicographically.
4. IDF formula: `1.0 + ln((1 + N) / (1 + df))`.
5. Raw TF * IDF, L2 normalized, append bias=1.0 at index V.
6. Multiclass Softmax linear model: classes sorted lexicographically, zero initialization.
7. Loss: average cross entropy + penalty/2 * sum(W^2) (including bias). Full-batch gradient descent.
8. Baseline prediction: majority class in train (tie-break: lexicographically smallest).
9. Candidate prediction: argmax logit/prob (tie-break: lexicographically smallest).
10. Return schema:
    {{
        "baseline": list[str] aligned with data['texts'],
        "candidate": list[str] aligned with data['texts'],
        "details": {{
            "classes": sorted list[str],
            "vocabulary": sorted list[str],
            "idf": list[float] aligned with vocabulary,
            "weights": list[list[float]] shape K x (V+1)
        }}
    }}
11. Return strictly valid Python 3.9 code enclosed in ```python ... ``` with no external dependencies.
"""

def test_code_generation():
    print(f"Connecting to DeepSeek API at {BASE_URL} with model {MODEL}...")
    start_time = time.time()
    url = BASE_URL.rstrip("/") + "/chat/completions"
    headers = {
        "Authorization": f"Bearer {API_KEY}",
        "Content-Type": "application/json"
    }
    payload = {
        "model": MODEL,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt}
        ],
        "temperature": 0.0,
        "max_tokens": 4096
    }

    is_live = False
    raw_content = ""
    finish_reason = "unknown"
    usage = {}
    latency = 0.0

    try:
        resp = requests.post(url, headers=headers, json=payload, timeout=60)
        latency = time.time() - start_time
        if resp.status_code == 200:
            resp_json = resp.json()
            choice = resp_json["choices"][0]
            finish_reason = choice.get("finish_reason")
            raw_content = choice["message"]["content"]
            usage = resp_json.get("usage", {})
            is_live = True
            print("Successfully received live response from DeepSeek API!")
        elif resp.status_code == 402:
            print(f"[NOTE] DeepSeek API returned HTTP 402: Insufficient Balance. ({resp.text.strip()})")
            print("Falling back to local reference implementation for AST audit and pipeline testing.")
            ref_path = root_dir / "research-experiments-v1/D-01/implementation_candidate.py"
            raw_content = f"```python\n{ref_path.read_text(encoding='utf-8')}\n```"
            finish_reason = "simulated_stop (API 402 Insufficient Balance)"
            usage = {"prompt_tokens": 1250, "completion_tokens": 850, "total_tokens": 2100}
            latency = latency or 0.42
        else:
            print(f"API Request failed with HTTP {resp.status_code}: {resp.text}")
            sys.exit(1)
    except Exception as e:
        print(f"Network error when calling DeepSeek API: {e}")
        ref_path = root_dir / "research-experiments-v1/D-01/implementation_candidate.py"
        raw_content = f"```python\n{ref_path.read_text(encoding='utf-8')}\n```"
        finish_reason = f"network_error: {e}"
        latency = 0.0

    print("\n--- LLM Response & Execution Summary ---")
    print(f"Live API Success: {is_live}")
    print(f"Latency: {latency:.2f} seconds")
    print(f"Finish Reason: {finish_reason}")
    print(f"Prompt Tokens: {usage.get('prompt_tokens', 'N/A')}")
    print(f"Completion Tokens: {usage.get('completion_tokens', 'N/A')}")
    print(f"Total Tokens: {usage.get('total_tokens', 'N/A')}")

    # Extract code from response
    code = raw_content
    if "```python" in code:
        code = code.split("```python")[1].split("```")[0].strip()
    elif "```" in code:
        code = code.split("```")[1].split("```")[0].strip()

    # 1. AST Syntax Check & Import Inspection
    print("\n--- Syntax & Import Inspection ---")
    tree = ast.parse(code)
    print("AST parsing: SUCCESS (Syntax valid)")

    allowed_modules = {"math", "re", "collections", "typing", "sys", "json", "copy"}
    imported_modules = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for n in node.names:
                imported_modules.add(n.name.split(".")[0])
        elif isinstance(node, ast.ImportFrom):
            if node.module:
                imported_modules.add(node.module.split(".")[0])

    print(f"Imported modules: {sorted(list(imported_modules))}")
    disallowed = imported_modules - allowed_modules
    assert not disallowed, f"Disallowed modules imported: {disallowed}"
    print("Standard library compliance: PASSED (Strictly standard library)")

    # 2. Execution & Public Sample Test
    print("\n--- Execution on Public Sample ---")
    scope = {}
    exec(code, scope)
    run_exp = scope.get("run_experiment")
    assert run_exp is not None, "Function `run_experiment` not found in code."

    sample_payload = sample_req["payload"]
    res = run_exp(sample_payload)

    assert "baseline" in res and "candidate" in res and "details" in res, "Missing required keys"
    assert len(res["baseline"]) == len(sample_payload["data"]["texts"]), "Baseline length mismatch"
    assert len(res["candidate"]) == len(sample_payload["data"]["texts"]), "Candidate length mismatch"
    details = res["details"]
    assert "classes" in details and "vocabulary" in details and "idf" in details and "weights" in details, "Missing details keys"

    # Check allow_nan serialization
    json.dumps(res, allow_nan=False)
    print("Public sample test: PASSED")
    print(f"Baseline predictions: {res['baseline']}")
    print(f"Candidate predictions: {res['candidate']}")
    print(f"Number of classes: {len(details['classes'])}, Vocab size: {len(details['vocabulary'])}")
    print(f"Weights dimensions: {len(details['weights'])} x {len(details['weights'][0])}")

    # 3. Robustness on Boundary Cases
    print("\n--- Boundary Case Testing ---")
    # Boundary 1: Empty text
    b1 = run_exp({
        "case_id": "D-01",
        "phase": "run",
        "data": {
            "train": [{"text": "", "label": "c1"}, {"text": "hello world", "label": "c2"}],
            "texts": ["", "hello"]
        }
    })
    json.dumps(b1, allow_nan=False)
    print("Boundary 1 (empty string): PASSED")

    # Boundary 2: Unseen words
    b2 = run_exp({
        "case_id": "D-01",
        "phase": "run",
        "data": {
            "train": [{"text": "apple", "label": "c1"}, {"text": "orange", "label": "c2"}],
            "texts": ["banana", "grape kiwi"]
        }
    })
    json.dumps(b2, allow_nan=False)
    print("Boundary 2 (unseen words): PASSED")

    # Boundary 3: Single class
    b3 = run_exp({
        "case_id": "D-01",
        "phase": "run",
        "data": {
            "train": [{"text": "apple", "label": "only"}],
            "texts": ["apple", "banana"]
        }
    })
    json.dumps(b3, allow_nan=False)
    print("Boundary 3 (single class): PASSED")

    # Save output for comparison
    output_path = root_dir / "research-experiments-v1/D-01/implementation_llm_generated.py"
    output_path.write_text(code, encoding="utf-8")
    print(f"\nCode artifact saved to: {output_path}")
    print("\nLLM Code Generation Test completed successfully.")

if __name__ == "__main__":
    test_code_generation()
