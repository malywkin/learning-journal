"""День 5 — Версии моделей.

Один и тот же запрос на разных «версиях» модели по двум осям:
  • ось A — РАЗМЕР: малая vs крупная модель (одно семейство, меняется только размер);
  • ось B — TEST-TIME COMPUTE: одна модель × reasoning effort low/medium/high.
На каждый прогон честно меряем: TTFT, total, output speed, токены
(вход/выход/reasoning), «как бы цену». Качество — LLM-судьёй со swap-and-agree.

Провайдер — OpenRouter (OpenAI-совместимый). Ключ — в .env (не хардкодим).

ВАЖНО (free-tier реальность): многие бесплатные модели сидят за общими лимитами
сторонних провайдеров и часто отдают 429. Надёжно доступно семейство OpenAI gpt-oss,
поэтому оно — дефолт. Широкую лесенку Llama 3B→70B→405B можно включить флагом --wide
(чище по размаху размеров, но часто упирается в лимиты — код это переживает).
"""
import os
import time
import argparse
from dotenv import load_dotenv
from openai import OpenAI, RateLimitError

load_dotenv(os.path.join(os.path.dirname(__file__), ".env"))

# --- Ось A: размер (надёжный дефолт — одно семейство gpt-oss) -------------------
TIERS = [
    ("малая · 20B",   "openai/gpt-oss-20b:free"),
    ("крупная · 120B", "openai/gpt-oss-120b:free"),
]
# Широкая лесенка по флагу --wide: один род (Llama), меняется только размер.
WIDE_TIERS = [
    ("слабая · 3B",    "meta-llama/llama-3.2-3b-instruct:free"),
    ("средняя · 70B",  "meta-llama/llama-3.3-70b-instruct:free"),
    ("сильная · 405B", "nousresearch/hermes-3-llama-3.1-405b:free"),
]

# --- Ось B: ОДНА reasoning-модель, меняем сколько ей думать ---------------------
EFFORT_MODEL = "openai/gpt-oss-20b:free"
EFFORTS = ["low", "medium", "high"]

# --- Судья: ОТДЕЛЬНАЯ модель (≠ участники оси B = 20B) → против self-preference --
JUDGE_MODEL = "openai/gpt-oss-120b:free"

# «Как бы цена»: наши модели бесплатные ($0). Чтобы показать механику стоимости,
# умножаем токены на РЕАЛЬНЫЙ тариф платной модели (DeepSeek-v4-flash, $/1M).
REF_NAME = "DeepSeek-v4-flash"
REF_IN, REF_OUT = 0.14, 0.28

RUBRIC = ("Критерии: фактическая точность, полнота, ясность. "
          "НАГРАЖДАЙ КРАТКОСТЬ и штрафуй «воду» — длина не есть качество.")


def get_client():
    return OpenAI(base_url="https://openrouter.ai/api/v1",
                  api_key=os.environ["OPENROUTER_API_KEY"])


