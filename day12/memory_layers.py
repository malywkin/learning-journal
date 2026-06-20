"""День 12 — ПЕРСОНАЛИЗАЦИЯ поверх модели памяти Дня 11.

День 11 дал три слоя памяти (краткосрочная/рабочая/долговременная) и роутер,
который сам решает, что куда сохранить. День 12 углубляет ДОЛГОВРЕМЕННЫЙ слой и
превращает его в настоящий ПРОФИЛЬ пользователя, который влияет на КАЖДЫЙ ответ.

Что нового по сравнению с Днём 11:
  • Профиль кормится из ДВУХ источников, и они хранятся раздельно:
      stated  — ЗАДАННОЕ пользователем явно («пиши кратко», «я юрист»). Это «опишите
                предпочтения» из задания. Может быть пустым — необязательно.
      noticed — ЗАМЕЧЕННОЕ ассистентом САМ, по ходу диалога (роутер). Это ответ на
                пункт задания «что ассистент учитывает автоматически».
    Почему раздельно: stated — твоя воля, noticed — догадки машины. Доверие разное,
    поэтому при сборке запроса stated идёт ВЫШЕ по приоритету (см. UserProfile.block).
  • Профиль подмешивается в КАЖДЫЙ запрос (build) с явным правилом приоритета:
        текущая реплика  >  заданные предпочтения  >  замеченное автоматически.
    Это рекомендация кукбука OpenAI (context engineering): свежее намерение
    пользователя не должно перебиваться устаревшим или угаданным профилем.

Тренд 2026 (из разведки темы): продуктовые ассистенты (ChatGPT «Dreaming», память
Claude/Gemini) ушли от «пользователь руками пишет профиль» к АВТОВЫВОДУ профиля из
диалогов. Поэтому ручной ввод у нас — минимум (одна фраза), основную работу делает
автонаполнение noticed. Антипаттерн, которого избегаем: пихать весь профиль целиком
в каждый запрос (context rot) — поэтому профиль это короткая карточка, не простыня.

Хранение раздельно (как в Дне 11): свой файл на каждую часть памяти.
"""
import json
import os


# ──────────────────────────────────────────────────────────────────────────
# Краткосрочная память — диалог (окно на чтении). Роутер ей не нужен. (Из Дня 11.)
# ──────────────────────────────────────────────────────────────────────────
class DialogMemory:
    """Список реплик диалога. На запись — просто append (без решения).
    На чтение — окно последних keep_last. Персистится в свой файл, если задан path."""

    def __init__(self, path=None, keep_last=6):
        self.path = path
        self.keep_last = keep_last
        self.messages = self._load()

    def _load(self):
        if self.path and os.path.exists(self.path):
            with open(self.path, encoding="utf-8") as f:
                return json.load(f)
        return []

    def _save(self):
        if not self.path:
            return
        tmp = self.path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(self.messages, f, ensure_ascii=False, indent=2)
        os.replace(tmp, self.path)

    def append(self, msg):
        self.messages.append(msg)
        self._save()

    def window(self):
        return self.messages[-self.keep_last:] if self.keep_last else list(self.messages)

    def dropped(self):
        return max(0, len(self.messages) - self.keep_last) if self.keep_last else 0

    def clear(self):
        self.messages = []
        self._save()


# ──────────────────────────────────────────────────────────────────────────
# Карточка «ключ: значение» в своём файле (из Дня 11). Кирпичик и для рабочей
# памяти, и для обеих частей профиля.
# ──────────────────────────────────────────────────────────────────────────
class CardMemory:
    """Карточка фактов (строки «ключ: значение») в своём файле. Отдельные поля,
    а не проза-пересказ — меньше дрейфа (поле либо точное, либо его нет). Текст
    карточки формирует вызов LLM (роутер/нормализатор); класс только хранит."""

    def __init__(self, name, path=None):
        self.name = name
        self.path = path
        self.text = self._load()

    def _load(self):
        if self.path and os.path.exists(self.path):
            with open(self.path, encoding="utf-8") as f:
                return f.read().strip()
        return ""

    def set(self, text):
        self.text = (text or "").strip()
        if self.path:
            tmp = self.path + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                f.write(self.text)
            os.replace(tmp, self.path)

    def fields(self):
        out = []
        for line in self.text.splitlines():
            line = line.strip()
            if not line:
                continue
            i = line.find(":")
            out.append((line[:i].strip(), line[i + 1:].strip()) if i > 0 else ("", line))
        return out

    def clear(self):
        self.set("")


