"""День 29 — собрать index.html «до/после» из results.json.
Локальная страница (file://), данные бота НЕ покидают машину. Три колонки:
сырая (думание вкл) → текущая (калькулятор) → новая (живая). Голосом по-русски,
без эмодзи; иконки — inline SVG.
"""
import html
import json
from pathlib import Path

BASE = Path(__file__).parent
data = json.loads((BASE / "results.json").read_text())

in_base = [r for r in data if r.get("kept_n")]
traps = [r for r in data if r.get("gate_abstained")]


def avg(vals):
    vals = [v for v in vals if v is not None]
    return sum(vals) / len(vals) if vals else 0


# --- сводные числа ---
cur_toks = avg([r["runs"]["current"]["out_tok"] for r in in_base if "current" in r["runs"]])
new_toks = avg([r["runs"]["new"]["out_tok"] for r in in_base if "new" in r["runs"]])
cur_toks_s = avg([r["runs"]["current"]["tok_s"] for r in in_base if "current" in r["runs"]])
new_toks_s = avg([r["runs"]["new"]["tok_s"] for r in in_base if "new" in r["runs"]])
raw_rows = [r for r in in_base if "raw" in r["runs"]]
raw_toks = avg([r["runs"]["raw"]["out_tok"] for r in raw_rows])
cur_toks_on_raw = avg([r["runs"]["current"]["out_tok"] for r in raw_rows])
raw_sec = avg([r["runs"]["raw"]["sec"] for r in raw_rows])
cur_sec = avg([r["runs"]["current"]["sec"] for r in raw_rows])


def esc(s):
    return html.escape(str(s or ""))


def col(run, title, sub, cls):
    if not run:
        return f'<div class="col {cls}"><div class="ct">{title}</div><div class="empty">—</div></div>'
    metr = (f'<span>{run["sec"]}с</span><span>{run["out_tok"]} ток.</span>'
            f'<span>{run["tok_s"]} ток/с</span>')
    if run["answer"]:
        ans = f'<div class="ans">{esc(run["answer"])}</div>'
    else:
        ans = (f'<div class="cut">Сожгла {run["out_tok"]} токенов на внутренний монолог '
               f'и до ответа не дошла — обрезано лимитом. Вот зачем думание гасят.</div>')
    return (f'<div class="col {cls}"><div class="ct">{title}</div>'
            f'<div class="cs">{sub}</div>'
            f'{ans}'
            f'<div class="mx">{metr}</div></div>')


cards = []
for r in in_base:
    runs = r["runs"]
    raw_col = col(runs.get("raw"), "Сырая", "думание вкл · temp 0 · старый промпт", "raw") if "raw" in runs else ""
    body = (
        f'<div class="qh"><span class="qn">Вопрос</span> {esc(r["q"])}'
        f'<span class="score">релевантность {r["top_score"]}</span></div>'
        f'<div class="cols">'
        f'{raw_col}'
        f'{col(runs.get("current"), "Текущая (калькулятор)", "думание off · temp 0 · старый промпт", "cur")}'
        f'{col(runs.get("new"), "Новая (живая)", "думание off · temp 0.3 + min_p · новый промпт", "new")}'
        f'</div>')
    cards.append(f'<div class="card">{body}</div>')

trap_html = ""
if traps:
    items = "".join(f'<li>{esc(t["q"])} <em>(порог {t["top_score"]})</em></li>' for t in traps)
    trap_html = (
        '<div class="card trap"><div class="qh"><span class="qn">Предохранитель цел</span>'
        ' Вопросы вне базы — обе версии честно молчат на пороге, до генерации. '
        'Оживление НЕ сломало защиту от выдумки.</div>'
        f'<ul class="traps">{items}</ul></div>')

CHECK = ('<svg viewBox="0 0 24 24" width="15" height="15"><path fill="none" stroke="currentColor" '
         'stroke-width="2.5" d="M4 12l5 5L20 6"/></svg>')

