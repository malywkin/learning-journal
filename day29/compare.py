"""День 29 — замер «до/после» оптимизации локальной LLM под наш RAG-бот по родительству.

Держим ПОИСК постоянным (тот же retrieve+rerank+порог дней 21–23), крутим ТОЛЬКО
ручки генерации — так замер честный. Три конфигурации показывают весь путь:

  raw     — сырая, до всякой оптимизации: думание ВКЛ, temp 0, старый жёсткий промпт.
            Медленно (лишние токены на внутренний монолог) и сухо. Baseline.
  current — что у бота СЕЙЧАС: думание погашено префиллом, temp 0, старый промпт.
            Быстро (скорость уже отвоёвана на RAG-неделе), но «калькулятор».
  new     — сегодняшняя: думание погашено, temp 0.3 + min_p 0.05, ПЕРЕПИСАННЫЙ промпт
            (рассуждать внутри источников, запрещать только выдумку фактов). Быстро И живо.

raw→current = отвоёванная СКОРОСТЬ (думание прочь). current→new = сегодняшнее КАЧЕСТВО.

Методика (как велит фронтир): прогрев выбрасываем; скорость = tok/s из usage; «ресурс»
модели (RAM) одинаков во всех конфигах — та же модель, — поэтому ресурс меряем
лишними ТОКЕНАМИ (работа впустую), а RAM отмечаем как константу.
"""
import json
import sys
import time
from pathlib import Path

BASE = Path(__file__).parent
sys.path.insert(0, str(BASE.parent / "day22"))
sys.path.insert(0, str(BASE.parent / "day24"))

import grounded as gr  # noqa: E402
from questions import GOLDEN  # noqa: E402
from rag_core import retrieve  # noqa: E402
from rerank import rerank_full  # noqa: E402
from openai import OpenAI  # noqa: E402

MODEL = "qwen3.5-9b-mlx"
client = OpenAI(base_url="http://127.0.0.1:1234/v1", api_key="lm-studio", timeout=240)
NOTHINK = {"role": "assistant", "content": "<think></think>"}

# --- Старый промпт бота (жёсткий, «калькулятор») — берём из дня 24 без изменений ---
OLD_TEMPLATE = gr.CONTRACT_TEMPLATE

# --- Новый промпт: тот же JSON-контракт, но намордник снят с речи, оставлен на фактах ---
NEW_TEMPLATE = (
    "Ты — тёплый, внимательный ассистент по родительству. Отвечай, опираясь на источники ниже.\n"
    "Верни ТОЛЬКО JSON-объект (без markdown) ровно такой формы:\n"
    '{"answer": "<ответ по-русски>", '
    '"sources": [{"chunk_id": <номер>, "section": "<раздел>"}], '
    '"quotes": ["<ДОСЛОВНЫЙ фрагмент из источника>"]}\n'
    "Как отвечать:\n"
    "1. Опирайся на источники. В ИХ ПРЕДЕЛАХ можешь рассуждать, связывать факты и "
    "объяснять простым, живым языком — так, чтобы уставшему родителю было понятно и "
    "по-человечески, а не сухой строкой.\n"
    "2. НЕ добавляй фактов, которых нет в источниках. Рассуждать внутри источников — можно, "
    "выдумывать вне их — нельзя.\n"
    "3. sources — только куски, на которые реально опёрся. quotes — дословные фрагменты "
    "из текста источников.\n"
    "4. Если ответа в источниках нет — верни answer «В источниках нет.», sources и quotes "
    "пустыми. Не придумывай.\n"
)

CONFIGS = {
    "raw":     dict(template=OLD_TEMPLATE, temp=0.0, min_p=None, gag=False),
    "current": dict(template=OLD_TEMPLATE, temp=0.0, min_p=None, gag=True),
    "new":     dict(template=NEW_TEMPLATE, temp=0.3, min_p=0.05, gag=True),
}


def _gen(question: str, chunks: list[dict], cfg: dict) -> dict:
    """Один вызов генерации на ГОТОВЫХ кусках. Возвращает ответ + метрики (warm-время,
    токены выхода, tok/s). gag=True → префилл <think></think> (гасим думание)."""
    user = f"ИСТОЧНИКИ:\n{gr._context(chunks)}\n\nВОПРОС: {question}"
    msgs = [{"role": "system", "content": cfg["template"]},
            {"role": "user", "content": user}]
    if cfg["gag"]:
        msgs = msgs + [NOTHINK]
    extra = {"min_p": cfg["min_p"]} if cfg["min_p"] is not None else {}
    t = time.time()
    r = client.chat.completions.create(
        model=MODEL, temperature=cfg["temp"], max_tokens=700, messages=msgs,
        extra_body=extra)
    dt = time.time() - t
    raw = (r.choices[0].message.content or "").strip()
    obj = gr._parse_json(raw) or {}
    out_tok = r.usage.completion_tokens
    return {
        "answer": str(obj.get("answer", raw)).strip(),
        "quotes": [q for q in (obj.get("quotes") or []) if isinstance(q, str) and q.strip()],
        "parse_ok": bool(obj),
        "sec": round(dt, 1),
        "out_tok": out_tok,
        "tok_s": round(out_tok / dt, 1) if dt > 0 else 0,
        "raw_len": len(raw),
    }


def warmup():
    print("прогрев (выбрасываем)...", flush=True)
    client.chat.completions.create(
        model=MODEL, temperature=0, max_tokens=20,
        messages=[{"role": "user", "content": "привет"}, NOTHINK])


def main():
    warmup()
    results = []
    for i, item in enumerate(GOLDEN, 1):
        q = item["q"]
        cand = retrieve(q, k=gr.CANDIDATES)
        graded = rerank_full(q, cand, top_k=gr.FINAL_K, threshold=gr.THRESHOLD)
        kept = [c for c in graded if c.get("kept")]
        top = round(graded[0]["score"], 3) if graded else 0.0
        row = {"q": q, "in_base": item["in_base"], "top_score": top,
               "kept_n": len(kept), "runs": {}}

        if not kept:
            # порог-отказ на ВХОДЕ: генерации нет, оба конфига честно молчат (предохранитель цел)
            row["gate_abstained"] = True
            print(f"[{i}/10] ОТКАЗ на пороге (top={top}) — {q[:40]}", flush=True)
            results.append(row)
            continue

        # current и new — на всех вопросах в базе (оба с гашением, быстрые)
        for name in ("current", "new"):
            row["runs"][name] = _gen(q, kept, CONFIGS[name])
            r = row["runs"][name]
            print(f"[{i}/10] {name:8} {r['sec']:>5}с  {r['out_tok']:>4}tok  "
                  f"{r['tok_s']}tok/s  «{r['answer'][:55]}»", flush=True)

        # raw (думание ВКЛ) — только на первых 3 в базе, чтобы показать цену думания
        if i <= 3:
            row["runs"]["raw"] = _gen(q, kept, CONFIGS["raw"])
            r = row["runs"]["raw"]
            print(f"[{i}/10] {'raw':8} {r['sec']:>5}с  {r['out_tok']:>4}tok  "
                  f"(думание ВКЛ) «{r['answer'][:45]}»", flush=True)

        results.append(row)

    out = BASE / "results.json"
    out.write_text(json.dumps(results, ensure_ascii=False, indent=2))
    print(f"\nГОТОВО → {out}", flush=True)


if __name__ == "__main__":
    main()
