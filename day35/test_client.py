"""
День 35 — smoke-тест пайплайна (§16 конспекта: Smoke Test).

Гоняем два состояния — «беременность» (сегодня) и «жизнь» (искусственно ставим дату
рождения 3 недели назад) — и проверяем то, что просит §16 и бриф Дня 35:
  • пайплайн запускается и выход НЕ пустой, формат корректный;
  • переключение фаз работает (беременность → жизнь) по данным;
  • ОГРАНИЧИТЕЛИ на месте: есть дисклеймер и явная маркировка «сгенерировано ИИ»;
  • ЗАПРЕЩЁННОГО в тексте нет: дозировок (мг), псевдонаучных «скачков развития по
    неделям», «окон бодрствования», «регресса сна» (дискредитировано, из брифа).

Это не заглушка ради галочки, а реальный quality-gate: если промпт-ограничитель сползёт,
тест это поймает до отправки.
"""
from datetime import date, timedelta

import config
import digest

# то, чего в родительском дайджесте быть НЕ должно (бриф Дня 35)
FORBIDDEN = ["скачок развития", "скачки развития", "wonder week", "окна бодрствования",
             "окно бодрствования", "регресс сна", " мг ", "мг/", "миллиграмм"]
MUST_HAVE = ["не заменяет консультацию врача", "Сгенерировано ИИ"]


def _check(name: str, md: str) -> list[str]:
    fails = []
    if not md or len(md) < 100:
        fails.append("выход пустой/слишком короткий")
    if not md.lstrip().startswith("#"):
        fails.append("нет заголовка (формат)")
    low = md.lower()
    for bad in FORBIDDEN:
        if bad.lower() in low:
            fails.append(f"запрещённое в тексте: «{bad.strip()}»")
    for need in MUST_HAVE:
        if need.lower() not in low:
            fails.append(f"нет обязательного: «{need}»")
    mark = "✓ PASS" if not fails else "✗ FAIL"
    print(f"\n[{mark}] {name}")
    for f in fails:
        print(f"    - {f}")
    return fails


def main() -> None:
    all_fails = []

    # --- 1. режим «беременность» (сегодняшние даты из .env) ---
    res = digest.build_digest()
    print("МЕТРИКИ беременность:", res["metrics"])
    all_fails += _check("беременность (сегодня)", res["markdown"])
    assert res["phase"] == "pregnancy", "ожидалась фаза беременность (ребёнок ещё не родился)"

    # --- 2. режим «жизнь»: искусственно ставим рождение 3 недели назад ---
    saved = config.BABY_BIRTH_DATE
    config.BABY_BIRTH_DATE = date.today() - timedelta(days=21)
    try:
        res2 = digest.build_digest()
        print("\nМЕТРИКИ жизнь(3 нед):", res2["metrics"])
        all_fails += _check("жизнь (3 недели)", res2["markdown"])
        assert res2["phase"] == "life", "ожидалась фаза жизнь"
        # рубрики должны переключиться на детские (кормление/сон/красные флаги)
        titles = [b["rubric"]["title"] for b in res2["blocks"]]
        assert any("сон" in t.lower() or "врач" in t.lower() or "кормл" in t.lower() for t in titles), \
            "в режиме жизни ожидались детские рубрики"
        print("    рубрики жизни:", "; ".join(titles))
    finally:
        config.BABY_BIRTH_DATE = saved

    print("\n" + "=" * 50)
    if all_fails:
        print(f"ИТОГ: {len(all_fails)} провал(ов) — смотри выше.")
        raise SystemExit(1)
    print("ИТОГ: smoke-тест ЗЕЛЁНЫЙ — оба режима, формат ок, ограничители держат.")


if __name__ == "__main__":
    main()
