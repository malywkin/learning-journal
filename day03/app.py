"""День 3 — GUI для сравнения 4 способов рассуждения.

Одна задача решается всеми 4 способами; ответы — в компактных прокручиваемых
карточках рядом, с числом токенов в шапке, чтобы сравнивать наглядно.

В списке «Готовые задачи» есть варианты С ЛОВУШКОЙ — на них прямой ответ часто
ошибается, а пошагово/эксперты исправляют. Так видно РАЗНИЦУ между способами.

Запуск:  python app.py   →   http://127.0.0.1:7860
"""

import gradio as gr

import task3
from task3 import (
    MODEL_INSTRUCT,
    MODEL_REASONING,
    TASK,
    method_cot,
    method_direct,
    method_experts,
    method_self_prompt,
)

# Готовые задачи. Первая — наш основной вопрос (пробел в праве -> способы разойдутся).
# Второй — ещё один пробел. Третий — КОНТРАСТ: вопрос с прямым ответом (сойдутся).
PRESETS = {
    "Право: наследование цифровых активов (пробел)": TASK,
    "Право: ответственность за вред от ИИ (пробел)": (
        "По российскому праву. Автономная система ИИ (например, беспилотный "
        "автомобиль) самостоятельно приняла решение и причинила вред человеку. "
        "Кто несёт юридическую ответственность: владелец, производитель, "
        "разработчик ПО или никто? Прямого регулирования нет. "
        "Дай юридически обоснованный ответ."
    ),
    "Контраст: есть прямой ответ (сойдутся)": (
        "По российскому праву. Какой общий срок исковой давности установлен "
        "Гражданским кодексом РФ? Дай краткий ответ."
    ),
}


def solve(task_text, model_label):
    """Генератор: прогоняет 4 способа и отдаёт обновления карточек по мере готовности.

    yield нужен, чтобы окно заполнялось постепенно, а не висело пустым, пока все
    4 запроса (по сути 5 — у способа 3 их два) сходят в API.
    """
    model = MODEL_REASONING if model_label == "reasoning" else MODEL_INSTRUCT
    task3.TASK = task_text  # подменяем задачу на введённую в окне

    # Стартовое состояние: 4 карточки «в процессе».
    state = [gr.update(value="⏳ думаю…", label=name) for name in NAMES]
    yield tuple(state)

    ans, tok = method_direct(model)
    state[0] = gr.update(value=ans, label=f"{NAMES[0]} · {tok} ток.")
    yield tuple(state)

    ans, tok = method_cot(model)
    state[1] = gr.update(value=ans, label=f"{NAMES[1]} · {tok} ток.")
    yield tuple(state)

    ans, tok, gen_prompt = method_self_prompt(model)
    state[2] = gr.update(
        value=f"[Промпт, который модель составила себе]\n{gen_prompt}\n\n"
        f"{'-' * 40}\n[Ответ по нему]\n{ans}",
        label=f"{NAMES[2]} · {tok} ток.",
    )
    yield tuple(state)

    ans, tok = method_experts(model)
    state[3] = gr.update(value=ans, label=f"{NAMES[3]} · {tok} ток.")
    yield tuple(state)


NAMES = [
    "1 · Прямой ответ",
    "2 · Пошагово (CoT)",
    "3 · Сам составил промпт",
    "4 · Эксперты (Теоретик/Практик/Критик)",
]

# Текстбоксы лучше markdown: фиксированная высота + прокрутка внутри = нет «простыни».
BOX = dict(lines=16, max_lines=16, interactive=False)

with gr.Blocks(title="День 3 — 4 способа рассуждения") as demo:
    gr.Markdown(
        "## День 3 — один юр. вопрос, 4 способа думать\n"
        "Выбери задачу, нажми **Решить**. Сравни ответы и число токенов. "
        "На вопросе с пробелом в праве прямой ответ беднее, а эксперты "
        "разворачивают аналогию и контрдоводы."
    )

    with gr.Row():
        preset = gr.Dropdown(
            choices=list(PRESETS.keys()),
            value=list(PRESETS.keys())[0],
            label="Готовая задача",
            scale=3,
        )
        model_in = gr.Radio(
            ["instruct", "reasoning"],
            value="instruct",
            label="Модель",
            info="instruct = думает по просьбе · reasoning = думает всегда сама",
            scale=2,
        )
        run = gr.Button("▶ Решить", variant="primary", scale=1)

    task_in = gr.Textbox(value=TASK, label="Текст задачи (можно править)", lines=3)

    with gr.Row(equal_height=True):
        b1 = gr.Textbox(label=NAMES[0], **BOX)
        b2 = gr.Textbox(label=NAMES[1], **BOX)
    with gr.Row(equal_height=True):
        b3 = gr.Textbox(label=NAMES[2], **BOX)
        b4 = gr.Textbox(label=NAMES[3], **BOX)

    # Выбор готовой задачи -> подставляем её текст в поле.
    preset.change(lambda k: PRESETS[k], inputs=preset, outputs=task_in)
    run.click(solve, inputs=[task_in, model_in], outputs=[b1, b2, b3, b4])

if __name__ == "__main__":
    demo.launch()
