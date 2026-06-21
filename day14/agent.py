"""День 14 — агент с инвариантами: мягкий слой (правила в промпте) + ЖЁСТКИЙ слой
(страж на выходе проверяет ответ КОДОМ и не пускает нарушение).

Поток одного запроса:
  1. генерируем ответ — в системный промпт кладём правила (мягкий слой: «модель, постарайся»);
  2. СТРАЖ проверяет готовый ответ выбранным детектором (детерминированный / судья / оба);
  3. при нарушении — либо ПЕРЕПИСАТЬ (reject-and-retry с усиленной инструкцией, до N раз),
     либо ОТКАЗАТЬ. Скрытое правило в отказе не называем.

Главное: пункт 2 — настоящий инвариант. Что бы пользователь ни уговорил модель в пункте 1,
страж смотрит результат и режет. Мягкий слой только снижает число срабатываний.
"""
import os
import time

from openai import OpenAI, RateLimitError

from invariants import (InvariantStore, deterministic_check, llm_judge_check)


class GuardedAgent:
    def __init__(self, store: InvariantStore, model="openai/gpt-oss-20b:free",
                 client=None, reasoning_effort="low", max_retries=2):
        self.store = store
        self.model = model
        self.reasoning_effort = reasoning_effort
        self.max_retries = max_retries
        self.client = client or OpenAI(
            base_url="https://openrouter.ai/api/v1",
            api_key=os.environ["OPENROUTER_API_KEY"],
        )

    # ── базовый вызов LLM (не-стрим), retry на лимит ────────────────────────
    def complete(self, system, user, max_tokens=700, temperature=0):
        msgs = [{"role": "system", "content": system},
                {"role": "user", "content": user}]
        kwargs = {"model": self.model, "messages": msgs,
                  "max_tokens": max_tokens, "temperature": temperature}
        if self.reasoning_effort:
            kwargs["extra_body"] = {"reasoning": {"effort": self.reasoning_effort}}
        for attempt in range(4):
            try:
                r = self.client.chat.completions.create(**kwargs)
                return r.choices[0].message.content or ""
            except RateLimitError:
                if attempt < 3:
                    time.sleep(3 * (attempt + 1))
                    continue
                return "[лимит запросов OpenRouter (429) — подожди минуту и повтори]"
            except Exception as e:
                return f"[ошибка вызова LLM: {e}]"
        return ""

    # ── мягкий слой: правила в системный промпт ─────────────────────────────
    # soft=False → правил в промпте НЕТ (модель не предупреждена). Тогда видно, как
    # работает ЖЁСТКИЙ слой: модель свободно нарушает, а страж на выходе ловит и режет.
    def _system_prompt(self, harden=False, soft=True):
        base = "Ты — ассистент-помощник по разработке. Отвечай по делу."
        if soft:
            rules = "\n".join("- %s" % inv.rule for inv in self.store.active())
            base += "\n\nЖЁСТКИЕ ПРАВИЛА, которые нельзя нарушать:\n" + rules
        if harden:
            base += ("\n\nПРОШЛЫЙ ответ нарушил правило. Перепиши ответ так, чтобы ни одно "
                     "правило не нарушалось. Если без нарушения помочь нельзя — вежливо откажись.")
        return base

    # ── СТРАЖ: проверка готового ответа выбранным детектором ────────────────
    def guard(self, text, detector="both"):
        invs = self.store.active()
        result = {"deterministic": [], "judge": None}
        violated_ids = set()
        if detector in ("deterministic", "both"):
            hits = deterministic_check(text, invs)
            result["deterministic"] = hits
            violated_ids.update(h["id"] for h in hits)
        if detector in ("judge", "both"):
            j = llm_judge_check(text, invs, self.complete)
            result["judge"] = j
            if j["violated"]:
                violated_ids.update(j["ids"] or [i.id for i in invs])
        result["violated_ids"] = sorted(violated_ids)
        result["blocked"] = bool(violated_ids)
        return result

    # ── объяснение отказа (скрытые правила не называем) ─────────────────────
    def _refusal(self, violated_ids):
        named, hidden_any = [], False
        for inv in self.store.active():
            if inv.id in violated_ids:
                if inv.hidden:
                    hidden_any = True
                else:
                    named.append(inv.rule)
        if named:
            return "Не могу выполнить запрос: это нарушит правило — " + "; ".join(named) + "."
        if hidden_any:
            return ("Не могу выполнить запрос в таком виде. Давай зайдём с другой стороны — "
                    "предложу допустимый вариант.")
        return "Не могу выполнить запрос: нарушает заданное ограничение."

    # ── полный цикл: ответ → страж → переписать/отказать ───────────────────
    def ask(self, user_msg, detector="both", on_violation="rewrite", soft=True):
        """Возвращает трассу для разбора: первичный ответ, что поймал страж, ретраи, итог.
        soft=False — не предупреждать модель правилами (демо чистого жёсткого слоя)."""
        trace = {"attempts": [], "final": None, "status": None}
        harden = False
        for attempt in range(self.max_retries + 1):
            answer = self.complete(self._system_prompt(harden=harden, soft=soft), user_msg)
            g = self.guard(answer, detector=detector)
            trace["attempts"].append({"answer": answer, "guard": g, "hardened": harden})
            if not g["blocked"]:
                trace["final"] = answer
                trace["status"] = "ok" if attempt == 0 else "fixed"
                return trace
            if on_violation == "refuse":
                trace["final"] = self._refusal(g["violated_ids"])
                trace["status"] = "refused"
                return trace
            harden = True            # rewrite: следующий заход с усиленной инструкцией
        # переписать не помогло за лимит попыток → отказ
        last = trace["attempts"][-1]["guard"]["violated_ids"]
        trace["final"] = self._refusal(last)
        trace["status"] = "refused_after_retries"
        return trace
