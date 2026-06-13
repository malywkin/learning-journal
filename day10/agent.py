"""День 10 — агент с ПЕРЕКЛЮЧАЕМЫМИ стратегиями контекста (наследие Дней 6–9).

Тот же класс Agent, что в Дне 9, но «что слать в модель» он делегирует не
сжатию, а одной из ТРЁХ стратегий Дня 10 (strategies.py). Агенту всё равно,
какую стратегию дали, — и её можно МЕНЯТЬ на лету (set_context) — это и есть
«переключатель» из задания.

Что нового против Дня 9:
  • self.context — любая из SlidingWindow / StickyFacts / Branching; set_context()
    переключает её в рантайме;
  • make_extractor() — вместо суммаризатора (День 9): отдельный вызов LLM, который
    обновляет карточку фактов по guardrail-инструкции (temperature=0). Его токены
    копятся в стратегии (СВОЯ цена facts), в ledger идут как facts_tokens;
  • поддержка веток: если стратегия — Branching, историю ведёт ОНА (trunk+дельта),
    а не плоский self.history. Агент это прячет за _remember()/_current_history().
"""
import os
import time

from openai import OpenAI, RateLimitError

from strategies import Branching, SlidingWindow, StickyFacts
from tokens import as_if_cost, estimate_messages, normalize_usage, window_for


class Agent:
    def __init__(self, system_prompt, model, memory=None, client=None, name="Агент",
                 context=None, temperature=None, reasoning_effort="low"):
        self.name = name
        self.system_prompt = system_prompt
        self.model = model
        self.temperature = temperature
        self.reasoning_effort = reasoning_effort
        self.memory = memory
        self.history = memory.load() if memory else []
        self.last_sent = []
        self.ledger = []
        self.branches = None                          # ставится в set_context, если ветки
        self.set_context(context or SlidingWindow())  # СТРАТЕГИЯ по умолчанию — окно
        self.client = client or OpenAI(
            base_url="https://openrouter.ai/api/v1",
            api_key=os.environ["OPENROUTER_API_KEY"],
        )

    # ── переключатель стратегий ───────────────────────────────────────────
    def set_context(self, strategy):
        """Сменить стратегию на лету. Если это ветки — историю отныне ведёт
        менеджер веток (trunk+дельта), а не плоский self.history."""
        self.context = strategy
        self.branches = strategy if isinstance(strategy, Branching) else None
        return strategy

    def _current_history(self):
        """Источник истории: для веток — активная линия (ствол+дельта),
        иначе — плоский список агента."""
        return self.branches.history() if self.branches else self.history

    def _build_messages(self):
        """Сборку делегируем стратегии. Окно/facts шлют последние N (+карточку);
        ветки — всю эффективную историю активной ветки."""
        return self.context.build(self.system_prompt, self._current_history())

    def _remember(self, msg):
        if self.branches:
            self.branches.add(msg)            # в ветках историей владеет менеджер
        else:
            self.history.append(msg)
            if self.memory:
                self.memory.append(msg)

    # ── обновлятель карточки фактов (для StickyFacts) ─────────────────────
    def make_extractor(self, max_tokens=200):
        """Вернуть функцию-обновлятель карточки для StickyFacts.

        Это ОТДЕЛЬНЫЙ вызов LLM (то, чем facts платит против окна): даём guardrail,
        текущую карточку и новое сообщение пользователя — получаем обновлённую
        карточку. temperature=0 — без «полёта фантазии» (на слабой модели высокая
        температура усиливает выдумывание; для фактов нужна точность)."""
        def extract(old_facts, user_message, guardrail):
            prev = (f"ТЕКУЩАЯ КАРТОЧКА (сохрани все её поля целиком):\n{old_facts}\n\n"
                    if old_facts else "ТЕКУЩАЯ КАРТОЧКА: (пусто)\n\n")
            user = (f"{prev}НОВОЕ СООБЩЕНИЕ ПОЛЬЗОВАТЕЛЯ:\n{user_message}\n\n"
                    "Верни обновлённую карточку: сначала перенеси ВСЕ прежние поля без потерь, "
                    "потом добавь/измени то, что есть в новом сообщении. Строго по правилам.")
            msgs = [{"role": "system", "content": guardrail},
                    {"role": "user", "content": user}]
            text, usage = self.complete(msgs, max_tokens=max_tokens, temperature=0)
            return text, usage
        return extract

    # ── учёт токенов ──────────────────────────────────────────────────────
    def _record_turn(self, user_message, usage, sent_messages):
        u = normalize_usage(usage)
        estimate = estimate_messages(sent_messages)
        prev_cost = self.ledger[-1]["cumulative_cost"] if self.ledger else 0.0
        cost = as_if_cost(u["prompt_tokens"], u["completion_tokens"]) if u else 0.0
        facts_tokens = self._facts_tokens_delta()     # цена обновления карточки в этом ходу
        rec = {
            "turn": len(self.ledger) + 1,
            "user_preview": user_message[:48],
            "estimate_sent": estimate,
            "usage": u,
            "facts_tokens": facts_tokens,             # 0 для окна/веток; >0 для facts
            "as_if_cost": cost,
            "cumulative_cost": prev_cost + cost,
            "window": window_for(self.model),
        }
        self.ledger.append(rec)
        return rec

    def _facts_tokens_delta(self):
        """Сколько ВСЕГО токенов потратили обновления карточки минус уже учтённое
        в прошлых ходах — чтобы на каждый ход пришёлся только новый расход."""
        usages = getattr(self.context, "extract_usage", [])
        total = sum((normalize_usage(u) or {}).get("total_tokens") or 0 for u in usages)
        prev = sum(r.get("facts_tokens", 0) for r in self.ledger)
        return max(0, total - prev)

    # ── основной ход диалога ──────────────────────────────────────────────
    def send(self, user_message, printer=None):
        self._remember({"role": "user", "content": user_message})
        if isinstance(self.context, StickyFacts):     # facts: догнать карточку по истории
            self.context.sync(self.history)            # (новую реплику + всё, что ещё не учли)
        messages = self._build_messages()             # стратегия решает, что реально уйдёт
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
        """Один НЕ-стримовый вызов произвольных messages (для демо и обновления
        карточки). В историю НИЧЕГО не пишет. Возвращает (текст, usage)."""
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
        if isinstance(self.context, Branching):
            self.set_context(Branching())
        if self.memory:
            self.memory.clear()
