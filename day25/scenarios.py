"""
День 25 — проверка на двух длинных диалогах (10–15 сообщений каждый).

Задание просит проверить, что ассистент:
  - не теряет ЦЕЛЬ диалога (держит карточку задачи от начала до конца);
  - на каждом содержательном ходу продолжает выдавать ответ С ИСТОЧНИКАМИ
    (либо честно отказывается, если ответа в корпусе нет — тоже валидно).

Сценарии нарочно набиты follow-up с отсылками ('это', 'ему', 'а в такой позе'),
сменой темы и вопросом вне корпуса — чтобы нагрузить оба винтика.

Запуск:  ../day21/.venv/bin/python scenarios.py
"""
import json
from pathlib import Path

from chat import ChatSession

BASE = Path(__file__).parent

SCEN_1 = [
    "Малыш плачет каждый вечер и не может уснуть, это нормально?",
    "А сколько это обычно длится? Ему три недели.",
    "Из-за чего это вообще происходит?",
    "Можно ли как-то его успокоить в такие часы?",
    "А пеленание в этом помогает?",
    "Он у меня спит на спине — это точно безопасно?",
    "А на животе почему нельзя?",
    "Сколько вообще часов в сутки он должен спать в таком возрасте?",
    "Кстати, а какие капли от коликов лучше давать?",   # вне корпуса → ожидаем отказ
    "Ладно. Вернёмся ко сну — когда у него наладится режим?",
    "То есть к трём месяцам станет полегче?",
    "Спасибо. Подытожь, на что мне обращать внимание вечером.",
]

SCEN_2 = [
    "Как безопаснее укладывать новорождённого спать?",
    "А что должно быть в кроватке?",
    "Одеяло и подушку класть можно?",
    "Почему именно их нельзя?",
    "Малышу два месяца, ему нужна отдельная кроватка или можно с нами?",
    "А температура в комнате какая должна быть?",
    "Он часто просыпается ночью — это норма для двух месяцев?",
    "Что делать, когда он проснулся среди ночи?",
    "Свет включать при этом или нет?",
    "Какой сейчас курс доллара?",   # вне корпуса → ожидаем отказ
    "Извини, отвлёкся. Так со скольки месяцев он начнёт спать всю ночь?",
    "Подытожь главные правила безопасного сна для него.",
]


def run(name: str, msgs: list[str]) -> dict:
    print(f"\n{'='*70}\n{name}: {len(msgs)} сообщений\n{'='*70}")
    sess = ChatSession()
    rows, answered, with_src, abstained = [], 0, 0, 0
    for i, msg in enumerate(msgs, 1):
        t = sess.turn(msg)
        has_src = bool(t["citations"])
        if t["abstained"]:
            abstained += 1
        else:
            answered += 1
            if has_src:
                with_src += 1
        goal_ok = bool(t["task_state"]["goal"])
        print(f"\n[{i:>2}] вы: {msg}")
        if t["rewritten"]:
            print(f"     искали как: {t['standalone']}")
        print(f"     бот: {t['answer'][:150]}")
        print(f"     источников: {len(t['citations'])} | отказ: {t['abstained']} | "
              f"цель в карточке: {'да' if goal_ok else 'НЕТ'}")
        rows.append({"msg": msg, "standalone": t["standalone"], "answer": t["answer"],
                     "sources": len(t["citations"]), "abstained": t["abstained"],
                     "goal": t["task_state"]["goal"]})
    final = sess.state
    goal_held = all(r["goal"] for r in rows)             # цель не терялась ни на одном ходу
    answered_have_src = with_src == answered             # каждый НЕ-отказ имел источник
    print(f"\n  --- итог {name} ---")
    print(f"  ответов: {answered}, из них с источником: {with_src}; честных отказов: {abstained}")
    print(f"  цель держалась весь диалог: {'ДА' if goal_held else 'НЕТ'}")
    print(f"  каждый ответ с источником: {'ДА' if answered_have_src else 'НЕТ'}")
    print(f"  финальная карточка: {json.dumps(final, ensure_ascii=False)}")
    return {"name": name, "rows": rows, "final_state": final,
            "answered": answered, "with_src": with_src, "abstained": abstained,
            "goal_held": goal_held, "answered_have_src": answered_have_src}


def main():
    out = [run("Сценарий 1 — вечерний плач", SCEN_1),
           run("Сценарий 2 — безопасный сон", SCEN_2)]
    (BASE / "scenarios_out.json").write_text(json.dumps(out, ensure_ascii=False, indent=2))
    ok = all(s["goal_held"] and s["answered_have_src"] for s in out)
    print(f"\n{'='*70}\nОБЩИЙ ВЕРДИКТ: {'ПРОШЛИ ОБА' if ok else 'ЕСТЬ ПРОВАЛ — см. выше'}\n{'='*70}")


if __name__ == "__main__":
    main()
