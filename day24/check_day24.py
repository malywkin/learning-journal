"""
Прогон Дня 24 живьём: калибровка порога + проверка на 10 вопросах + пара полных ответов.
Запуск: day21/.venv/bin/python day24/check_day24.py [--smoke]
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "day22"))
from questions import GOLDEN  # noqa: E402  (golden set Дня 22 — переиспользуем)

import grounded as g  # noqa: E402
from rag_core import retrieve  # noqa: E402
from rerank import rerank_full  # noqa: E402


def calibrate():
    """Те самые «10 строчек»: по каждому вопросу — top score реранкера + метка свой/ловушка.
    Смотрим, есть ли яма между группами, и куда поставить порог."""
    print("\n=== КАЛИБРОВКА ПОРОГА (top score реранкера по каждому из 10) ===")
    rows = []
    for item in GOLDEN:
        cand = retrieve(item["q"], k=g.CANDIDATES)
        graded = rerank_full(item["q"], cand, top_k=g.FINAL_K, threshold=0.0)
        top = graded[0]["score"] if graded else 0.0
        rows.append((top, item["in_base"], item["q"]))
    ins = sorted((t for t, b, _ in rows if b), reverse=True)
    traps = sorted((t for t, b, _ in rows if not b), reverse=True)
    for top, in_base, q in sorted(rows, reverse=True):
        tag = "свой   " if in_base else "ЛОВУШКА"
        print(f"  {top:5.3f}  {tag}  {q[:60]}")
    print(f"\n  свои:    min={min(ins):.3f}  max={max(ins):.3f}")
    print(f"  ловушки: min={min(traps):.3f}  max={max(traps):.3f}")
    gap_lo, gap_hi = max(traps), min(ins)
    if gap_hi > gap_lo:
        print(f"  ЯМА между {gap_lo:.3f}(ловушка) и {gap_hi:.3f}(свой) → порог ≈ {(gap_lo + gap_hi) / 2:.3f}")
    else:
        print(f"  ямы нет (перехлёст): ловушки до {gap_lo:.3f}, свои от {gap_hi:.3f}")


def show(res: dict):
    print(f"\n  вопрос: {res['question']}")
    print(f"  провайдер: {res.get('provider')}/{res.get('model')}")
    print(f"  top_score={res['top_score']:.3f}  abstained={res['abstained']}"
          f"  status={res.get('status')}")
    print(f"  ОТВЕТ: {res['answer'][:200]}")
    if res.get("checked"):
        print("  цитаты (проверка кодом):")
        for x in res["checked"]:
            mark = "OK " if x["matched"] else "БРАК"
            print(f"    [{mark} {x['method']} {x['score']}] chunk#{x['chunk_id']}: {x['quote'][:70]}")
    if res.get("faithfulness"):
        f = res["faithfulness"]
        print(f"  faithfulness(судья): {f['verdict']} — {f['reason'][:100]}")


def eval_ten():
    """Проверка на 10 вопросах: есть источник / есть цитата / цитата подтверждена /
    ловушки честно отбиты."""
    print("\n=== ПРОВЕРКА НА 10 ВОПРОСАХ ===")
    ok_ans = ok_trap = 0
    for item in GOLDEN:
        r = g.answer(item["q"])
        if item["in_base"]:
            verified = r.get("verified_n", 0)
            faith = (r.get("faithfulness") or {}).get("verdict", "—")
            good = (not r["abstained"]) and verified > 0
            ok_ans += good
            print(f"  [{'OK ' if good else 'MISS'}] свой   | цитат✓={verified} "
                  f"faith={faith} | {item['q'][:45]}")
        else:
            abst = r["abstained"] or r.get("status") in ("model_abstained", "unverifiable")
            ok_trap += abst
            print(f"  [{'OK ' if abst else 'FAIL'}] ловушка| отказ={abst} | {item['q'][:45]}")
    print(f"\n  своих отвечено с подтв. цитатой: {ok_ans}/7")
    print(f"  ловушек честно отбито:           {ok_trap}/3")


if __name__ == "__main__":
    smoke = "--smoke" in sys.argv
    print(f"провайдер: {g.PROVIDER} / {g.MODEL}")
    if smoke:
        show(g.answer("В какой позе безопаснее всего укладывать младенца спать?"))
        show(g.answer("Какая сейчас ставка по ипотеке в России?"))
        sys.exit(0)
    calibrate()
    print("\n=== ДВА ПОЛНЫХ ОТВЕТА ===")
    show(g.answer("В какой позе безопаснее всего укладывать младенца спать?"))
    show(g.answer("Сколько стоит детская коляска?"))
    eval_ten()
