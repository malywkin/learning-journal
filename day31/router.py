"""
День 31 — РОУТЕР /help: function-calling цикл (§10 конспекта).

Сердце дня. Сюда сходятся все три вида инструментов §8:
  RAG Tools    — search_docs  (поиск по докам, узел 3);
  MCP Tools    — git_*        (живое состояние репо через MCP-сервер, узел 4);
  System Tools — grep_repo/read_file/list_files (агентное чтение, узел 5).

Цикл (слайд 34): вопрос → модель смотрит на список инструментов → выбирает нужный →
вызываем execute() → результат обратно в модель → она решает: звать ещё инструмент или
дать ответ. Для сложного вопроса модель может пройти НЕСКОЛЬКО кругов (tool-use loop).

Ключ надёжности (принцип Anthropic из брифа): НЕ «сила модели», а ЧЁТКИЕ непересекающиеся
описания инструментов в system-промпте и в схемах — по ним модель и выбирает.
"""
import asyncio
import json
import sys
from contextlib import AsyncExitStack
from pathlib import Path

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

import config
import docs_tool
import fs_tool
import llm

BASE = Path(__file__).resolve().parent

# ── System-промпт: рамка «ассистент по проекту» + КОГДА какой инструмент ──
SYSTEM = f"""Ты — ассистент-разработчик по проекту, лежащему в {config.REPO_ROOT.name}.
Отвечаешь на вопросы о проекте (команда /help): его структура, код, документация, git.

У тебя есть три вида инструментов — выбирай по смыслу вопроса:
1. search_docs(query) — СМЫСЛОВОЙ поиск по документации проекта (обзор, задания, выводы).
   Бери, когда вопрос концептуальный: «как мы делали X», «что за проект», «зачем Y».
2. git_branch / git_status / git_log / git_diff — ЖИВОЕ состояние репозитория через git.
   Бери, когда спрашивают про ветку, изменения, историю коммитов.
3. grep_repo(pattern) / read_file(relpath) / list_files(subdir) — ТОЧНОЕ чтение файлов.
   Бери, когда нужно найти конкретное имя/строку в коде или прочитать конкретный файл.

Правила:
- Опирайся на инструменты, а не на догадки. Не знаешь — сходи инструментом.
- Если ответа в проекте нет — честно скажи «в проекте не нашёл», не выдумывай.
- Отвечай кратко, по-русски. Ссылайся на файлы, откуда взял (напр. day22/rag_core.py)."""

# ── Схемы System-инструментов в формате function-calling (OpenAI) ──
LOCAL_SCHEMAS = [
    {"type": "function", "function": {
        "name": "search_docs",
        "description": "Смысловой поиск по документации проекта (RAG). Для концептуальных "
                       "вопросов: как что делали, что за проект, зачем нужен модуль.",
        "parameters": {"type": "object", "properties": {
            "query": {"type": "string", "description": "поисковый запрос по смыслу"}},
            "required": ["query"]}}},
    {"type": "function", "function": {
        "name": "grep_repo",
        "description": "Точный поиск строки/регэкспа по файлам репозитория (код и доки). "
                       "Для поиска конкретного имени, функции, строки.",
        "parameters": {"type": "object", "properties": {
            "pattern": {"type": "string", "description": "регэксп/подстрока для поиска"},
            "glob": {"type": "string", "description": "маска файлов, напр. *.py (по умолч. все)"}},
            "required": ["pattern"]}}},
    {"type": "function", "function": {
        "name": "read_file",
        "description": "Прочитать конкретный текстовый файл репозитория по относительному пути.",
        "parameters": {"type": "object", "properties": {
            "relpath": {"type": "string", "description": "путь от корня репо, напр. day22/rag_core.py"}},
            "required": ["relpath"]}}},
    {"type": "function", "function": {
        "name": "list_files",
        "description": "Список файлов репозитория (карта проекта). subdir — сузить до подпапки.",
        "parameters": {"type": "object", "properties": {
            "subdir": {"type": "string", "description": "подпапка, напр. day31 (по умолч. весь репо)"}}}}},
]

# Дружелюбные подписи для значка в окне (какой инструмент сработал).
TOOL_LABEL = {
    "search_docs": "искал в документации",
    "git_branch": "смотрел git-ветку", "git_status": "смотрел git-статус",
    "git_log": "смотрел историю коммитов", "git_diff": "смотрел изменения",
    "grep_repo": "искал по коду", "read_file": "читал файл", "list_files": "смотрел карту проекта",
}
TOOL_KIND = {  # к какому из трёх видов §8 относится инструмент — для цвета значка
    "search_docs": "rag",
    "git_branch": "mcp", "git_status": "mcp", "git_log": "mcp", "git_diff": "mcp",
    "grep_repo": "sys", "read_file": "sys", "list_files": "sys",
}


