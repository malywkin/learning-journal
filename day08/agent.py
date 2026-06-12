"""День 8 — агент со СЧЁТЧИКОМ ТОКЕНОВ (наследие Дней 6–7 + бухгалтерия токенов).

Тот же класс Agent, что в Дне 7 (роль + клиент + история + персист), с одним
новшеством: после каждого хода он читает серверное поле `usage` и ведёт
«бухгалтерскую книгу» (ledger) — сколько токенов ушло на вход (вся история),
сколько на ответ, и «как если бы» стоимость нарастающим итогом.

Что именно новое против Дня 7:
  • из стрима ловим финальный чанк с `usage` (на OpenRouter он приходит всегда);
  • складываем по-ходовую запись в self.ledger (для кривой роста и счётчика);
  • перед отправкой считаем ЛОКАЛЬНУЮ прикидку — чтобы рядом показать «оценка vs факт»;
  • метод complete() — один не-стримовый вызов для демо-сценариев (переполнение/забывание).
"""
import os
import time

from openai import OpenAI, RateLimitError

from tokens import as_if_cost, estimate_messages, normalize_usage, window_for


class Agent:
    def __init__(self, system_prompt, model, memory=None, client=None, name="Агент",
                 max_turns=12, temperature=None, reasoning_effort="low"):
        self.name = name
        self.system_prompt = system_prompt   # РОЛЬ: задаёт поведение агента
        self.model = model
        self.temperature = temperature
        self.reasoning_effort = reasoning_effort
        self.max_turns = max_turns            # окно: сколько ПОСЛЕДНИХ ходов слать в модель
        self.memory = memory                  # «папка дела» на диске (День 7)
        self.history = memory.load() if memory else []
        self.last_sent = []                   # что реально ушло в модель (для «капота»)
        self.ledger = []                      # НОВОЕ (День 8): бухгалтерия по ходам
        self.client = client or OpenAI(
            base_url="https://openrouter.ai/api/v1",
            api_key=os.environ["OPENROUTER_API_KEY"],
        )

    def _build_messages(self):
        """РОЛЬ + скользящее окно истории (последние max_turns ходов).
        Окно режет только то, что ШЛЁМ модели; на диске история полная."""
        window = self.history[-self.max_turns * 2:]
        return [{"role": "system", "content": self.system_prompt}, *window]

    def _remember(self, msg):
        """Одна точка записи: в список (ОЗУ) и, если есть, на диск."""
        self.history.append(msg)
        if self.memory:
            self.memory.append(msg)

    def _record_turn(self, user_message, usage, sent_messages):
        """НОВОЕ (День 8): сложить по-ходовую строку в бухгалтерскую книгу."""
        u = normalize_usage(usage)
        # ЛОКАЛЬНАЯ прикидка того, что мы отправили — чтобы рядом легло «оценка vs факт».
        estimate = estimate_messages(sent_messages)
        prev_cost = self.ledger[-1]["cumulative_cost"] if self.ledger else 0.0
        cost = as_if_cost(u["prompt_tokens"], u["completion_tokens"]) if u else 0.0
        rec = {
            "turn": len(self.ledger) + 1,
            "user_preview": user_message[:48],
            "estimate_sent": estimate,            # наша оценка входа (до ответа)
            "usage": u,                           # факт с сервера (вход/выход/всего/…)
            "as_if_cost": cost,                   # «как если бы» цена этого хода
            "cumulative_cost": prev_cost + cost,  # нарастающим итогом
            "window": window_for(self.model),     # потолок окна модели
        }
        self.ledger.append(rec)
        return rec

    def send(self, user_message, printer=None):
        """Принять реплику → вызвать LLM (стрим) → запомнить → записать токены → вернуть ответ."""
        self._remember({"role": "user", "content": user_message})
        messages = self._build_messages()
        self.last_sent = messages

        kwargs = {"model": self.model, "messages": messages, "stream": True}
        if self.temperature is not None:
            kwargs["temperature"] = self.temperature
        if self.reasoning_effort:
            kwargs["extra_body"] = {"reasoning": {"effort": self.reasoning_effort}}

        reply, usage = "", None
        for attempt in range(4):              # до 4 попыток при лимите 429
            reply, usage = "", None
            try:
                stream = self.client.chat.completions.create(**kwargs)
                for chunk in stream:
                    # текст — в choices; usage — в ОТДЕЛЬНОМ финальном чанке
                    # (на OpenRouter приходит всегда, без stream_options).
                    if chunk.choices and chunk.choices[0].delta.content:
                        token = chunk.choices[0].delta.content
                        reply += token
                        if printer:
                            printer(token)
                    if getattr(chunk, "usage", None):
                        usage = chunk.usage
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
        if usage is not None:
            self._record_turn(user_message, usage, messages)
        return reply

    def complete(self, messages, max_tokens=None):
        """Один НЕ-стримовый вызов произвольных messages (для демо-сценариев).
        Возвращает (текст_ответа, usage). Сюда НИЧЕГО не пишется в историю —
        это «лабораторный» вызов, чтобы показать поведение, не пачкая диалог."""
        kwargs = {"model": self.model, "messages": messages}
        if max_tokens is not None:
            kwargs["max_tokens"] = max_tokens
        if self.reasoning_effort:
            kwargs["extra_body"] = {"reasoning": {"effort": self.reasoning_effort}}
        r = self.client.chat.completions.create(**kwargs)
        return r.choices[0].message.content, r.usage

    def reset(self):
        """Стереть разговор: ОЗУ + диск + бухгалтерию."""
        self.history = []
        self.ledger = []
        if self.memory:
            self.memory.clear()
