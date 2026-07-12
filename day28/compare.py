"""День 28 — сравнение ОБЛАКО (DeepSeek) vs ЛОКАЛЬ (qwen3.5-9b) на одном RAG.

Один и тот же конвейер дней 21–24 (поиск+реранк+контракт+проверка цитат+судья),
меняется только мотор генерации. Снимаем по трём осям задания: качество (тексты
рядом — судит человек), скорость (сек), стабильность (пустые ответы/ретраи/ошибки).
"""
import json
import sys
import time
from pathlib import Path

for d in ("day22", "day23", "day24"):
    sys.path.insert(0, str(Path(__file__).parent.parent / d))
import grounded as gr
import local_llm

QS = ["Как снизить риск СВДС во сне младенца?",
      "Насколько безопасен совместный сон с малышом в одной кровати?",
      "Что делать, если новорождённый плачет вечером несколько часов подряд?"]


def run_all(tag):
    rows = []
    for q in QS:
        t0 = time.time()
        try:
            r = gr.answer(q)
            err = None
        except Exception as e:
            r, err = None, f"{type(e).__name__}: {str(e)[:80]}"
        dt = time.time() - t0
        rows.append({"q": q, "sec": round(dt, 1), "err": err,
                     "status": (r or {}).get("status") or ("abstain" if (r or {}).get("abstained") else "?"),
                     "answer": (r or {}).get("answer", ""),
                     "quotes": len((r or {}).get("quotes", []) or []),
                     "verified": (r or {}).get("verified_n", 0),
                     "faith": ((r or {}).get("faithfulness") or {}).get("verdict")})
        print(f"[{tag}] {q[:40]}… {dt:.1f}с status={rows[-1]['status']}", flush=True)
    return rows


print(f"ОБЛАКО провайдер: {gr.PROVIDER} / {gr.MODEL}", flush=True)
cloud = run_all("cloud")

local_llm.activate()
print(f"\nЛОКАЛЬ провайдер: {gr.PROVIDER} / {gr.MODEL}", flush=True)
local = run_all("local")

out = {"cloud": {"provider": "deepseek-chat", "rows": cloud},
       "local": {"provider": "qwen3.5-9b-mlx", "rows": local}}
(Path(__file__).parent / "compare.json").write_text(json.dumps(out, ensure_ascii=False, indent=2))
print("\n=== СВЕДЕНО → compare.json ===")
for i, q in enumerate(QS):
    c, l = cloud[i], local[i]
    print(f"\nВОПРОС: {q}")
    print(f"  облако DeepSeek: {c['sec']}с | {c['status']} | цитат {c['quotes']}/{c['verified']} | судья {c['faith']}")
    print(f"  локаль qwen9b  : {l['sec']}с | {l['status']} | цитат {l['quotes']}/{l['verified']} | судья {l['faith']}")
