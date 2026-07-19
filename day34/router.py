"""
День 34 — РОУТЕР: function-calling цикл (§10) для ассистента-редактора файлов.

Мост к Дню 31: тот же цикл «цель → модель смотрит на список инструментов → зовёт
нужный → результат обратно → снова модель» (слайд 34). Отличие Дня 34 — у агента
появились РУКИ на запись, и они работают через ГЕЙТ §11:
  * read-инструменты (read_file/grep_repo/list_files) — безопасные, идут молча;
  * write-инструменты (propose_edit/propose_create) — ГОТОВЯТ правку и складывают её
    в «ожидают подтверждения», но НЕ пишут на диск. Реальная запись — только после
    того, как человек нажмёт «Применить» (это делает app.py → fs_tool.apply_change).

Так «ассистент сам инициирует работу с файлами» (задание), но необратимый шаг —
запись — остаётся за человеком (§14 Human-in-the-Loop).
"""
import asyncio
import json
import sys

import config
import fs_tool
import llm

SYSTEM = f"""Ты — ассистент, который РАБОТАЕТ С ФАЙЛАМИ проекта «{config.PROJECT_ROOT.name}»,
а не просто отвечает текстом. Тебе дают ЦЕЛЬ (например «найди все места использования
save_note» или «обнови документацию под текущий код»), и ты сам решаешь, какие файлы
прочитать и что в них изменить.

Инструменты:
ЧТЕНИЕ (используй свободно, чтобы разобраться):
  • list_files(subdir) — карта проекта.
  • grep_repo(pattern, glob) — точный поиск строки/имени по файлам.
  • read_file(relpath) — прочитать конкретный файл.
ЗАПИСЬ (готовит правку; НА ДИСК НЕ ПИШЕТ — правку подтверждает человек):
  • propose_edit(relpath, old_str, new_str) — точечная правка. old_str обязан совпасть
    ДОСЛОВНО (те же отступы и пробелы) и встречаться РОВНО ОДИН раз. Если получил ошибку
    «не найден» или «несколько совпадений» — прочитай файл и пришли более точный фрагмент
    с окружающим контекстом.
  • propose_create(relpath, content) — создать НОВЫЙ файл (отчёт, README, ADR, changelog).

Правила:
- Сначала изучи (чтение), потом предлагай правки. Не выдумывай содержимое файлов — читай.
- Ты НЕ можешь записать сам: propose_* лишь готовит diff, человек нажмёт «Применить».
- Меняй только то, что просит цель. Не трогай .env и секреты (доступа к ним нет).
- Когда всё нужное предложено — дай КОРОТКИЙ итог по-русски: что нашёл и что предлагаешь
  изменить (перечисли файлы). Не повторяй сам diff — его человек увидит отдельно."""

SCHEMAS = [
    {"type": "function", "function": {
        "name": "list_files",
        "description": "Карта проекта: список файлов. subdir — сузить до подпапки.",
        "parameters": {"type": "object", "properties": {
            "subdir": {"type": "string", "description": "подпапка (по умолч. весь проект)"}}}}},
    {"type": "function", "function": {
        "name": "grep_repo",
        "description": "Точный поиск строки/регэкспа по файлам проекта. Для поиска имени/API.",
        "parameters": {"type": "object", "properties": {
            "pattern": {"type": "string", "description": "регэксп/подстрока"},
            "glob": {"type": "string", "description": "маска файлов, напр. *.py"}},
            "required": ["pattern"]}}},
    {"type": "function", "function": {
        "name": "read_file",
        "description": "Прочитать текстовый файл проекта по относительному пути.",
        "parameters": {"type": "object", "properties": {
            "relpath": {"type": "string", "description": "путь от корня проекта, напр. storage.py"}},
            "required": ["relpath"]}}},
    {"type": "function", "function": {
        "name": "propose_edit",
        "description": "Подготовить точечную правку файла (search/replace). НА ДИСК НЕ ПИШЕТ — "
                       "готовит diff на подтверждение человеку. old_str должен совпадать дословно и один раз.",
        "parameters": {"type": "object", "properties": {
            "relpath": {"type": "string"},
            "old_str": {"type": "string", "description": "точный фрагмент из файла (с отступами)"},
            "new_str": {"type": "string", "description": "на что заменить"}},
            "required": ["relpath", "old_str", "new_str"]}}},
    {"type": "function", "function": {
        "name": "propose_create",
        "description": "Подготовить создание НОВОГО файла (отчёт/README/ADR/changelog). На диск не пишет.",
        "parameters": {"type": "object", "properties": {
            "relpath": {"type": "string"},
            "content": {"type": "string", "description": "полное содержимое нового файла"}},
            "required": ["relpath", "content"]}}},
]

