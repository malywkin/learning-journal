"""
День 25 — ядро мини-чата с RAG и памятью задачи (production-like).

Ничего не изобретаем с нуля — склеиваем уже собранное за неделю RAG:
  - День 21 дал индекс + эмбеддер;
  - День 22 дал retrieve();
  - День 23 дал реранкер + порог;
  - День 24 дал grounded.answer() — весь конвейер: поиск → реранк → порог-отказ →
    контракт {answer,sources,quotes} → проверка цитат кодом → судья faithfulness.

СЕГОДНЯ поверх этого два винтика, которые превращают одиночный вопрос-ответ в диалог:
  Винтик #1 — контекстуализация follow-up (condense): переписываем реплику с
    отсылками ('это', 'ему', 'а сколько') в самодостаточный вопрос ПЕРЕД поиском,
    подтягивая недостающее из истории И из карточки задачи.
  Винтик #2 — карточка задачи (task state): точечно (дельтой, не пересказом) копим,
    что уточнил юзер / какие ограничения / какая цель. Дедуп против задвоения.

Железное правило (стандарт conversational RAG 2026): история чинит ВОПРОС, но
отвечаем ТОЛЬКО из найденных источников — карточка НЕ источник ответов.
"""
import json
import sys
from pathlib import Path

BASE = Path(__file__).parent
sys.path.insert(0, str(BASE.parent / "day22"))
sys.path.insert(0, str(BASE.parent / "day23"))
sys.path.insert(0, str(BASE.parent / "day24"))

import grounded as g  # noqa: E402  весь конвейер Дня 24 + _chat/_parse_json/провайдер


# ---------- Винтик #1: контекстуализация follow-up ----------
CONDENSE_SYS = (
    "Ты переписываешь последний вопрос пользователя в ОДИН самодостаточный поисковый запрос.\n"
    "Дана история диалога и карточка задачи (уточнённые факты).\n"
    "Разверни все отсылки ('это', 'он', 'ему', 'а сколько', 'в таком случае') по истории.\n"
    "Если в карточке есть факты (возраст, ограничения), уместные вопросу — впиши их в запрос.\n"
    "Если пользователь сменил тему — НЕ тащи старую тему в запрос, бери только уместное.\n"
    "Верни ОДНУ строку на русском — полный самостоятельный вопрос, без пояснений и кавычек."
)


def condense(history: list[dict], state: dict, followup: str) -> tuple[str, bool]:
    """Реплику с отсылками → самодостаточный запрос. Возвращает (запрос, переписали ли).

    На первом ходу (истории нет) переписывать нечего — отдаём вопрос как есть, экономим
    вызов LLM и не даём модели испортить и без того чистый вопрос."""
    if not history:
        return followup, False
    hist = "\n".join(f"{m['role']}: {m['content']}" for m in history[-8:])
    card = json.dumps(state, ensure_ascii=False)
    raw = g._chat(
        [{"role": "system", "content": CONDENSE_SYS},
         {"role": "user", "content": f"ИСТОРИЯ:\n{hist}\n\nКАРТОЧКА ЗАДАЧИ:\n{card}\n\n"
                                     f"ПОСЛЕДНИЙ ВОПРОС: {followup}\n\nСАМОДОСТАТОЧНЫЙ ЗАПРОС:"}],
        json_mode=False, max_tokens=120)
    standalone = raw.strip().splitlines()[0].strip().strip('"') if raw.strip() else followup
    return standalone, standalone.strip().lower() != followup.strip().lower()


# ---------- Винтик #2: карточка задачи (точечная дельта + дедуп) ----------
STATE_SYS = (
    "Ты ведёшь карточку задачи диалога. Дана текущая карточка и новый ход пользователя.\n"
    "Верни ТОЛЬКО JSON с ДЕЛЬТОЙ (что добавить), пустые поля опускай:\n"
    '{"goal": "<новая формулировка цели, ТОЛЬКО если реально уточнилась>", '
    '"clarified_add": ["<новый ФАКТ, который пользователь сообщил О СЕБЕ или о ребёнке>"], '
    '"constraints_add": ["<новое ограничение или зафиксированный термин>"]}\n'
    "ВАЖНО: вопрос пользователя — это НЕ факт. Если пользователь просто задаёт вопрос и "
    "не сообщает НОВОГО факта о себе/ребёнке (возраст, состояние, условия) — верни пустой {}.\n"
    "Пример факта: 'ребёнку три недели', 'спит на спине'. НЕ факт: 'а одеяло можно?'.\n"
    "Бери только то, что реально прозвучало — не выдумывай.\n"
    "НЕ повторяй то, что УЖЕ есть в карточке — добавляй только НОВОЕ."
)


