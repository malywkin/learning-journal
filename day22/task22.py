"""
День 22 — сдача (CLI). Показывает ровно то, что просит задание:
  1. функция «вопрос → чанки → augmented-промпт → ответ LLM» (rag_core.rag_answer);
  2. сравнение ответа без RAG и с RAG на одном вопросе;
  3. усиление — прогон 10 контрольных вопросов и замер качества по 3 метрикам
     слайда 55 (relevance / faithfulness / correctness) + проверка честного отказа.

Запуск (из папки day22, через venv Дня 21 — переиспользуем):
  OPENROUTER_API_KEY из .env;  INDEX_DB по умолчанию = ../day21/index.db
"""
import textwrap
from dotenv import load_dotenv

import rag_core
from questions import GOLDEN

load_dotenv()  # берём OPENROUTER_API_KEY из day22/.env


def _wrap(t, w=86):
    return textwrap.fill(t, w, subsequent_indent="   ")


# ---------- eval одного вопроса по трём метрикам ----------
def grade(item: dict) -> dict:
    """Прогоняем вопрос через RAG и сверяем с эталоном (тройка метрик)."""
    r = rag_core.rag_answer(item["q"])
    ans_low = r["answer"].lower()

    # 1) Context Relevance — нашёл ли ретривал близкий кусок
    relevant = r["top_cos"] >= rag_core.REL_THRESHOLD
    # 2) Faithfulness — ответ оперся на источники (есть валидные ссылки) ИЛИ честный отказ
    faithful = bool(r["citations"]["valid"]) or r["abstained"]
    # 3) Answer Correctness — совпал с ожиданием
    hit = any(kw.lower() in ans_low for kw in item["expect"])

    if item["in_base"]:
        # ожидаем: нашли, оперлись, попали в ожидание
        ok = relevant and faithful and hit
    else:
        # ловушка: правильно = ЧЕСТНЫЙ отказ. «нашёл» тут честно False (близкого нет,
        # top_cos < порога) — и это ожидаемо; зачёт держится на самом отказе.
        ok = r["abstained"]

    return {"q": item["q"], "in_base": item["in_base"], "answer": r["answer"],
            "top_cos": r["top_cos"], "relevant": relevant, "faithful": faithful,
            "hit": hit, "abstained": r["abstained"], "citations": r["citations"],
            "ok": ok}


def demo_two_modes(question: str):
    print("=" * 92)
    print("1–2. ДВА РЕЖИМА НА ОДНОМ ВОПРОСЕ")
    print("=" * 92)
    print(f"Вопрос: {question}\n")
    print("[БЕЗ RAG] модель отвечает из головы:")
    print("   " + _wrap(rag_core.plain_answer(question)["answer"]) + "\n")
    r = rag_core.rag_answer(question)
    print("[С RAG] ответ по книге (близость найденных кусков: " +
          ", ".join(f"{c['cos']}" for c in r["chunks"]) + "):")
    print("   " + _wrap(r["answer"]))
    print(f"   ссылки: {r['citations']['cited']}  "
          f"(валидные: {r['citations']['valid']}, выдуманные: {r['citations']['invalid']})")


def run_golden():
    print("\n" + "=" * 92)
    print("3. КОНТРОЛЬНЫЕ 10 ВОПРОСОВ — качество по метрикам слайда 55")
    print("=" * 92)
    print(f"{'вопрос':46}| близ. | нашёл | оперся | совпал | итог")
    print("-" * 92)
    rows = [grade(it) for it in GOLDEN]
    m = lambda b: " ✓ " if b else " · "
    for r in rows:
        tag = "в базе" if r["in_base"] else "ВНЕ"
        print(f"{r['q'][:46]:46}| {r['top_cos']:.2f} |{m(r['relevant'])}  |"
              f"{m(r['faithful'])}   |{m(r['hit'])}   | {'OK' if r['ok'] else 'FAIL'} ({tag})")
    passed = sum(r["ok"] for r in rows)
    print("-" * 92)
    print(f"ИТОГО: {passed}/{len(rows)} прошли эталон "
          f"| в базе: {sum(r['ok'] and r['in_base'] for r in rows)}/"
          f"{sum(r['in_base'] for r in rows)} "
          f"| отказ на ловушках: {sum(r['ok'] and not r['in_base'] for r in rows)}/"
          f"{sum(not r['in_base'] for r in rows)}")
    return rows


if __name__ == "__main__":
    demo_two_modes("В какой позе безопаснее всего укладывать младенца спать?")
    run_golden()
