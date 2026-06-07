"""День 4 — GUI для сравнения ТЕМПЕРАТУР.

Один и тот же запрос прогоняется при T=0 / 0.7 / 1.2 — три колонки рядом.
В каждой колонке N повторов: видно РАЗНООБРАЗИЕ (при T=0 повторы почти одинаковы,
при T=1.2 — все разные). Снизу — слайдер «своя температура» для живого эксперимента.

Запуск:  python app.py   →   http://127.0.0.1:7860
"""

import gradio as gr

import task4
from task4 import MODEL, TASK, run_temperature, unique_count

# Три точки температуры из задания.
TEMPS = [0.0, 0.7, 1.2]

# Пресеты. Первые — творческие (разброс температур ВИДЕН).
# Последний — КОНТРАСТ: фактический вопрос, где температура почти не влияет.
PRESETS = {
    "Творческая: слоган для кофейни": TASK,
    "Творческая: название для книги о путешествиях во времени": (
        "Придумай оригинальное название для книги о путешествиях во времени. "
        "Дай ОДНО название, без пояснений."
    ),
    "Творческая: первая фраза детективного рассказа": (
        "Напиши одну интригующую первую фразу детективного рассказа."
    ),
    "Контраст: факт (температура почти не влияет)": (
        "В каком году человек впервые высадился на Луну? Ответь одним числом."
    ),
}


def _render(answers):
    """Складывает N повторов в один текст с нумерацией."""
    return "\n\n".join(f"[{i}] {a}" for i, a in enumerate(answers, 1))


def compare(task_text, n_runs):
    """Генератор: прогоняет 3 температуры и заполняет колонки по мере готовности."""
    n_runs = int(n_runs)
    # Стартовое состояние: три колонки «в процессе».
    state = [gr.update(value="⏳ думаю…", label=f"T = {t}") for t in TEMPS]
    yield tuple(state)

    for idx, t in enumerate(TEMPS):
        answers = run_temperature(task_text, t, n_runs)
        uniq = unique_count(answers)
        state[idx] = gr.update(
            value=_render(answers),
            label=f"T = {t} · разных: {uniq} из {n_runs}",
        )
        yield tuple(state)


def custom(task_text, temperature, n_runs):
    """Живой эксперимент: своя температура со слайдера."""
    answers = run_temperature(task_text, float(temperature), int(n_runs))
    uniq = unique_count(answers)
    return gr.update(
        value=_render(answers),
        label=f"Своя T = {temperature} · разных: {uniq} из {int(n_runs)}",
    )


# Текстбоксы с фиксированной высотой и прокруткой — чтобы не было «простыни».
BOX = dict(lines=14, max_lines=14, interactive=False)

with gr.Blocks(title="День 4 — Температура") as demo:
    gr.Markdown(
        "## День 4 — один запрос, три температуры\n"
        f"Модель: `{MODEL}`. Выбери задачу, нажми **Сравнить**. "
        "Слева направо температура растёт: ответы становятся разнообразнее и "
        "креативнее, но менее предсказуемыми. На **творческой** задаче разница "
        "видна; на **фактической** (пресет «Контраст») — почти нет."
    )

    with gr.Row():
        preset = gr.Dropdown(
            choices=list(PRESETS.keys()),
            value=list(PRESETS.keys())[0],
            label="Готовая задача",
            scale=3,
        )
        n_runs = gr.Slider(
            1, 5, value=3, step=1, label="Повторов на температуру", scale=2
        )
        run = gr.Button("▶ Сравнить", variant="primary", scale=1)

    task_in = gr.Textbox(value=TASK, label="Текст запроса (можно править)", lines=2)

    with gr.Row(equal_height=True):
        c0 = gr.Textbox(label="T = 0.0", **BOX)
        c1 = gr.Textbox(label="T = 0.7", **BOX)
        c2 = gr.Textbox(label="T = 1.2", **BOX)

    gr.Markdown("### Живой эксперимент — поставь свою температуру")
    with gr.Row():
        temp_slider = gr.Slider(0.0, 2.0, value=1.5, step=0.1, label="Температура", scale=3)
        run_custom = gr.Button("▶ Прогнать свою", scale=1)
    custom_out = gr.Textbox(label="Своя температура", **BOX)

    # Выбор готовой задачи -> подставляем её текст в поле.
    preset.change(lambda k: PRESETS[k], inputs=preset, outputs=task_in)
    run.click(compare, inputs=[task_in, n_runs], outputs=[c0, c1, c2])
    run_custom.click(
        custom, inputs=[task_in, temp_slider, n_runs], outputs=custom_out
    )

if __name__ == "__main__":
    demo.launch()