class ToolHub:
    """Держит живую MCP-сессию к git-серверу и умеет вызывать любой из трёх видов тулзов."""

    def __init__(self, session: ClientSession):
        self.session = session
        self.mcp_names: set[str] = set()
        self.schemas: list[dict] = []

    @classmethod
    async def create(cls, stack: AsyncExitStack) -> "ToolHub":
        # Поднимаем MCP-git-сервер как stdio под-процесс (тем же venv, что и мы).
        params = StdioServerParameters(
            command=sys.executable, args=[str(BASE / "mcp_git.py")], cwd=str(BASE))
        read, write = await stack.enter_async_context(stdio_client(params))
        session = await stack.enter_async_context(ClientSession(read, write))
        await session.initialize()
        hub = cls(session)
        listed = await session.list_tools()
        for t in listed.tools:                     # MCP-схемы → формат function-calling
            hub.mcp_names.add(t.name)
            hub.schemas.append({"type": "function", "function": {
                "name": t.name, "description": t.description or "", "parameters": t.inputSchema}})
        hub.schemas += LOCAL_SCHEMAS               # + System/RAG инструменты
        return hub

    async def dispatch(self, name: str, args: dict) -> str:
        """Выполнить инструмент по имени. MCP-тулзы идут через сессию, остальные — напрямую."""
        if name in self.mcp_names:
            res = await self.session.call_tool(name, args)
            payload = res.structuredContent or {"text": _mcp_text(res)}
            return json.dumps(payload, ensure_ascii=False)
        # System/RAG — синхронные функции, гоним в отдельном потоке, чтобы не блокировать loop.
        if name == "search_docs":
            hits = await asyncio.to_thread(docs_tool.search_docs, args.get("query", ""), 4)
            return json.dumps([{"source": h["source"], "section": h["section"],
                                "score": h.get("score"), "text": h["text"][:400]} for h in hits],
                              ensure_ascii=False)
        if name == "grep_repo":
            return json.dumps(await asyncio.to_thread(
                fs_tool.grep_repo, args.get("pattern", ""), args.get("glob", "*")), ensure_ascii=False)
        if name == "read_file":
            return json.dumps(await asyncio.to_thread(
                fs_tool.read_file, args.get("relpath", "")), ensure_ascii=False)
        if name == "list_files":
            return json.dumps(await asyncio.to_thread(
                fs_tool.list_files, args.get("subdir", ".")), ensure_ascii=False)
        return json.dumps({"error": f"неизвестный инструмент {name}"}, ensure_ascii=False)


def _mcp_text(res) -> str:
    """Фолбэк: вытащить текст из MCP-ответа, если нет structuredContent (память day17)."""
    try:
        return res.content[0].text
    except Exception:
        return ""


async def answer(question: str, hub: ToolHub, history: list[dict] | None = None) -> dict:
    """Один проход function-calling цикла §10. Возвращает ответ + след использованных тулзов."""
    messages = [{"role": "system", "content": SYSTEM}]
    messages += history or []
    messages.append({"role": "user", "content": question})

    trace: list[dict] = []
    provider = "none"
    for _hop in range(config.MAX_TOOL_HOPS):
        msg, provider = await llm.chat(messages, hub.schemas)
        calls = msg.tool_calls or []
        if not calls:                                     # модель дала финальный ответ
            return {"answer": msg.content or "(пусто)", "trace": trace, "provider": provider}

        # Кладём ответ модели с запросом инструментов обратно в диалог.
        messages.append({"role": "assistant", "content": msg.content or "",
                         "tool_calls": [{"id": c.id, "type": "function",
                                         "function": {"name": c.function.name,
                                                      "arguments": c.function.arguments}} for c in calls]})
        # Выполняем каждый запрошенный инструмент, результат — обратно в диалог.
        for c in calls:
            try:
                args = json.loads(c.function.arguments or "{}")
            except Exception:
                args = {}
            result = await hub.dispatch(c.function.name, args)
            trace.append({"tool": c.function.name, "label": TOOL_LABEL.get(c.function.name, c.function.name),
                          "kind": TOOL_KIND.get(c.function.name, "sys"), "args": args})
            messages.append({"role": "tool", "tool_call_id": c.id, "content": result})

    # Исчерпали круги инструментов (§14): не сдаёмся с пустыми руками — просим модель
    # ответить по УЖЕ собранному, запретив новые вызовы (tool_choice отсутствует).
    messages.append({"role": "user", "content":
                     "Достаточно инструментов. Дай финальный ответ по уже собранным данным."})
    msg, provider = await llm.chat(messages, tools=None)
    return {"answer": msg.content or "(не удалось собрать ответ)",
            "trace": trace, "provider": provider, "capped": True}


# ── CLI-смок: доказать, что мозг работает, ДО веб-лица ──
async def _cli():
    q = " ".join(sys.argv[1:]) or "Какая сейчас git-ветка и сколько было последних коммитов?"
    async with AsyncExitStack() as stack:
        hub = await ToolHub.create(stack)
        print(f"Инструментов в наборе: {len(hub.schemas)}  (из них MCP: {len(hub.mcp_names)})")
        print(f"Вопрос: {q}\n")
        res = await answer(q, hub)
        print("── СЛЕД ИНСТРУМЕНТОВ ──")
        for t in res["trace"]:
            print(f"  • {t['label']} ({t['kind']}) args={t['args']}")
        print(f"\n── ОТВЕТ ({res['provider']}) ──\n{res['answer']}")


if __name__ == "__main__":
    asyncio.run(_cli())
