"""
День 23 — query rewrite: чиним сам вопрос ДО поиска.

Короткий/кривой вопрос даёт размытую координату смысла → поиск мажет. Два приёма:
  - expand  — переписать в развёрнутый поисковый вид (одна строка);
  - multi   — размножить на N парафраз под разными углами (ищем по каждой, сводим).

Зовём ту же модель и тот же клиент, что День 22 (rag_core._ask) — не плодим второй.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "day22"))
from rag_core import _ask  # noqa: E402  (переиспользуем вызов модели Дня 22)

EXPAND_SYS = (
    "Ты помогаешь искать по базе знаний. Перепиши вопрос пользователя в развёрнутый "
    "поисковый запрос: добавь ключевые слова темы, убери разговорность. "
    "Верни ОДНУ строку, без пояснений."
)
MULTI_SYS = (
    "Ты помогаешь искать по базе знаний. Сгенерируй {n} разных переформулировок вопроса "
    "под разными углами (синонимы, аспекты темы). По одной на строку, без нумерации, "
    "без пояснений."
)


def rewrite_expand(question: str) -> str:
    """Кривой вопрос → одна развёрнутая поисковая строка."""
    out = _ask([{"role": "system", "content": EXPAND_SYS},
                {"role": "user", "content": question}], max_tokens=80)
    line = out.strip().splitlines()[0] if out.strip() else question
    return line.strip().strip('"')


def rewrite_multi(question: str, n: int = 3) -> list[str]:
    """Вопрос → N парафраз (плюс сам оригинал первым, чтобы не потерять)."""
    out = _ask([{"role": "system", "content": MULTI_SYS.format(n=n)},
                {"role": "user", "content": question}], max_tokens=160)
    variants = [ln.strip(" -•\t\"") for ln in out.splitlines() if ln.strip()]
    seen, res = set(), [question]
    for v in variants:
        key = v.lower()
        if v and key not in seen and key != question.lower():
            seen.add(key)
            res.append(v)
    return res[: n + 1]