# ──────────────────────────────────────────────────────────────────────────
# ПРОФИЛЬ — сердце Дня 12. Долговременный слой Дня 11, разведённый на два источника.
# ──────────────────────────────────────────────────────────────────────────
class UserProfile:
    """Профиль пользователя = две раздельные карточки.

    stated  — пользователь задал САМ (через нормализатор: фраза → поля). Высокий вес.
    noticed — ассистент заметил САМ (роутер по диалогу). Это «учитывает автоматически».

    block() собирает текст для подмешивания в запрос с правилом приоритета — именно
    он делает ассистента персональным."""

    def __init__(self, path_stated=None, path_noticed=None):
        self.stated = CardMemory("заданные предпочтения", path_stated)
        self.noticed = CardMemory("замечено автоматически", path_noticed)

    def is_empty(self):
        return not (self.stated.text or self.noticed.text)

    def block(self):
        """Текст профиля для системного сообщения. Внутри — правило приоритета и
        обе части по убыванию доверия. Пустые части не упоминаем."""
        parts = [
            "ПРОФИЛЬ ПОЛЬЗОВАТЕЛЯ — применяй к КАЖДОМУ ответу (стиль, формат, "
            "ограничения). Если пользователь прямо в текущей реплике просит иначе — "
            "слушай текущую реплику, она важнее профиля. Заданные пользователем "
            "предпочтения важнее замеченных автоматически."
        ]
        if self.stated.text:
            parts.append("Заданные пользователем предпочтения:\n" + self.stated.text)
        if self.noticed.text:
            parts.append("Замечено автоматически по ходу диалога:\n" + self.noticed.text)
        return "\n\n".join(parts)

    def clear(self):
        self.stated.clear()
        self.noticed.clear()

    def view(self):
        return {
            "stated": {"text": self.stated.text, "fields": self.stated.fields()},
            "noticed": {"text": self.noticed.text, "fields": self.noticed.fields()},
        }


# ──────────────────────────────────────────────────────────────────────────
# Роутер записи (из Дня 11): за один вызов обновляет рабочую карточку и часть
# профиля «замечено автоматически». Это и есть автонаполнение профиля.
# ──────────────────────────────────────────────────────────────────────────
ROUTER_GUARDRAIL = (
    "Ты — РОУТЕР памяти ассистента. Тебе дают НОВУЮ реплику пользователя и две "
    "карточки: РАБОЧУЮ (данные текущей задачи) и КАРТОЧКУ «О ПОЛЬЗОВАТЕЛЕ» (его "
    "устойчивые предпочтения и привычки, замеченные по ходу диалога). Верни ОБЕ "
    "карточки в обновлённом виде.\n\n"
    "Куда что относится:\n"
    "• РАБОЧАЯ — факты ТЕКУЩЕЙ задачи: бюджет и сроки этого проекта, выбранный для "
    "него стек, принятые по нему решения. Признак — «в этом проекте / сейчас / для "
    "этой задачи». Закончится задача — эти факты станут не нужны.\n"
    "• О ПОЛЬЗОВАТЕЛЕ — устойчивое про самого человека, прежде всего КАК ОН ЛЮБИТ "
    "ОТВЕТЫ: краткость или подробность, нужен ли код/примеры/таблицы, тон; его роль; "
    "постоянные запреты и привычки. Признак — «всегда / вообще / я такой / терпеть не "
    "могу / отвечай мне…». Пригодится и в следующих, не связанных задачах.\n\n"
    "Две развилки на КАЖДУЮ реплику:\n"
    "1) Есть ли тут вообще что запоминать? Болтовня, «окей, дальше», вопросы без "
    "новых данных — НЕ запоминаем (обе карточки оставляем как есть).\n"
    "2) Если факт есть — он про ЗАДАЧУ или про ПОЛЬЗОВАТЕЛЯ? Положи в нужную секцию.\n\n"
    "Правила строго:\n"
    "a) Сначала ПЕРЕНЕСИ каждую карточку целиком, со ВСЕМИ полями дословно — копируй "
    "прежние строки БУКВА В БУКВУ, НЕ переводи ключи на другой язык и не "
    "переформулируй. Потом добавь/измени только то, что прямо есть в новой реплике.\n"
    "b) НИЧЕГО не выдумывай: нет факта в тексте реплики — нет нового поля.\n"
    "c) Одно значение на ключ; передумал пользователь — перезапиши поле.\n"
    "d) Формат карточек — короткие строки «ключ: значение», без пояснений.\n"
    "e) Если для секции нового нет — верни её прежнее содержимое без изменений.\n\n"
    "Формат ОТВЕТА строго такой (ровно эти два разделителя; пустая карточка = пустая "
    "строка):\n"
    "=== РАБОЧАЯ ===\n"
    "<строки рабочей карточки>\n"
    "=== О ПОЛЬЗОВАТЕЛЕ ===\n"
    "<строки карточки о пользователе>"
)

