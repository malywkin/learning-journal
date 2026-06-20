"""День 12 — агент с персонализацией поверх модели памяти Дня 11.

Тот же класс Agent (вызов LLM, стрим, retry на 429, учёт токенов из Дня 8). Память
делегируется MemoryModel (memory_layers.py), но долговременный слой теперь ПРОФИЛЬ
из двух частей. Ход диалога:

  send(query):
    1) memory.observe(query)        — краткосрочная (без решения) + РОУТИНГ: рабочая
                                       память + автонаполнение профиля (что заметили);
    2) memory.build(...)            — собрать запрос, подмешав ПРОФИЛЬ в каждый запрос;
    3) вызов LLM (стрим);
    4) memory.see_reply(reply)      — ответ в краткосрочную.

Два служебных вызова LLM (оба temperature=0 — точность важнее фантазии):
  make_router()     — обновляет рабочую карточку и «замечено автоматически» (Дня 11);
  make_normalizer() — новое в Дне 12: фразу пользователя о предпочтениях приводит к
                      аккуратной карточке заданных предпочтений (stated).
"""
import os
import time

from openai import OpenAI, RateLimitError

from memory_layers import MemoryModel, NORMALIZER_GUARDRAIL, ROUTER_GUARDRAIL
from tokens import as_if_cost, estimate_messages, normalize_usage, window_for


class Agent:
    def __init__(self, system_prompt, model, client=None, name="Ассистент",
                 short_keep=6, paths=None, reasoning_effort="low"):
        self.name = name
        self.system_prompt = system_prompt
        self.model = model
        self.reasoning_effort = reasoning_effort
        self.last_sent = []
        self.ledger = []
        self.client = client or OpenAI(
            base_url="https://openrouter.ai/api/v1",
            api_key=os.environ["OPENROUTER_API_KEY"],
        )
        # модель памяти получает наши служебные вызовы (DI, как extractor в Дне 10)
        self.memory = MemoryModel(self.make_router(), self.make_normalizer(),
                                  short_keep=short_keep, paths=paths)

    # ── роутер записи (рабочая + автонаполнение профиля) ───────────────────
    def make_router(self, max_tokens=400):
        """Вернуть функцию-роутер для MemoryModel: даём guardrail + обе текущие
        карточки + новую реплику, получаем обе обновлённые карточки с разметкой
        «=== РАБОЧАЯ === / === О ПОЛЬЗОВАТЕЛЕ ===». Решение о слое примет КОД,
        разобрав эту разметку (memory_layers.parse_router_output)."""
        def route(user_message, working_text, noticed_text):
            user = (
                f"ТЕКУЩАЯ РАБОЧАЯ КАРТОЧКА:\n{working_text or '(пусто)'}\n\n"
                f"ТЕКУЩАЯ КАРТОЧКА О ПОЛЬЗОВАТЕЛЕ:\n{noticed_text or '(пусто)'}\n\n"
                f"НОВАЯ РЕПЛИКА ПОЛЬЗОВАТЕЛЯ:\n{user_message}\n\n"
                "Верни обе карточки в требуемом формате (сначала перенеси все прежние "
                "поля без потерь, затем добавь/измени по новой реплике, в нужную секцию)."
            )
            msgs = [{"role": "system", "content": ROUTER_GUARDRAIL},
                    {"role": "user", "content": user}]
            return self.complete(msgs, max_tokens=max_tokens, temperature=0)
        return route

    # ── нормализатор заданных предпочтений (новое в Дне 12) ─────────────────
    def make_normalizer(self, max_tokens=300):
        """Вернуть функцию для MemoryModel.state_preference: фразу пользователя о
        предпочтениях + текущую карточку stated → обновлённая карточка stated."""
        def normalize(preference_text, stated_text):
            user = (
                f"ТЕКУЩАЯ КАРТОЧКА ПРЕДПОЧТЕНИЙ:\n{stated_text or '(пусто)'}\n\n"
                f"НОВАЯ ФРАЗА ПОЛЬЗОВАТЕЛЯ О ПРЕДПОЧТЕНИЯХ:\n{preference_text}\n\n"
                "Верни обновлённую карточку (перенеси прежние поля, добавь/перезапиши "
                "по новой фразе)."
            )
            msgs = [{"role": "system", "content": NORMALIZER_GUARDRAIL},
                    {"role": "user", "content": user}]
            return self.complete(msgs, max_tokens=max_tokens, temperature=0)
        return normalize

    # ── учёт токенов (как День 8/10) ──────────────────────────────────────
    def _record_turn(self, user_message, usage, sent_messages):
        u = normalize_usage(usage)
        prev_cost = self.ledger[-1]["cumulative_cost"] if self.ledger else 0.0
        cost = as_if_cost(u["prompt_tokens"], u["completion_tokens"]) if u else 0.0
        rec = {
            "turn": len(self.ledger) + 1,
            "user_preview": user_message[:48],
            "estimate_sent": estimate_messages(sent_messages),
            "usage": u,
            "router_tokens": self._router_tokens_delta(),   # цена роутинга в этом ходу
            "as_if_cost": cost,
            "cumulative_cost": prev_cost + cost,
            "window": window_for(self.model),
        }
        self.ledger.append(rec)
        return rec

    def _router_tokens_delta(self):
        """Токены вызовов роутера, ещё не отнесённые на прошлые ходы (своя цена памяти)."""
        total = sum((normalize_usage(u) or {}).get("total_tokens") or 0
                    for u in self.memory.route_usage)
        prev = sum(r.get("router_tokens", 0) for r in self.ledger)
        return max(0, total - prev)

    # ── основной ход ──────────────────────────────────────────────────────
    def send(self, user_message, printer=None, use_profile=True, use_working=True):
        """Принять реплику (краткосрочная + роутинг), собрать запрос с выбранными
        слоями, получить ответ. use_profile/use_working — рычаги для демо «как
        слой меняет ответ» (выключи профиль — увидишь ответ без персонализации)."""
        self.memory.observe(user_message)             # запись по слоям (роутер)
        messages = self.memory.build(self.system_prompt,
                                     use_profile=use_profile, use_working=use_working)
        self.last_sent = messages

        kwargs = {"model": self.model, "messages": messages, "stream": True}
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

        self.memory.see_reply(reply)
        if usage is not None:
            self._record_turn(user_message, usage, messages)
        return reply

    def complete(self, messages, max_tokens=None, temperature=None):
        """Один НЕ-стримовый вызов произвольных messages (роутер и демо). В память
        ничего не пишет. Возвращает (текст, usage)."""
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
        self.ledger = []
        self.memory.clear_all()
