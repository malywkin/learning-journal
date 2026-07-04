"""
День 23 — улучшенный RAG: pipeline поверх ядра Дня 22.

  вопрос ─(опц. rewrite)→ поиск top-N ─(опц. rerank+порог)→ top-K ─→ ответ модели

Даём две сборки на один вопрос, чтобы задание «сравните без фильтра / с фильтром»
считалось живьём:
  baseline  — как День 22: берём top-K прямо из поиска (по теме);
  improved  — rewrite → поиск top-N → rerank → порог/top-K (по ответу).

Ядро Дня 22 (retrieve/build_context/_ask/validate_citations) переиспользуем как есть.
"""
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "day22"))
from rag_core import (  # noqa: E402
    GEN_MODEL, SYSTEM, _openrouter, build_context, retrieve, validate_citations,
)
from rerank import rerank_full  # noqa: E402
from rewrite import rewrite_multi  # noqa: E402

CANDIDATES = 20   # top-N: сколько поиск отдаёт реранкеру (широко зачерпнуть)
FINAL_K = 5       # top-K: сколько уходит модели после фильтра (узко подать)
THRESHOLD = 0.30  # порог по оценке реранкера (0..1); подбираем на golden set
ANSWER_TOKENS = 900   # потолок ответа: gpt-oss — reasoning-модель, ей нужен запас
                      # (иначе всё съедает молчаливое «размышление» → пустой content)
RUNS_LOG = Path(__file__).parent / "runs.jsonl"


def _ask_diag(messages, max_tokens=ANSWER_TOKENS, tries=6) -> dict:
    """Вызов модели с диагностикой: ловим finish_reason и usage, чтобы видеть,
    почему ответ пустой (reasoning съел бюджет → finish=length, content='')."""
    last = {"content": "", "finish": None, "usage": None, "error": None}
    for _ in range(tries):
        try:
            r = _openrouter().chat.completions.create(
                model=GEN_MODEL, temperature=0, max_tokens=max_tokens,
                messages=messages,
                extra_body={"reasoning": {"effort": "low"}})  # меньше «думать» — больше писать
            ch = r.choices[0]
            last["finish"] = ch.finish_reason
            last["usage"] = r.usage.model_dump() if r.usage else None
            content = (ch.message.content or "").strip()
            if content:
                last["content"] = content
                last["error"] = None      # был удачный повтор — не тащим прошлую 429
                return last
            last["error"] = "empty_content"
        except Exception as e:
            last["error"] = f"{type(e).__name__}: {e}"
        time.sleep(4)
    return last


def _dedup(chunks: list[dict]) -> list[dict]:
    seen, out = set(), []
    for c in chunks:
        key = c["text"][:60]
        if key not in seen:
            seen.add(key)
            out.append(c)
    return out


def _generate(question: str, chunks: list[dict]) -> dict:
    """Куски → augmented-промпт → ответ модели со ссылками (как День 22)."""
    context = build_context(chunks)
    user = f"ИСТОЧНИКИ:\n{context}\n\nВОПРОС: {question}\nОТВЕТ:"
    if not chunks:
        return {"answer": "В источниках нет.", "abstained": True,
                "citations": {"cited": [], "valid": [], "invalid": []},
                "prompt_preview": user, "diag": {"error": "no_chunks"}}
    d = _ask_diag([{"role": "system", "content": SYSTEM},
                   {"role": "user", "content": user}])
    ans = d["content"] or f"(модель не дала ответ: finish={d['finish']}, err={d['error']})"
    return {
        "answer": ans,
        "abstained": "в источниках нет" in ans.lower(),
        "citations": validate_citations(ans, len(chunks)),
        "prompt_preview": user,
        "diag": {k: d[k] for k in ("finish", "usage", "error")},
    }


def search_candidates(question: str, use_rewrite: bool = False,
                      n_variants: int = 3) -> tuple[list[dict], list[str]]:
    """Поиск кандидатов. С rewrite — ищем по нескольким парафразам и сводим."""
    if not use_rewrite:
        return retrieve(question, k=CANDIDATES), [question]
    queries = rewrite_multi(question, n=n_variants)
    pool: list[dict] = []
    for q in queries:
        pool.extend(retrieve(q, k=CANDIDATES))
    pool.sort(key=lambda c: c["cos"], reverse=True)     # лучшие по близости вперёд
    return _dedup(pool)[:CANDIDATES], queries


def run(question: str, use_rerank: bool, use_rewrite: bool = False,
        top_k: int = FINAL_K, threshold: float = THRESHOLD) -> dict:
    """Один прогон pipeline. Возвращаем и кандидатов (со всеми оценками), и ответ."""
    candidates, queries = search_candidates(question, use_rewrite=use_rewrite)
    if use_rerank:
        graded = rerank_full(question, candidates, top_k=top_k, threshold=threshold)
        final = [c for c in graded if c["kept"]]
    else:
        graded = candidates[:top_k]                     # baseline: топ поиска как есть
        final = graded
    gen = _generate(question, final)
    result = {
        "question": question,
        "queries": queries,
        "use_rerank": use_rerank,
        "use_rewrite": use_rewrite,
        "candidates_n": len(candidates),
        "graded": graded,       # витрине: показать оценки и что отвалилось
        "final": final,
        **gen,
    }
    _log_run(result)
    return result


def _log_run(r: dict) -> None:
    """Пишем прогон в runs.jsonl: вопрос, куски с оценками, ответ, диагностика модели."""
    rec = {
        "t": round(time.time(), 1),
        "question": r["question"],
        "mode": ("rerank" if r["use_rerank"] else "baseline")
        + ("+rewrite" if r["use_rewrite"] else ""),
        "queries": r["queries"],
        "candidates_n": r["candidates_n"],
        "final_chunks": [
            {"section": c.get("section", ""), "cos": c.get("cos"),
             "score": c.get("score"), "text": c["text"][:90]}
            for c in r["final"]
        ],
        "answer": r["answer"],
        "diag": r.get("diag"),
    }
    with open(RUNS_LOG, "a", encoding="utf-8") as f:
        f.write(json.dumps(rec, ensure_ascii=False) + "\n")


def compare(question: str, use_rewrite: bool = False,
            top_k: int = FINAL_K, threshold: float = THRESHOLD) -> dict:
    """Две сборки на один вопрос: baseline (День 22) и improved (реранк+порог)."""
    base = run(question, use_rerank=False, use_rewrite=False, top_k=top_k)
    impr = run(question, use_rerank=True, use_rewrite=use_rewrite,
               top_k=top_k, threshold=threshold)
    return {"question": question, "baseline": base, "improved": impr}