def run_model(client, model, prompt, effort=None, max_tokens=1024, retries=2):
    """Один прогон со стримингом. Возвращает словарь метрик (или {'error': ...})."""
    extra = {"reasoning": {"effort": effort}} if effort else {}
    for attempt in range(retries + 1):
        t0 = time.time()
        ttft = None
        content = ""
        reasoning_text = ""
        usage = None
        try:
            stream = client.chat.completions.create(
                model=model,
                messages=[{"role": "user", "content": prompt}],
                stream=True,
                stream_options={"include_usage": True},
                max_tokens=max_tokens,
                extra_body=extra,
            )
            for chunk in stream:
                if chunk.usage:                       # финальный chunk
                    usage = chunk.usage
                if not chunk.choices:
                    continue
                delta = chunk.choices[0].delta
                if getattr(delta, "reasoning", None):  # невидимое думанье
                    reasoning_text += delta.reasoning
                if delta.content:
                    if ttft is None:                   # первый ВИДИМЫЙ токен
                        ttft = time.time() - t0
                    content += delta.content
            total = time.time() - t0

            # --- разбираем квитанцию usage ---
            pt = getattr(usage, "prompt_tokens", None) if usage else None
            ct = getattr(usage, "completion_tokens", None) if usage else None
            rt = 0
            details = getattr(usage, "completion_tokens_details", None) if usage else None
            if details:
                rt = getattr(details, "reasoning_tokens", 0) or 0
            visible = (ct - rt) if ct is not None else None

            # output speed считаем по ФАЗЕ ПЕЧАТИ (total минус молчаливое думанье).
            # Когда думанье съело почти всё время (фаза печати < 0.5с), метрика
            # неустойчива (делим на ~0) — помечаем think_bound, число не показываем.
            speed = None
            think_bound = False
            if ct and ttft is not None and total > ttft:
                printing = total - ttft
                if printing < 0.5:
                    think_bound = True
                else:
                    speed = ct / printing

            # Надёжный «весь выход» = total - prompt (совпадает с completion, когда
            # учёт чистый; но переживает редкий кривой репорт стримингового usage,
            # где completion и reasoning приходят рассогласованно у free-провайдера).
            tt = getattr(usage, "total_tokens", None) if usage else None
            out_billed = (tt - pt) if (tt is not None and pt is not None) else ct

            # «как бы цена» = вход/1e6*тариф_входа + выход/1e6*тариф_выхода
            cost = None
            if pt is not None and out_billed is not None:
                cost = pt / 1e6 * REF_IN + out_billed / 1e6 * REF_OUT

            return dict(model=model, effort=effort, error=None,
                        ttft=ttft, total=total, speed=speed, think_bound=think_bound,
                        prompt_tokens=pt, completion_tokens=ct,
                        reasoning_tokens=rt, visible_tokens=visible,
                        cost=cost, answer=content.strip(),
                        reasoning_text=reasoning_text.strip())
        except RateLimitError:
            if attempt < retries:
                time.sleep(6)                          # короткий backoff и повтор
                continue
        except Exception as e:
            return dict(model=model, effort=effort,
                        error=f"{type(e).__name__}: {e}", answer="")
    return dict(model=model, effort=effort,
                error=f"RateLimit после {retries} повторов (free-tier)", answer="")