def _norm_item(s: str) -> str:
    return " ".join(str(s).lower().split())


def _merge(existing: list, add: list) -> list:
    """Дедуп: добавляем только то, чего ещё нет (грабля трейса — модель задваивала факт)."""
    seen = {_norm_item(x) for x in existing}
    out = list(existing)
    for x in add or []:
        if x and _norm_item(x) not in seen:
            seen.add(_norm_item(x))
            out.append(x)
    return out


def update_state(state: dict, user_msg: str, standalone: str) -> tuple[dict, dict]:
    """Карточку обновляем ДЕЛЬТОЙ, а не пересказом истории (пересказ копит ошибки)."""
    payload = (f"КАРТОЧКА СЕЙЧАС:\n{json.dumps(state, ensure_ascii=False)}\n\n"
               f"НОВЫЙ ХОД — вопрос пользователя: {user_msg}\n"
               f"(в самодостаточном виде: {standalone})")
    delta = g._parse_json(g._chat(
        [{"role": "system", "content": STATE_SYS},
         {"role": "user", "content": payload}], max_tokens=200)) or {}
    new = {"goal": (delta.get("goal") or state.get("goal") or "").strip(),
           "clarified": _merge(state.get("clarified", []), delta.get("clarified_add")),
           "constraints": _merge(state.get("constraints", []), delta.get("constraints_add"))}
    return new, delta


# ---------- Сессия чата: история + карточка живут между ходами ----------
def new_state(goal: str = "") -> dict:
    return {"goal": goal, "clarified": [], "constraints": []}


class ChatSession:
    """Держит историю диалога и карточку задачи. Один ход = один вызов turn()."""

    def __init__(self, goal: str = ""):
        self.history: list[dict] = []
        self.state: dict = new_state(goal)

    def turn(self, user_msg: str) -> dict:
        """Ход диалога: переписать вопрос → ответить по источникам → обновить карточку."""
        # 1) Винтик #1 — самодостаточный запрос
        standalone, rewritten = condense(self.history, self.state, user_msg)

        # 2) Ядро Дня 24 — ответ СТРОГО по источникам, с цитатами.
        #    judge=False: в вебе судью не показываем, а он тратит лишний вызов модели —
        #    грунтовку ответа держит проверка цитат КОДОМ (бесплатная), её и хватает.
        res = g.answer(standalone, judge=False)

        # 3) Винтик #2 — точечно обновить карточку задачи
        self.state, delta = update_state(self.state, user_msg, standalone)

        # 4) Записать ход в историю (для следующей контекстуализации)
        self.history.append({"role": "user", "content": user_msg})
        self.history.append({"role": "assistant", "content": res["answer"]})

        # источники к показу: подтверждённые цитаты + разделы
        sources = [{"section": (s.get("section") or "источник"),
                    "chunk_id": s.get("chunk_id")} for s in (res.get("sources") or [])]
        verified = [x for x in (res.get("checked") or []) if x.get("matched")]

        return {
            "user": user_msg,
            "standalone": standalone,
            "rewritten": rewritten,
            "answer": res["answer"],
            "abstained": res.get("abstained") or res.get("status") == "model_abstained",
            "status": res.get("status", "abstained" if res.get("abstained") else "answered"),
            "top_score": res.get("top_score", 0.0),
            "sources": sources,
            "citations": [{"quote": v["quote"], "chunk_id": v.get("chunk_id"),
                           "method": v.get("method")} for v in verified],
            "faithfulness": res.get("faithfulness"),
            "state_delta": delta,
            "task_state": self.state,
        }


# ---------- CLI: мини-чат в терминале (формат задания — CLI/веб) ----------
def _cli():
    print("Мини-чат RAG + память задачи (День 25). Пустая строка — выход.\n")
    sess = ChatSession()
    while True:
        try:
            msg = input("вы> ").strip()
        except (EOFError, KeyboardInterrupt):
            break
        if not msg:
            break
        t = sess.turn(msg)
        if t["rewritten"]:
            print(f"   (искали как: {t['standalone']})")
        print(f"бот> {t['answer']}")
        for c in t["citations"]:
            print(f"     ↳ источник: «{c['quote'][:90]}»")
        if not t["citations"] and not t["abstained"]:
            print("     ↳ (без подтверждённой цитаты)")
        card = t["task_state"]
        print(f"   [карточка] цель: {card['goal'] or '—'} | "
              f"уточнено: {card['clarified'] or '—'} | ограничения: {card['constraints'] or '—'}\n")


if __name__ == "__main__":
    _cli()
