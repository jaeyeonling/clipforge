"""엔진이 화면에 내보내는 문구 규칙: 오류의 원인·할 일, 진행 메시지, 경고는 '~해요'체로 쓴다.
화면의 '원인과 할 일' 카드와 진행 줄은 엔진 문자열을 그대로 보여주므로 여기서 지킨다. 독스트링·주석은 대상이 아니다."""

import ast
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
FORMAL = re.compile(r"[가-힣](?:습니다|니다)(?=[\s.!?\"')\]]|$)")
# 실제 영상 제목을 예로 든 곳처럼, 사용자 문구가 아닌 데이터 문자열
ALLOW = {"clipforge/weaklabel.py"}


def _strings(tree: ast.AST):
    docstrings = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Module | ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef) and node.body:
            first = node.body[0]
            if isinstance(first, ast.Expr) and isinstance(first.value, ast.Constant):
                docstrings.add(id(first.value))
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, str) and id(node) not in docstrings:
            yield node.lineno, node.value


def test_engine_user_facing_strings_use_friendly_register():
    bad = []
    for p in sorted((ROOT / "clipforge").rglob("*.py")):
        rel = p.relative_to(ROOT).as_posix()
        if rel in ALLOW:
            continue
        for line, text in _strings(ast.parse(p.read_text(encoding="utf-8"))):
            if FORMAL.search(text):
                bad.append(f"{rel}:{line}: {text[:60]}")
    assert bad == [], "딱딱한 '~습니다'체 대신 '~해요'체로:\n" + "\n".join(bad)