def run_repeated(client, model, prompt, effort=None, runs=1):
    """Прогоняем конфиг runs раз и берём МЕДИАННЫЙ по total — против шума free-tier
    (один прогон врёт: видели, как 120B оказалась быстрее 20B из-за нагрузки)."""
    outs = [run_model(client, model, prompt, effort=effort) for _ in range(runs)]
    ok = [r for r in outs if not r.get("error")]
    if not ok:
        return outs[-1]                                # все упали — вернём последнюю ошибку
    ok.sort(key=lambda r: r["total"])
    med = dict(ok[len(ok) // 2])                        # медиана по времени
    med["runs_ok"], med["runs_total"] = len(ok), runs
    return med


# ------------------------- КАЧЕСТВО: LLM-судья --------------------------------
def _judge_once(client, question, ans1, ans2):
    """Один вердикт судьи для ОДНОГО порядка. Вернёт '1' | '2' | 'tie'."""
    msg = (f"Ты — строгий судья качества ответов. Вопрос:\n{question}\n\n"
           f"{RUBRIC}\n\n"
           f"Ответ [1]:\n{ans1}\n\nОтвет [2]:\n{ans2}\n\n"
           "Какой ответ лучше по рубрике? Ответь СТРОГО одним словом: 1, 2 или tie.")
    r = client.chat.completions.create(
        model=JUDGE_MODEL,
        messages=[{"role": "user", "content": msg}],
        max_tokens=600,
        extra_body={"reasoning": {"effort": "low"}},
    )
    out = (r.choices[0].message.content or "").strip().lower()
    if out.startswith("1"):
        return "1"
    if out.startswith("2"):
        return "2"
    return "tie"


def swap_and_agree(client, question, name_a, ans_a, name_b, ans_b):
    """Судим пару в ОБА порядка. Победитель засчитывается, только если совпал.
    Несовпадение = судья реагировал на позицию → честная ничья."""
    v1 = _judge_once(client, question, ans_a, ans_b)        # порядок [A, B]
    v2 = _judge_once(client, question, ans_b, ans_a)        # порядок [B, A]
    win1 = name_a if v1 == "1" else name_b if v1 == "2" else "tie"
    win2 = name_b if v2 == "1" else name_a if v2 == "2" else "tie"
    if win1 == win2 and win1 != "tie":
        return dict(winner=win1, consistent=True, order1=win1, order2=win2)
    return dict(winner="ничья", consistent=False, order1=win1, order2=win2)


def judge_tournament(client, question, named_answers):
    """Попарный турнир swap-and-agree по всем парам. named_answers = [(имя, текст)]."""
    results = []
    valid = [(n, a) for n, a in named_answers if a]
    for i in range(len(valid)):
        for j in range(i + 1, len(valid)):
            (na, aa), (nb, ab) = valid[i], valid[j]
            res = swap_and_agree(client, question, na, aa, nb, ab)
            res["pair"] = (na, nb)
            results.append(res)
    return results


# ------------------------------- ВЫВОД ----------------------------------------
def fmt_row(label, r):
    if r.get("error"):
        return f"{label:<16} | ОШИБКА: {r['error']}"
    g = lambda v, f: (f.format(v) if v is not None else "—")
    spd = "think" if r.get("think_bound") else g(r["speed"], "{:.0f}")
    return (f"{label:<16} | TTFT {g(r['ttft'],'{:.2f}s'):>7} | total {g(r['total'],'{:.2f}s'):>7} "
            f"| {spd:>5} tok/s | in {g(r['prompt_tokens'],'{}'):>4} "
            f"| out {g(r['completion_tokens'],'{}'):>4} (reason {r.get('reasoning_tokens',0)}) "
            f"| ~${g(r['cost'],'{:.5f}')}")


def main():
    ap = argparse.ArgumentParser(description="День 5 — сравнение версий моделей")
    ap.add_argument("prompt", nargs="?",
                    default="Договор заключён 30 февраля 2024 года сроком на один месяц. "
                            "Когда истекает срок? Ответь кратко и укажи, если с датой что-то не так.",
                    help="запрос, который шлём всем моделям")
    ap.add_argument("--wide", action="store_true", help="широкая лесенка Llama 3B/70B/405B (может лимититься)")
    ap.add_argument("--axis-b", action="store_true", help="прогнать ось B (effort low/medium/high)")
    ap.add_argument("--judge", action="store_true", help="оценить качество судьёй (swap-and-agree)")
    ap.add_argument("--runs", type=int, default=1, help="повторов на конфиг, берём медиану по time (против шума)")
    args = ap.parse_args()

    client = get_client()
    tiers = WIDE_TIERS if args.wide else TIERS
    print(f"ЗАПРОС: {args.prompt}\n")

    # --- Ось A: размер ---
    print(f"=== ОСЬ A — размер модели  (runs={args.runs}, медиана) ===")
    a_answers = []
    for label, model in tiers:
        r = run_repeated(client, model, args.prompt, runs=args.runs)
        print(fmt_row(label, r))
        a_answers.append((label, r.get("answer", "")))
    print(f"(«как бы цена» — по тарифу {REF_NAME}: ${REF_IN}/1M вход, ${REF_OUT}/1M выход)\n")

    # --- Ось B: reasoning effort ---
    b_answers = []
    if args.axis_b:
        print(f"=== ОСЬ B — reasoning effort на ОДНОЙ модели ({EFFORT_MODEL}) ===")
        for eff in EFFORTS:
            r = run_repeated(client, EFFORT_MODEL, args.prompt, effort=eff, runs=args.runs)
            print(fmt_row(f"effort={eff}", r))
            b_answers.append((f"effort={eff}", r.get("answer", "")))
        print()

    # --- Качество: судья. По умолчанию судим ось B (нет self-preference:
    #     участники = 20B, судья = 120B). Если оси B нет — судим ось A с оговоркой.
    if args.judge:
        if b_answers:
            print("=== КАЧЕСТВО — судья по ОСИ B (больше reasoning = лучше?) ===")
            named = b_answers
        else:
            print("=== КАЧЕСТВО — судья по ОСИ A (⚠ судья 120B той же семьи → возможен self-preference) ===")
            named = a_answers
        for res in judge_tournament(client, args.prompt, named):
            na, nb = res["pair"]
            tag = "✓ устойчиво" if res["consistent"] else "⚠ перевернулось → ничья (position bias)"
            print(f"{na} vs {nb}: победитель = {res['winner']}  "
                  f"[{na}|{nb}→{res['order1']}, {nb}|{na}→{res['order2']}]  {tag}")


if __name__ == "__main__":
    main()
