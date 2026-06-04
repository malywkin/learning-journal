"""Графический интерфейс ко Дню 2 (Gradio).

Окно в браузере: вводишь один вопрос → видишь два ответа рядом.
Слева — без контроля (raw), справа — с контролем (формат + длина + стоп).
Логика запроса переиспользуется из task2.py — здесь только «обёртка-витрина».
"""

import gradio as gr

# Берём готовые функции из task2.py — не дублируем логику запроса.
# (input() в task2.py не сработает: он спрятан под `if __name__ == "__main__"`.)
from task2 import ask_raw, ask_controlled


def _meta(response):
    """Служебная строка: почему остановилось и сколько токенов потрачено."""
    choice = response.choices[0]
    tokens = response.usage.completion_tokens if response.usage else "?"
    return f"`finish_reason = {choice.finish_reason}` · токенов: **{tokens}**"


def compare(question):
    """Один вопрос → два режима. Возвращает 4 значения под 4 поля интерфейса."""
    if not question.strip():
        return "Сначала введите вопрос.", "", "", ""
    raw = ask_raw(question)
    ctl = ask_controlled(question)
    return (
        raw.choices[0].message.content,
        _meta(raw),
        ctl.choices[0].message.content,
        _meta(ctl),
    )


with gr.Blocks(title="День 2 — Формат ответа") as demo:
    gr.Markdown(
        "# День 2 — Формат ответа\n"
        "Один и тот же вопрос уходит в модель дважды. "
        "**Слева** — без ограничений. **Справа** — с контролем формата, длины и завершения."
    )
    question = gr.Textbox(
        label="Ваш вопрос к LLM",
        placeholder="Например: Расскажи, что такое Python",
    )
    btn = gr.Button("Сравнить", variant="primary")

    with gr.Row():
        with gr.Column():
            gr.Markdown("### Без контроля (raw)")
            raw_out = gr.Markdown()
            raw_meta = gr.Markdown()
        with gr.Column():
            gr.Markdown("### С контролем (формат + длина + стоп)")
            ctl_out = gr.Markdown()
            ctl_meta = gr.Markdown()

    outputs = [raw_out, raw_meta, ctl_out, ctl_meta]
    btn.click(compare, inputs=question, outputs=outputs)
    question.submit(compare, inputs=question, outputs=outputs)  # Enter тоже запускает


if __name__ == "__main__":
    # Поднимаем локальный сервер на http://127.0.0.1:7860
    demo.launch()