W_MARK = "=== РАБОЧАЯ ==="
U_MARK = "=== О ПОЛЬЗОВАТЕЛЕ ==="


def parse_router_output(text, prev_working, prev_noticed):
    """Разобрать ответ роутера на две карточки. Если разметку не нашли (слабая
    модель сорвалась) — НЕ трогаем карточки (возвращаем прежние), чтобы кривой
    ответ не стёр память. Предохранитель против срыва (из Дня 11)."""
    if not text or W_MARK not in text or U_MARK not in text:
        return prev_working, prev_noticed, False
    after_w = text.split(W_MARK, 1)[1]
    working, noticed = after_w.split(U_MARK, 1)
    return working.strip(), noticed.strip(), True


# ──────────────────────────────────────────────────────────────────────────
# Нормализатор ЗАДАННЫХ предпочтений — новое в Дне 12. Превращает свободную фразу
# пользователя («пиши кратко, я юрист») в аккуратные поля карточки stated.
# ──────────────────────────────────────────────────────────────────────────
NORMALIZER_GUARDRAIL = (
    "Ты приводишь ПРЕДПОЧТЕНИЯ пользователя к аккуратной карточке. Тебе дают текущую "
    "карточку предпочтений и новую фразу пользователя о том, как он хочет получать "
    "ответы. Верни ОБНОВЛЁННУЮ карточку — и больше ничего.\n\n"
    "Поля бери из этого набора, если они есть во фразе: Роль, Язык, Стиль, Формат, "
    "Ограничения, Тон. Лишних полей не добавляй.\n"
    "Правила: (a) сначала перенеси текущую карточку целиком, поля дословно; "
    "(b) добавь/перезапиши только то, что прямо сказано во фразе; (c) ничего не "
    "выдумывай; (d) формат — короткие строки «ключ: значение», без пояснений и "
    "вступлений. Верни только карточку."
)


