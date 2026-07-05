"""
День 25 — ТРЕЙСЕР полного конвейера RAG-чата (снимает РЕАЛЬНЫЕ числа для объяснялки).

Гоняет один ход диалога ОТ и ДО через настоящий код дней 21–24 + два новых звена
Дня 25 (контекстуализация follow-up с историей, обновление памяти задачи) и
дампит каждый промежуточный шаг в trace.json. Никаких выдуманных чисел —
объяснялка (explain_day25.html) читает ровно то, что тут снято.

Запуск: day21/.venv/bin/python trace_pipeline.py
"""
import json
import sys
import time
from pathlib import Path

BASE = Path(__file__).parent
sys.path.insert(0, str(BASE.parent / "day22"))
sys.path.insert(0, str(BASE.parent / "day23"))
sys.path.insert(0, str(BASE.parent / "day24"))

import rag_core            # noqa: E402  День 22: retrieve + эмбеддер
import rerank as rr        # noqa: E402  День 23: cross-encoder
import grounded as gr      # noqa: E402  День 24: контракт, проверка цитат, судья


def log(*a):
    print(*a, flush=True)


# ---------- вход: диалог ----------
HISTORY = [
    {"role": "user", "content": "Малыш плачет каждый вечер и не может уснуть, это нормально?"},
    {"role": "assistant", "content": "Да, у новорождённых часто бывает вечерний период беспокойства."},
]
FOLLOWUP = "А сколько это обычно длится? Ему три недели."

TASK_STATE_BEFORE = {
    "goal": "понять вечерний плач малыша и как его пережить",
    "clarified": [],
    "constraints": [],
}

THRESHOLD = 0.54
CANDIDATES = 12
FINAL_K = 5


# ---------- Звено Дня 25 #1: контекстуализация follow-up с историей ----------
CONDENSE_SYS = (
    "Ты переписываешь вопрос пользователя в самодостаточный поисковый запрос.\n"
    "Дана история диалога и последний вопрос с местоимениями/отсылками ('он', 'перед этим').\n"
    "Разверни отсылки по истории и верни ОДНУ строку — полный самостоятельный вопрос "
    "на русском, без пояснений."
)


def condense(history, followup) -> str:
    hist = "\n".join(f"{m['role']}: {m['content']}" for m in history)
    raw = gr._chat(
        [{"role": "system", "content": CONDENSE_SYS},
         {"role": "user", "content": f"ИСТОРИЯ:\n{hist}\n\nПОСЛЕДНИЙ ВОПРОС: {followup}\n\nСАМОДОСТАТОЧНЫЙ ЗАПРОС:"}],
        json_mode=False, max_tokens=120)
    return raw.strip().splitlines()[0].strip().strip('"') if raw.strip() else followup


# ---------- Звено Дня 25 #2: обновление памяти задачи (точечная дельта) ----------
STATE_SYS = (
    "Ты ведёшь карточку задачи диалога. Дана текущая карточка и новый ход.\n"
    "Верни ТОЛЬКО JSON с ДЕЛЬТОЙ (что добавить/уточнить), пустые поля опускай:\n"
    '{"goal": "<новая формулировка цели, если уточнилась>", '
    '"clarified_add": ["<новый факт, уточнённый пользователем>"], '
    '"constraints_add": ["<новое ограничение/термин>"]}\n'
    "Не выдумывай — бери только то, что реально прозвучало в ходе.\n"
    "НЕ повторяй то, что УЖЕ есть в карточке — добавляй только НОВОЕ."
)


def _norm_item(s: str) -> str:
    return " ".join(str(s).lower().split())


def _merge(existing: list, add: list) -> list:
    """Дедуп: добавляем только то, чего ещё нет (грабля трейса — модель повторяла факт)."""
    seen = {_norm_item(x) for x in existing}
    out = list(existing)
    for x in add or []:
        if _norm_item(x) not in seen:
            seen.add(_norm_item(x))
            out.append(x)
    return out


def update_state(state, user_msg, standalone) -> tuple[dict, dict]:
    payload = (f"КАРТОЧКА СЕЙЧАС:\n{json.dumps(state, ensure_ascii=False)}\n\n"
               f"НОВЫЙ ХОД — вопрос пользователя: {user_msg}\n"
               f"(в самодостаточном виде: {standalone})")
    delta = gr._parse_json(gr._chat(
        [{"role": "system", "content": STATE_SYS},
         {"role": "user", "content": payload}], max_tokens=200)) or {}
    new = {"goal": delta.get("goal") or state["goal"],
           "clarified": _merge(state["clarified"], delta.get("clarified_add")),
           "constraints": _merge(state["constraints"], delta.get("constraints_add"))}
    return new, delta