page = f"""<div class="wrap">
<header>
  <h1>День 29 · оптимизация локальной LLM под наш RAG-бот по родительству</h1>
  <p class="lede">Одна модель, qwen3.5-9b в LM Studio. Крутили только ручки генерации,
  поиск держали постоянным. Два разных выигрыша на двух разных ручках.</p>
</header>

<section class="tiles">
  <div class="tile">
    <div class="tk">Скорость — уже отвоёвана (гашение думания)</div>
    <div class="tv">{raw_toks:.0f} <span>&rarr;</span> {cur_toks_on_raw:.0f} <small>ток. на ответ</small></div>
    <div class="tn">Сырая модель думает вслух и тратит лишние токены ({raw_sec:.0f}с),
    с гашением — сразу ответ ({cur_sec:.0f}с). Это мы сделали ещё на RAG-неделе.</div>
  </div>
  <div class="tile hl">
    <div class="tk">Качество — сегодняшняя работа (промпт + sampling)</div>
    <div class="tv">{cur_toks:.0f} <span>&rarr;</span> {new_toks:.0f} <small>ток. на ответ</small></div>
    <div class="tn">Тот же быстрый режим, но новый промпт снял намордник с речи —
    ответ развёрнутее и живее, а не сухая строка. Скорость: {cur_toks_s:.0f} и {new_toks_s:.0f} ток/с.</div>
  </div>
</section>

<div class="legend">
  <span class="lg raw">{CHECK} Сырая — до всякой оптимизации</span>
  <span class="lg cur">{CHECK} Текущая — быстрая, но калькулятор</span>
  <span class="lg new">{CHECK} Новая — быстрая и живая</span>
</div>

{''.join(cards)}
{trap_html}

<footer>Данные локальные, страница никуда не отправляется. Замер по методике: прогрев
выброшен, tok/s из usage. RAM модели во всех конфигах одинаковый — та же модель, —
поэтому «ресурс» виден в лишних токенах думания, не в памяти.</footer>
</div>"""

CSS = """
* { box-sizing: border-box; }
body { margin:0; background:#f4f5f7; color:#1c2024;
  font:16px/1.6 -apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,sans-serif; }
.wrap { max-width:1180px; margin:0 auto; padding:32px 20px 64px; }
header h1 { font-size:24px; margin:0 0 6px; letter-spacing:-.01em; }
.lede { color:#5b6470; margin:0 0 24px; max-width:760px; }
.tiles { display:grid; grid-template-columns:1fr 1fr; gap:16px; margin-bottom:24px; }
.tile { background:#fff; border:1px solid #e4e7eb; border-radius:14px; padding:18px 20px; }
.tile.hl { border-color:#2f7d5b; box-shadow:0 0 0 1px #2f7d5b; }
.tk { font-size:13px; color:#6b7280; margin-bottom:8px; }
.tv { font-size:30px; font-weight:650; letter-spacing:-.02em; }
.tv span { color:#9aa3ad; margin:0 6px; }
.tv small { font-size:14px; font-weight:400; color:#6b7280; }
.tn { font-size:13.5px; color:#5b6470; margin-top:8px; }
.legend { display:flex; gap:18px; flex-wrap:wrap; margin:0 2px 18px; font-size:13px; color:#5b6470; }
.lg { display:inline-flex; align-items:center; gap:5px; }
.lg.raw { color:#9a6b2f; } .lg.cur { color:#7a4fbf; } .lg.new { color:#2f7d5b; }
.card { background:#fff; border:1px solid #e4e7eb; border-radius:14px; padding:18px 20px;
  margin-bottom:16px; }
.qh { font-size:15.5px; font-weight:550; margin-bottom:14px; }
.qn { display:inline-block; font-size:11px; font-weight:600; text-transform:uppercase;
  letter-spacing:.04em; color:#8a94a0; margin-right:8px; }
.score { display:inline-block; margin-left:10px; font-size:12px; font-weight:400;
  color:#6b7280; background:#f0f2f4; padding:2px 8px; border-radius:20px; }
.cols { display:grid; grid-template-columns:repeat(auto-fit,minmax(240px,1fr)); gap:12px; }
.col { border-radius:11px; padding:13px 15px; border:1px solid #e8ebee; background:#fbfcfd; }
.col.raw { border-left:3px solid #c99a5b; }
.col.cur { border-left:3px solid #a884d8; }
.col.new { border-left:3px solid #4aa079; background:#f6fbf8; }
.ct { font-size:13px; font-weight:600; margin-bottom:2px; }
.cs { font-size:11.5px; color:#8a94a0; margin-bottom:10px; }
.ans { font-size:14.5px; color:#1c2024; white-space:pre-wrap; }
.cut { font-size:13.5px; color:#9a6b2f; font-style:italic; background:#fbf6ec;
  border-radius:8px; padding:9px 11px; }
.mx { display:flex; gap:12px; margin-top:12px; padding-top:9px; border-top:1px solid #eceff2;
  font-size:12px; color:#7a828c; }
.empty { color:#c4cad0; font-size:22px; }
.trap { background:#fcfbf7; border-color:#e8e2cf; }
.traps { margin:10px 0 0; padding-left:20px; color:#5b6470; font-size:14px; }
.traps em { color:#98a0aa; font-style:normal; font-size:12px; }
footer { color:#8a94a0; font-size:12.5px; margin-top:22px; line-height:1.5; }
"""

out = BASE / "index.html"
out.write_text(f"<!doctype html><html lang='ru'><head><meta charset='utf-8'>"
               f"<meta name='viewport' content='width=device-width,initial-scale=1'>"
               f"<title>День 29 — оптимизация локальной LLM</title><style>{CSS}</style>"
               f"</head><body>{page}</body></html>")
print(f"собрано → {out}")