TOOL_LABEL = {"list_files": "смотрел карту проекта", "grep_repo": "искал по коду",
              "read_file": "читал файл", "propose_edit": "предложил правку",
              "propose_create": "предложил новый файл"}
TOOL_KIND = {"list_files": "read", "grep_repo": "read", "read_file": "read",
             "propose_edit": "write", "propose_create": "write"}
READ_TOOLS = {"list_files", "grep_repo", "read_file"}


class Session:
    """Один прогон цели. Копит предложенные правки (pending) — их применит человек."""

    def __init__(self):
        self.changes: list[dict] = []       # [{id, kind, relpath, diff, new_text}]

    def _dispatch(self, name: str, args: dict) -> str:
        if name == "list_files":
            return json.dumps(fs_tool.list_files(args.get("subdir", ".")), ensure_ascii=False)
        if name == "grep_repo":
            return json.dumps(fs_tool.grep_repo(args.get("pattern", ""), args.get("glob", "*")), ensure_ascii=False)
        if name == "read_file":
            return json.dumps(fs_tool.read_file(args.get("relpath", "")), ensure_ascii=False)
        if name in ("propose_edit", "propose_create"):
            res = (fs_tool.propose_edit(args.get("relpath", ""), args.get("old_str", ""), args.get("new_str", ""))
                   if name == "propose_edit" else
                   fs_tool.propose_create(args.get("relpath", ""), args.get("content", "")))
            if not res.get("ok"):
                return json.dumps(res, ensure_ascii=False)          # ошибка → модель переформулирует
            cid = len(self.changes) + 1
            self.changes.append({"id": cid, "kind": res["kind"], "relpath": res["relpath"],
                                 "diff": res["diff"], "new_text": res["new_text"]})
            # модели отдаём ФАКТ регистрации, но НЕ разрешаем считать это записью
            return json.dumps({"prepared": True, "change_id": cid, "relpath": res["relpath"],
                               "note": "правка подготовлена и ждёт подтверждения ЧЕЛОВЕКА; на диск ещё не записана"},
                              ensure_ascii=False)
        return json.dumps({"error": f"неизвестный инструмент {name}"}, ensure_ascii=False)


async def run_goal(goal: str) -> dict:
    """Прогнать одну цель через цикл §10. Возвращает итог + след + предложенные правки."""
    sess = Session()
    messages = [{"role": "system", "content": SYSTEM},
                {"role": "user", "content": goal}]
    trace, provider = [], "none"

    for _hop in range(config.MAX_TOOL_HOPS):
        msg, provider = await llm.chat(messages, SCHEMAS)
        calls = msg.tool_calls or []
        if not calls:
            return {"answer": msg.content or "(пусто)", "trace": trace,
                    "provider": provider, "changes": sess.changes}
        messages.append({"role": "assistant", "content": msg.content or "",
                         "tool_calls": [{"id": c.id, "type": "function",
                                         "function": {"name": c.function.name,
                                                      "arguments": c.function.arguments}} for c in calls]})
        for c in calls:
            try:
                args = json.loads(c.function.arguments or "{}")
            except Exception:
                args = {}
            result = await asyncio.to_thread(sess._dispatch, c.function.name, args)
            trace.append({"tool": c.function.name, "label": TOOL_LABEL.get(c.function.name, c.function.name),
                          "kind": TOOL_KIND.get(c.function.name, "read"),
                          "arg": args.get("relpath") or args.get("pattern") or args.get("subdir") or ""})
            messages.append({"role": "tool", "tool_call_id": c.id, "content": result})

    # исчерпали круги (§14): финальный синтез без новых вызовов
    messages.append({"role": "user", "content": "Достаточно. Дай короткий итог: что нашёл и какие правки предложил."})
    msg, provider = await llm.chat(messages, tools=None)
    return {"answer": msg.content or "(итог не собран)", "trace": trace,
            "provider": provider, "changes": sess.changes, "capped": True}


# ── CLI-смок: доказать, что мозг ходит в файлы и готовит правки, ДО веб-лица ──
async def _cli():
    goal = " ".join(sys.argv[1:]) or "Найди все места в проекте, где используется функция save_note."
    print(f"ЦЕЛЬ: {goal}\n")
    res = await run_goal(goal)
    print("── СЛЕД ──")
    for t in res["trace"]:
        print(f"  • {t['label']} ({t['kind']}) {t['arg']}")
    print(f"\n── ИТОГ ({res['provider']}) ──\n{res['answer']}")
    print(f"\n── ПРЕДЛОЖЕНО ПРАВОК: {len(res['changes'])} ──")
    for ch in res["changes"]:
        print(f"  #{ch['id']} [{ch['kind']}] {ch['relpath']}")


if __name__ == "__main__":
    asyncio.run(_cli())