def main():
    t0 = time.time()
    trace = {"provider": gr.PROVIDER, "model": gr.MODEL,
             "history": HISTORY, "followup": FOLLOWUP,
             "task_state_before": TASK_STATE_BEFORE, "threshold": THRESHOLD}

    # --- Этап 1: контекстуализация ---
    log("[1/10] контекстуализация follow-up ...")
    standalone = condense(HISTORY, FOLLOWUP)
    trace["standalone"] = standalone
    log("      было :", FOLLOWUP)
    log("      стало:", standalone)

    # --- Этап 2: эмбеддинг (срез вектора) ---
    log("[2/10] эмбеддинг запроса (bge-m3) ...")
    emb = rag_core._embedder()
    qvec = emb.encode([standalone], normalize_embeddings=True)[0]
    norm = float((qvec ** 2).sum() ** 0.5)
    trace["embedding"] = {"dim": int(qvec.shape[0]), "norm": round(norm, 4),
                          "head": [round(float(x), 4) for x in qvec[:14]]}
    log(f"      dim={qvec.shape[0]} norm={norm:.3f} head={trace['embedding']['head'][:5]}...")

    # --- Этап 3: поиск. КОНТРАСТ сырой follow-up vs переписанный ---
    log("[3/10] поиск: контраст сырого follow-up и переписанного ...")
    raw_hits = rag_core.retrieve(FOLLOWUP, k=6)
    good_hits = rag_core.retrieve(standalone, k=CANDIDATES)
    trace["retrieve_raw"] = [{"section": c["section"], "cos": c["cos"],
                              "text": c["text"][:180]} for c in raw_hits]
    trace["retrieve_good"] = [{"section": c["section"], "cos": c["cos"],
                               "text": c["text"][:180]} for c in good_hits]
    log(f"      сырой  топ-раздел: {raw_hits[0]['section']} (cos={raw_hits[0]['cos']})")
    log(f"      переп. топ-раздел: {good_hits[0]['section']} (cos={good_hits[0]['cos']})")

    # --- Этап 4: реранк (сырой логит → sigmoid) ---
    log("[4/10] реранк кандидатов (cross-encoder) ...")
    pairs = [[standalone, c["text"]] for c in good_hits]
    raw_logits = rr._model().predict(pairs)
    graded = rr.rerank_full(standalone, good_hits, top_k=FINAL_K, threshold=THRESHOLD)
    # приклеим сырой логит к каждому (по тексту)
    logit_by_text = {c["text"]: float(r) for c, r in zip(good_hits, raw_logits)}
    trace["reranked"] = [{
        "rank": c["rank"], "section": c["section"], "cos": c["cos"],
        "logit": round(logit_by_text.get(c["text"], 0.0), 3), "score": c["score"],
        "kept": c["kept"], "text": c["text"][:180]} for c in graded]
    kept = [c for c in graded if c["kept"]]
    log(f"      прошло порог {THRESHOLD}: {len(kept)} из {len(graded)}")
    for c in graded[:6]:
        mark = "KEEP" if c["kept"] else "drop"
        log(f"      [{mark}] score={c['score']:.3f} logit={logit_by_text.get(c['text'],0):+.2f} {c['section'][:40]}")

    # --- Этап 5+6: порог + контекст ---
    trace["kept_n"] = len(kept)
    trace["context_preview"] = gr._context(kept)[:1200]

    if not kept:
        trace["abstained"] = True
        log("      abstain: ничего не прошло порог")
    else:
        trace["abstained"] = False
        # --- Этап 7: контракт ---
        log("[7/10] контракт {answer, sources, quotes} ...")
        c = gr.ask_contract(standalone, kept)
        trace["contract"] = {"answer": c["answer"], "sources": c["sources"],
                             "quotes": c["quotes"], "parse_ok": c["parse_ok"]}
        log("      answer:", c["answer"][:120])
        log(f"      quotes: {len(c['quotes'])}, sources: {len(c['sources'])}")

        # --- Этап 8: проверка цитат кодом ---
        log("[8/10] проверка цитат кодом (substring→fuzzy) ...")
        checked = gr.verify_quotes(c["quotes"], kept)
        trace["checked"] = checked
        for x in checked:
            log(f"      [{ 'ok' if x['matched'] else 'NO'}] {x['method']} {x['score']}% :: {x['quote'][:70]}")

        # --- Этап 9: судья ---
        log("[9/10] судья faithfulness ...")
        verified = [x["quote"] for x in checked if x["matched"]]
        trace["faithfulness"] = gr.faithfulness_judge(c["answer"], verified) if verified else \
            {"verdict": "unsupported", "reason": "нет подтверждённых цитат"}
        log("      вердикт:", trace["faithfulness"]["verdict"])

    # --- Этап 10: обновление памяти задачи ---
    log("[10/10] обновление карточки задачи ...")
    new_state, delta = update_state(TASK_STATE_BEFORE, FOLLOWUP, standalone)
    trace["task_state_delta"] = delta
    trace["task_state_after"] = new_state
    log("      дельта:", json.dumps(delta, ensure_ascii=False))

    trace["elapsed_s"] = round(time.time() - t0, 1)
    (BASE / "trace.json").write_text(json.dumps(trace, ensure_ascii=False, indent=2))
    log(f"\nГОТОВО за {trace['elapsed_s']}с → trace.json")


if __name__ == "__main__":
    main()