# ──────────────────────────────────────────────────────────────────────────
# Модель памяти Дня 12: три слоя, но долговременный — это профиль (две части).
# ──────────────────────────────────────────────────────────────────────────
class MemoryModel:
    """Контейнер слоёв + роутер (автонаполнение профиля) + нормализатор (заданные
    предпочтения) + сборка запроса с приоритетом профиля.

    router_fn(user_message, working_text, noticed_text)   -> (raw_text, usage)
    normalizer_fn(preference_text, stated_text)           -> (raw_text, usage)
    Оба — вызовы LLM, их даёт агент. Память не знает, КАК зовётся модель."""

    def __init__(self, router_fn, normalizer_fn, short_keep=6, paths=None):
        paths = paths or {}
        self.short = DialogMemory(paths.get("dialog"), keep_last=short_keep)
        self.working = CardMemory("рабочая", paths.get("working"))
        self.profile = UserProfile(paths.get("stated"), paths.get("noticed"))
        self.router_fn = router_fn
        self.normalizer_fn = normalizer_fn
        self.routes = []            # лог решений роутера (для капота/демо)
        self.route_usage = []       # usage вызовов роутера+нормализатора = цена памяти

    # ── ЗАПИСЬ ────────────────────────────────────────────────────────────
    def see_dialog(self, msg):
        self.short.append(msg)

    def route(self, user_message):
        """Автонаполнение: роутер обновляет рабочую и «замечено автоматически».
        Это про пункт задания «что ассистент учитывает автоматически»."""
        before_w, before_n = self.working.text, self.profile.noticed.text
        raw, usage = self.router_fn(user_message, before_w, before_n)
        new_w, new_n, ok = parse_router_output(raw, before_w, before_n)
        self.working.set(new_w)
        self.profile.noticed.set(new_n)
        if usage is not None:
            self.route_usage.append(usage)
        trace = {
            "message": user_message[:60],
            "parsed": ok,
            "to_working": _diff(before_w, new_w),
            "to_noticed": _diff(before_n, new_n),
            "saved_nothing": (before_w == new_w and before_n == new_n),
        }
        self.routes.append(trace)
        return trace

    def state_preference(self, preference_text):
        """ЗАДАННОЕ пользователем: фразу о предпочтениях нормализуем в карточку
        stated. Это «опишите предпочтения» из задания — рукой пользователя."""
        before = self.profile.stated.text
        raw, usage = self.normalizer_fn(preference_text, before)
        self.profile.stated.set((raw or before).strip())
        if usage is not None:
            self.route_usage.append(usage)
        return {"before": before, "after": self.profile.stated.text,
                "added": _diff(before, self.profile.stated.text)}

    def observe(self, user_message):
        """Полный приём реплики: краткосрочная (без решения) + автонаполнение."""
        self.see_dialog({"role": "user", "content": user_message})
        return self.route(user_message)

    # ── ЧТЕНИЕ ────────────────────────────────────────────────────────────
    def build(self, system_prompt, use_profile=True, use_working=True):
        """Собрать запрос, подмешивая профиль (если use_profile) и рабочую память.
        Профиль идёт в КАЖДЫЙ запрос — на этом и держится персонализация. Порядок
        сообщений задаёт приоритет: системная роль и профиль раньше, реальный
        диалог (включая текущую реплику) — последним, поэтому свежее намерение
        пользователя перевешивает профиль."""
        msgs = [{"role": "system", "content": system_prompt}]
        if use_profile and not self.profile.is_empty():
            msgs.append({"role": "system", "content": self.profile.block()})
        if use_working and self.working.text:
            msgs.append({"role": "system",
                         "content": "Данные текущей задачи (рабочая память):\n"
                                    + self.working.text})
        msgs += self.short.window()
        return msgs

    def see_reply(self, reply):
        self.see_dialog({"role": "assistant", "content": reply})

    # ── управление задачей ────────────────────────────────────────────────
    def new_task(self):
        """Новая задача: рабочую и диалог ОБНУЛЯЕМ, профиль (обе части) ОСТАВЛЯЕМ.
        Профиль про человека — он в силе и в новой задаче."""
        self.working.clear()
        self.short.clear()

    def clear_all(self):
        self.short.clear()
        self.working.clear()
        self.profile.clear()
        self.routes = []
        self.route_usage = []

    def view(self):
        p = self.profile.view()
        return {
            "short": {"messages": self.short.messages, "window": self.short.window(),
                      "keep_last": self.short.keep_last, "dropped": self.short.dropped()},
            "working": {"text": self.working.text, "fields": self.working.fields()},
            "profile": p,
            "profile_block": self.profile.block() if not self.profile.is_empty() else "",
            "routes": self.routes,
        }


def _diff(before, after):
    """Строки, появившиеся/изменившиеся в карточке (грубая трасса для капота)."""
    old = set(l.strip() for l in (before or "").splitlines() if l.strip())
    return [l.strip() for l in (after or "").splitlines()
            if l.strip() and l.strip() not in old]
