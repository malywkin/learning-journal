"""День 5 — GUI (Gradio): версии моделей бок о бок.

Один запрос → ось A (размер: gpt-oss 20B vs 120B) и ось B (одна модель × reasoning
effort), честные замеры (TTFT / total / tok-s / токены / «как бы цена») и качество
судьёй со swap-and-agree. Логика — из task5.py (один источник правды).

Скорость: все вызовы идут ПАРАЛЛЕЛЬНО (пул потоков), а таблица заполняется
ПРОГРЕССИВНО (yield по мере готовности) — не ждём самый медленный high-effort.
Судья оценивает ОСЬ B (участники = 20B, судья = 120B → нет self-preference).
"""
import concurrent.futures as cf
import gradio as gr
from task5 import (get_client, run_repeated, swap_and_agree,
                   TIERS, EFFORT_MODEL, EFFORTS, JUDGE_MODEL,
                   REF_NAME, REF_IN, REF_OUT)

EXAMPLES = [
    "Договор заключён 30 февраля 2024 года сроком на один месяц. Когда истекает срок? "
    "Ответь кратко и укажи, если с датой что-то не так.",
    "Иван подарил автомобиль и оформил дарение. Через месяц умер. Наследники требуют "
    "вернуть авто в наследственную массу. Правомерно ли требование? Кратко обоснуй.",
    "Сколько будет 17 умножить на 24? Покажи только итог.",
]
COLS = ["конфиг", "TTFT с", "total с", "tok/с", "вход", "выход", "reason", "~цена"]
NOTE = (f"«Как бы цена» — токены × тариф **{REF_NAME}** (${REF_IN}/1M вход, ${REF_OUT}/1M "
        f"выход); модели бесплатные. `think` в tok/с = модель почти всё время думала. "
        f"Вызовы идут параллельно, строки появляются по мере готовности.")


def _cell(label, r):
    if r.get("error"):
        return [label, "—", "—", "—", "—", "—", "—", f"ОШИБКА: {r['error'][:40]}"]
    f = lambda v, fmt: (fmt.format(v) if v is not None else "—")
    spd = "think" if r.get("think_bound") else f(r["speed"], "{:.0f}")
    return [label, f(r["ttft"], "{:.2f}"), f(r["total"], "{:.2f}"), spd,
            f(r["prompt_tokens"], "{}"), f(r["completion_tokens"], "{}"),
            str(r.get("reasoning_tokens", 0)), f(r["cost"], "${:.5f}")]


def _answer_block(label, model, r):
    ans = r.get("answer") or f"_{r.get('error', '')}_"
    block = f"### {label}\n`{model}`\n\n{ans}"
    peek = r.get("reasoning_text", "")
    if peek:                                  # показываем кусок ОБЫЧНО невидимого думанья
        block += (f"\n\n<details><summary>🧠 reasoning ({len(peek)} симв.)</summary>\n\n"
                  f"{peek[:800]}\n</details>")
    return block


def run_all(prompt, do_axis_b, do_judge, runs):
    client = get_client()
    if do_judge:
        do_axis_b = True                      # судья судит ось B → она нужна
    runs = int(runs)

    # план заданий: (label, model, effort)
    jobs = [(f"A · {label}", model, None) for label, model in TIERS]
    if do_axis_b:
        jobs += [(f"B · effort={eff}", EFFORT_MODEL, eff) for eff in EFFORTS]
    n = len(jobs)

    rows = [[lbl, "…", "…", "…", "…", "…", "…", "⏳"] for (lbl, _, _) in jobs]
    results = [None] * n
    yield rows, NOTE, "", ""                   # сразу показываем каркас таблицы

    # --- все вызовы моделей ПАРАЛЛЕЛЬНО, рисуем по мере готовности ---
    with cf.ThreadPoolExecutor(max_workers=n) as ex:
        fut = {ex.submit(run_repeated, client, m, prompt, effort=e, runs=runs): i
               for i, (lbl, m, e) in enumerate(jobs)}
        for f in cf.as_completed(fut):
            i = fut[f]
            results[i] = f.result()
            rows[i] = _cell(jobs[i][0], results[i])
            answers = "\n\n---\n\n".join(
                _answer_block(jobs[k][0], jobs[k][1], results[k])
                for k in range(n) if results[k] is not None)
            yield rows, NOTE, answers, ""

    # --- судья по оси B (пары — тоже параллельно) ---
    if do_judge:
        b_named = [(jobs[i][0].replace("B · ", ""), results[i].get("answer", ""))
                   for i, (lbl, m, e) in enumerate(jobs) if e is not None and results[i].get("answer")]
        pairs = [(b_named[i], b_named[j])
                 for i in range(len(b_named)) for j in range(i + 1, len(b_named))]
        judge_md = ("### ⚖️ Судья по оси B (больше reasoning = лучше?)\n"
                    f"_судья {JUDGE_MODEL} ≠ участники (20B) → нет self-preference. Считаю…_\n\n")
        yield rows, NOTE, answers, judge_md
        with cf.ThreadPoolExecutor(max_workers=max(len(pairs), 1)) as ex:
            futs = [ex.submit(swap_and_agree, client, prompt, na, aa, nb, ab)
                    for (na, aa), (nb, ab) in pairs]
            lines = []
            for (na, aa), (nb, ab), fu in zip([p[0] for p in pairs], [p[1] for p in pairs], futs):
                res = fu.result()
                tag = ("✓ устойчиво" if res["consistent"]
                       else "⚠ перевернулось при смене порядка → **ничья** (position bias пойман)")
                lines.append(f"- **{na}** vs **{nb}** → **{res['winner']}**  "
                             f"`[{na},{nb}]→{res['order1']}` · `[{nb},{na}]→{res['order2']}` · {tag}")
                judge_md = ("### ⚖️ Судья по оси B (больше reasoning = лучше?)\n"
                            f"_судья {JUDGE_MODEL} ≠ участники (20B) → нет self-preference_\n\n"
                            + "\n".join(lines))
                yield rows, NOTE, answers, judge_md


with gr.Blocks(title="День 5 — Версии моделей") as demo:
    gr.Markdown("# День 5 — Версии моделей\n"
                "Один запрос → **ось A** (размер: gpt-oss 20B vs 120B) и **ось B** "
                "(reasoning effort). Вызовы параллельны, строки появляются по мере готовности.")
    with gr.Row():
        prompt = gr.Textbox(label="Запрос (один на всех)", value=EXAMPLES[0], lines=3, scale=4)
        with gr.Column(scale=1):
            ax_b = gr.Checkbox(label="Ось B (reasoning effort)", value=True)
            jud = gr.Checkbox(label="Качество (судья оси B)", value=False)
            runs = gr.Slider(1, 3, value=1, step=1, label="повторов (медиана)")
            run = gr.Button("▶ Запустить", variant="primary")
    gr.Examples(EXAMPLES, inputs=prompt)

    table = gr.Dataframe(headers=COLS, label="Замеры", wrap=True, interactive=False)
    note = gr.Markdown()
    judge_out = gr.Markdown()
    answers = gr.Markdown(label="Ответы")

    run.click(run_all, inputs=[prompt, ax_b, jud, runs],
              outputs=[table, note, answers, judge_out])

if __name__ == "__main__":
    demo.launch()
