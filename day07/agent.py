"""День 7 — агент с долговременной памятью (наследие Дня 6 + персист на диск).

Это тот же класс Agent из day06 с ОДНИМ новшеством: ему можно дать «папку дела»
(объект memory из memory.py). Тогда:
  • при создании агент ЗАГРУЖАЕТ историю с диска (продолжаем старый разговор);
  • после каждого хода ДОПИСЫВАЕТ обе реплики на диск (упадём — не потеряем).

Модель (LLM) об этом не знает: она, как и раньше, получает список реплик и
отвечает. Память — свойство ОБВЯЗКИ, а не модели.
"""
import os
import time
from openai import OpenAI, RateLimitError


class Agent:
    def __init__(self, system_prompt, model, memory=None, client=None, name="Агент",
                 max_turns=12, temperature=None, reasoning_effort="low"):
        self.name = name
        self.system_prompt = system_prompt   # РОЛЬ: задаёт поведение агента
        self.model = model
        self.temperature = temperature
        self.reasoning_effort = reasoning_effort
        self.max_turns = max_turns            # окно: сколько ПОСЛЕДНИХ ходов слать в модель
        self.memory = memory                  # НОВОЕ (День 7): «папка дела» на диске
        # Память сессии. Раньше всегда начинали с нуля; теперь — с того,
        # что лежит на диске (если папку дела дали и она не пуста).
        self.history = memory.load() if memory else []
        self.last_sent = []                   # что реально ушло в модель (для «капота»)
        self.client = client or OpenAI(
            base_url="https://openrouter.ai/api/v1",
            api_key=os.environ["OPENROUTER_API_KEY"],
        )

    def _build_messages(self):
        """РОЛЬ + скользящее окно истории (последние max_turns ходов).
        ВАЖНО: окно режет только то, что ШЛЁМ модели; на диске история полная."""
        window = self.history[-self.max_turns * 2:]
        return [{"role": "system", "content": self.system_prompt}, *window]

    def _remember(self, msg):
        """Одна точка записи: в список (стол) и, если есть, на диск (полка)."""
        self.history.append(msg)
        if self.memory:
            self.memory.append(msg)           # НОВОЕ (День 7): подшили листок сразу

    def send(self, user_message, printer=None):
        """Принять реплику → вызвать LLM → запомнить (ОЗУ + диск) → вернуть ответ."""
        self._remember({"role": "user", "content": user_message})
        messages = self._build_messages()
        self.last_sent = messages

        kwargs = {"model": self.model, "messages": messages, "stream": True}
        if self.temperature is not None:
            kwargs["temperature"] = self.temperature
        if self.reasoning_effort:
            kwargs["extra_body"] = {"reasoning": {"effort": self.reasoning_effort}}

        reply = ""
        for attempt in range(4):              # до 4 попыток при лимите 429
            reply = ""
            try:
                stream = self.client.chat.completions.create(**kwargs)
                for chunk in stream:
                    if not chunk.choices:
                        continue
                    token = chunk.choices[0].delta.content or ""
                    if token:
                        reply += token
                        if printer:
                            printer(token)
                break
            except RateLimitError:
                if attempt < 3:
                    time.sleep(3 * (attempt + 1))
                    continue
                reply = "[лимит запросов OpenRouter (429) — подожди минуту и повтори]"
            except Exception as e:
                reply = f"[ошибка вызова LLM: {e}]"
                break

        self._remember({"role": "assistant", "content": reply})
        return reply

    def reset(self):
        """Стереть разговор: и со стола (ОЗУ), и из папки дела (диск)."""
        self.history = []
        if self.memory:
            self.memory.clear()
