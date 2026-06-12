"""День 9 — агент со СЖАТИЕМ ИСТОРИИ (наследие Дней 6–8 + управление контекстом).

Тот же класс Agent, что в Дне 8 (роль + клиент + история + персист + ledger токенов),
но «что слать в модель» он теперь НЕ решает сам, а делегирует СТРАТЕГИИ КОНТЕКСТА:
    NoCompression  — РОЛЬ + вся история (как было);
    RollingSummary — РОЛЬ + копилка-summary + последние N реплик.
Агенту всё равно, какую стратегию дали (инкапсуляция — как с памятью в Дне 7).

Что нового против Дня 8:
  • поле self.context — стратегия сборки сообщений; send() зовёт context.build();
  • make_summarizer() — отдельный (не-стримовый) вызов LLM, который и составляет
    копилку по guardrail-инструкции; его токены копятся в стратегии (СВОЯ цена сжатия);
  • в ledger добавлено поле summary_tokens — сколько токенов ушло на суммаризацию
    в этом ходу (чтобы сравнение «до/после» было ЧЕСТНЫМ: сжатие не бесплатно).
"""
import os
import time

from openai import OpenAI, RateLimitError

from compress import NoCompression
from tokens import as_if_cost, estimate_messages, normalize_usage, window_for


class Agent:
    def __init__(self, system_prompt, model, memory=None, client=None, name="Агент",
                 context=None, temperature=None, reasoning_effort="low"):
        self.name = name
        self.system_prompt = system_prompt
        self.model = model
        self.temperature = temperature
        self.reasoning_effort = reasoning_effort
        self.context = context or NoCompression()   # СТРАТЕГИЯ: что реально слать в модель
        self.memory = memory
        self.history = memory.load() if memory else []
        self.last_sent = []
        self.ledger = []
        self.client = client or OpenAI(
            base_url="https://openrouter.ai/api/v1",
            api_key=os.environ["OPENROUTER_API_KEY"],
        )

    def _build_messages(self):
        """Сборку делегируем стратегии: NoCompression шлёт всё, RollingSummary —
        копилку + окно. Окно/сжатие — это про ПРОМПТ; на диске история всегда полная."""
        return self.context.build(self.system_prompt, self.history)

    def _remember(self, msg):
        self.history.append(msg)
        if self.memory:
            self.memory.append(msg)

    def make_summarizer(self, max_tokens=220):
        """Вернуть функцию-суммаризатор для RollingSummary.

        Это ОТДЕЛЬНЫЙ вызов LLM: даём guardrail-инструкцию (что сохранить),
        предыдущую копилку и новый выпавший кусок — получаем обновлённую копилку.
        Именно тут мы ВЛИЯЕМ на содержимое summary (а не «модель сама решает»).

        temperature=0 — детерминированно и без «полёта фантазии» (на слабой модели
        высокая температура усиливает выдумывание; для выжимки нам нужна точность).
        """
        def summarize(old_summary, chunk, guardrail):
            convo = "\n".join(f"{m['role']}: {m['content']}" for m in chunk)
            prev = f"ПРЕДЫДУЩАЯ СВОДКА:\n{old_summary}\n\n" if old_summary else ""
            user = (f"{prev}НОВЫЙ КУСОК ДИАЛОГА:\n{convo}\n\n"
                    "Верни ОДНУ обновлённую сводку строго по фактам из текста выше.")
            msgs = [{"role": "system", "content": guardrail},
                    {"role": "user", "content": user}]
            text, usage = self.complete(msgs, max_tokens=max_tokens, temperature=0)
            return text, usage
        return summarize

    def _record_turn(self, user_message, usage, sent_messages):
        u = normalize_usage(usage)
        estimate = estimate_messages(sent_messages)
        prev_cost = self.ledger[-1]["cumulative_cost"] if self.ledger else 0.0
        cost = as_if_cost(u["prompt_tokens"], u["completion_tokens"]) if u else 0.0
        # токены, ушедшие на суммаризацию ИМЕННО в этом ходу (новые записи в стратегии)
        summ_tokens = self._summary_tokens_delta()
        rec = {
            "turn": len(self.ledger) + 1,
            "user_preview": user_message[:48],
            "estimate_sent": estimate,
            "usage": u,
            "summary_tokens": summ_tokens,          # цена сжатия этого хода (0, если не срабатывало)
            "as_if_cost": cost,
            "cumulative_cost": prev_cost + cost,
            "window": window_for(self.model),
        }
        self.ledger.append(rec)
        return rec

    def _summary_tokens_delta(self):
        """Сколько ВСЕГО токенов потратила суммаризация на данный момент минус то,
        что уже учли в прошлых ходах. Так на каждый ход приходится только новый расход."""
        usages = getattr(self.context, "summ_usage", [])
        total = sum((normalize_usage(u) or {}).get("total_tokens") or 0 for u in usages)
        prev = sum(r.get("summary_tokens", 0) for r in self.ledger)
        return max(0, total - prev)

    def send(self, user_message, printer=None):
        self._remember({"role": "user", "content": user_message})
        messages = self._build_messages()      # ← тут стратегия может СВЕРНУТЬ старое в копилку
        self.last_sent = messages

        kwargs = {"model": self.model, "messages": messages, "stream": True}
        if self.temperature is not None:
            kwargs["temperature"] = self.temperature
        if self.reasoning_effort:
            kwargs["extra_body"] = {"reasoning": {"effort": self.reasoning_effort}}

        reply, usage = "", None
        for attempt in range(4):
            reply, usage = "", None
            try:
                stream = self.client.chat.completions.create(**kwargs)
                for chunk in stream:
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

    def complete(self, messages, max_tokens=None, temperature=None):
        """Один НЕ-стримовый вызов произвольных messages (для демо и суммаризации).
        В историю НИЧЕГО не пишет — «лабораторный» вызов. Возвращает (текст, usage)."""
        kwargs = {"model": self.model, "messages": messages}
        if max_tokens is not None:
            kwargs["max_tokens"] = max_tokens
        if temperature is not None:
            kwargs["temperature"] = temperature
        if self.reasoning_effort:
            kwargs["extra_body"] = {"reasoning": {"effort": self.reasoning_effort}}
        for attempt in range(4):
            try:
                r = self.client.chat.completions.create(**kwargs)
                return r.choices[0].message.content, r.usage
            except RateLimitError:
                if attempt < 3:
                    time.sleep(3 * (attempt + 1))
                    continue
                raise
        raise RuntimeError("unreachable")

    def reset(self):
        self.history = []
        self.ledger = []
        if self.memory:
            self.memory.clear()
