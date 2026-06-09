"""День 6 — Первый агент: класс Agent (ОТДЕЛЬНАЯ СУЩНОСТЬ).

Задание дня: «агент должен быть отдельной сущностью, а не просто один вызов API;
логика запроса и ответа должна быть инкапсулирована в агенте».

Что делает это «сущностью», а не функцией с одним вызовом:
  • РОЛЬ (system prompt) — кто агент и как себя ведёт. Сужает бесконечную базу
    знаний LLM до нужного поведения (лекция нед. 2, §3.4).
  • ПАМЯТЬ СЕССИИ (self.history) — агент помнит разговор между ходами, поэтому это
    диалог с состоянием, а НЕ «один вызов» (лекция нед. 2, §6.2 «session memory»).
  • ИНКАПСУЛЯЦИЯ — клиент и сетевой вызов спрятаны внутри; снаружи доступно только
    .send(text). Кто угодно (CLI, веб, бот) общается с агентом одинаково.
  • УПРАВЛЕНИЕ КОНТЕКСТОМ — простое «скользящее окно» (sliding window, §4.2):
    помним последние N ходов, старое выкидываем, чтобы контекст не рос бесконечно.

Честная оговорка: по строгому определению 2026 «агент» = модель + ИНСТРУМЕНТЫ +
ЦИКЛ до достижения цели. Здесь пока 1 ход за вызов — это ЗАГОТОВКА (proto-agent).
Цикл и инструменты добавим на след. шагах недели; место под них зарезервировано
(см. метод step() внизу).

Провайдер — OpenRouter (OpenAI-совместимый). Ключ — в .env, не хардкодим.
"""
import os
import time
from openai import OpenAI, RateLimitError


class Agent:
    def __init__(self, system_prompt, model, client=None, name="Агент",
                 max_turns=12, temperature=None, reasoning_effort="low"):
        self.name = name
        self.system_prompt = system_prompt   # РОЛЬ: задаёт поведение агента
        self.model = model
        self.temperature = temperature        # ручка дня 4; на reasoning-моделях игнор.
        self.reasoning_effort = reasoning_effort  # ручка дня 5; "low" → чат отвечает быстро
        self.max_turns = max_turns            # сколько ПОСЛЕДНИХ ходов помнить (окно)
        self.history = []                     # ПАМЯТЬ СЕССИИ: [{role, content}, ...]
        self.last_sent = []                   # что реально ушло в модель (для «капота»)
        # Клиент создаём ОДИН раз и держим внутри агента — это и есть инкапсуляция
        # вызова API: наружу он не торчит.
        self.client = client or OpenAI(
            base_url="https://openrouter.ai/api/v1",
            api_key=os.environ["OPENROUTER_API_KEY"],
        )

    def _build_messages(self):
        """Собрать то, что реально уйдёт в модель: РОЛЬ + (обрезанная) история.
        Срез [-max_turns*2:] — скользящее окно: *2, т.к. на 1 ход приходится пара
        сообщений (user + assistant)."""
        window = self.history[-self.max_turns * 2:]
        return [{"role": "system", "content": self.system_prompt}, *window]

    def send(self, user_message, printer=None, remember=True):
        """Принять реплику → вызвать LLM → (запомнить ответ) → вернуть его.

        remember=True  → АГЕНТ: дописываем ход в историю и шлём ВСЮ историю заново.
        remember=False → имитация ОДНОГО вызова: шлём только роль + текущую реплику,
                         в историю НЕ пишем (агент остаётся «без памяти», как амнезия).

        Весь сетевой вызов спрятан здесь (инкапсуляция). Стримим (как в дне 5).
        printer(token) — необязательный колбэк для живого вывода (его передаёт CLI).
        """
        if remember:
            self.history.append({"role": "user", "content": user_message})
            messages = self._build_messages()
        else:
            messages = [{"role": "system", "content": self.system_prompt},
                        {"role": "user", "content": user_message}]
        self.last_sent = messages             # фиксируем для панели «под капотом»

        kwargs = {"model": self.model, "messages": messages, "stream": True}
        if self.temperature is not None:
            kwargs["temperature"] = self.temperature
        if self.reasoning_effort:
            kwargs["extra_body"] = {"reasoning": {"effort": self.reasoning_effort}}

        reply = ""
        for attempt in range(4):                  # до 4 попыток при лимите 429
            reply = ""
            try:
                stream = self.client.chat.completions.create(**kwargs)
                for chunk in stream:
                    if not chunk.choices:          # последний usage-чанк без choices
                        continue
                    token = chunk.choices[0].delta.content or ""
                    if token:
                        reply += token
                        if printer:
                            printer(token)
                break                              # успех — выходим из цикла повторов
            except RateLimitError:
                if attempt < 3:                    # подождать и повторить (3, 6, 9 с)
                    time.sleep(3 * (attempt + 1))
                    continue
                reply = "[лимит запросов OpenRouter (429) — подожди минуту и повтори]"
            except Exception as e:                 # сеть/ключ/прочее — не роняем чат
                reply = f"[ошибка вызова LLM: {e}]"
                break

        if remember:
            self.history.append({"role": "assistant", "content": reply})
        return reply

    def reset(self):
        """Пересоздание диалога (лекция §4.5 / команда clear): чистим память сессии."""
        self.history = []

    # --- ЗАГОТОВКА под настоящую агентность (след. шаги недели 2) -----------------
    # def step(self, goal):
    #     Здесь будет ЦИКЛ: модель думает → выбирает ИНСТРУМЕНТ → видит результат →
    #     повторяет, пока цель не достигнута (agentic loop из брифа). Сейчас агент
    #     делает один ход; цикл + инструменты (tool use / MCP) добавим позже.
