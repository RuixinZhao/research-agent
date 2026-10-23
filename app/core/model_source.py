"""Extract a complete model response without rewriting its Python source.

This is an offline format check, not a platform source credential.
Enhanced with strict Python 3.9 AST verification and self-healing support.
"""
import argparse
import ast
import hashlib
import json
from pathlib import Path
import re


def _check_python39_ast(tree):
    """
    针对 Python 3.9 环境做深度语法断言：
    1. 阻断 match-case (Pattern Matching, Python 3.10+);
    2. 阻断函数签名与变量声明中的 '|' 联合类型注解 (PEP 604, Python 3.10+)。
    """
    for node in ast.walk(tree):
        if hasattr(ast, "Match") and isinstance(node, ast.Match):
            lineno = getattr(node, "lineno", 1)
            raise SyntaxError(
                "Pattern matching (match-case) is not supported in Python 3.9; use if-elif-else statements instead",
                (None, lineno, getattr(node, "col_offset", 0), None)
            )
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            annotations = []
            if node.returns:
                annotations.append(node.returns)
            for arg in node.args.args + node.args.kwonlyargs + [node.args.vararg, node.args.kwarg]:
                if arg and arg.annotation:
                    annotations.append(arg.annotation)
            for ann in annotations:
                for sub in ast.walk(ann):
                    if isinstance(sub, ast.BinOp) and isinstance(sub.op, ast.BitOr):
                        lineno = getattr(sub, "lineno", getattr(node, "lineno", 1))
                        raise SyntaxError(
                            "Union type syntax (X | Y) is not supported in Python 3.9; use typing.Union or omit type annotations",
                            (None, lineno, getattr(sub, "col_offset", 0), None)
                        )
        if isinstance(node, ast.AnnAssign):
            for sub in ast.walk(node.annotation):
                if isinstance(sub, ast.BinOp) and isinstance(sub.op, ast.BitOr):
                    lineno = getattr(sub, "lineno", getattr(node, "lineno", 1))
                    raise SyntaxError(
                        "Union type syntax (X | Y) is not supported in Python 3.9; use typing.Union or omit type annotations",
                        (None, lineno, getattr(sub, "col_offset", 0), None)
                    )


def _normalize(source):
    if not isinstance(source, str) or not 0 < len(source.encode('utf-8')) <= 65536:
        raise ValueError('Source must be 1..65536 UTF-8 bytes')
    source = source.replace('\r\n', '\n').replace('\r', '\n').rstrip('\n') + '\n'
    tree = ast.parse(source, feature_version=(3, 9))
    _check_python39_ast(tree)
    if not any(isinstance(n, ast.FunctionDef) and n.name == 'run_experiment' for n in tree.body):
        raise ValueError('Missing run_experiment(request)')
    return source


def extract_source(response):
    if not isinstance(response, dict):
        raise ValueError('Expected a complete chat/completions JSON response')
    found = set()
    syntax_errors = []
    for choice in response.get('choices', []):
        if not isinstance(choice, dict) or choice.get('finish_reason') != 'stop':
            continue
        message = choice.get('message', {})
        if message.get('role') != 'assistant' or not isinstance(message.get('content'), str):
            continue
        content = message['content']
        candidates = [content]
        candidates.extend(re.findall(r'^```(?:python|py)?[ \t]*\r?\n(.*?)^```[ \t]*$',
                                     content, re.MULTILINE | re.DOTALL))
        for candidate in candidates:
            try:
                found.add(_normalize(candidate))
            except SyntaxError as e:
                syntax_errors.append(e)
            except (ValueError, RecursionError):
                pass
    if len(found) != 1:
        if not found and syntax_errors:
            last_err = syntax_errors[-1]
            lineno = getattr(last_err, "lineno", None)
            msg = getattr(last_err, "msg", str(last_err))
            loc = f"line {lineno}: " if lineno is not None else ""
            raise SyntaxError(f"{loc}{msg}")
        raise ValueError('Expected exactly one complete Python implementation with finish_reason=stop; request a full new response')
    return found.pop()


def save_source(response, destination):
    source = extract_source(response)
    destination = Path(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_bytes(source.encode('utf-8'))
    return hashlib.sha256(source.encode('utf-8')).hexdigest()


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--response', required=True, help='Saved complete chat/completions JSON, not only message.content')
    parser.add_argument('--output', required=True)
    args = parser.parse_args()
    response = json.loads(Path(args.response).read_text(encoding='utf-8-sig'))
    print(json.dumps({'source_sha256': save_source(response, args.output),
                      'offline_format_only': True, 'platform_credential_issued': False}))
