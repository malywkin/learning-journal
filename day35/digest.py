"""
День 35 — СБОРКА дайджеста: возраст → рубрики → RAG по каждой → готовая заметка.

Это AGENT+OUTPUT по §12 конспекта. Возраст (age.py) даёт список рубрик, каждая рубрика
прогоняется через заземлённый RAG (rag.grounded_answer), а сверху надеваются ОГРАНИЧИТЕЛИ
из брифа Дня 35 — то, чего популярные родительские рассылки как раз НЕ делают:

  • дисклеймер СВОИМИ силами (у платформ он исчез: Stanford 26%→<1% в 2025);
  • явная маркировка «сгенерировано ИИ» (родители не отличают AI от врача и доверяют больше);
  • дата пересмотра гайдлайна у каждого источника (milestone-таблицы до 2022 устарели);
  • отказ вместо выдумки (порог Дня 24) — рубрика без опоры честно пропускается;
  • §14 human-in-the-loop: рубрика «когда к врачу» всегда ведёт к живому специалисту.

Error handling §14: если модель недоступна, НЕ падаем и НЕ молчим — отдаём
детерминированный fallback (выдержки прямо из источника, без генерации).
Метрики §15 считаем на каждом прогоне (время, отвечено/отказано, проверенных цитат).
"""
import re
import time
from datetime import date
from pathlib import Path

import config
import rag
from age import baby_age
from docs_tool import search_docs

DISCLAIMER = (
    "⚕️ Это авто-дайджест на основе официальных гайдлайнов NHS и CDC. "
    "Он собран искусственным интеллектом и НЕ заменяет консультацию врача. "
    "При тревожных признаках — сразу к врачу/акушерке, в неотложном случае — скорая."
)


# ---------- метаданные корпуса: URL/лицензия/дата пересмотра из шапки .md ----------
def _corpus_meta() -> dict[str, dict]:
    """Прочитать шапки всех гайдлайнов → {имя_файла: {url, license, reviewed}}.
    Нужно для честной подписи источника с ДАТОЙ пересмотра (требование брифа)."""
    meta = {}
    for p in config.CORPUS_DIR.glob("*.md"):
        if p.name == "SOURCES.md":               # мета-сводка, не гайдлайн
            continue
        head = p.read_text(encoding="utf-8", errors="ignore")[:800]
        def _grab(label):
            m = re.search(rf">\s*{label}:\s*(.+)", head)
            return m.group(1).strip() if m else ""
        meta[p.name] = {"url": _grab("URL"), "license": _grab("Лицензия"),
                        "reviewed": _grab("Пересмотрено")}
    return meta


def _sources_line(block: dict, meta: dict) -> str:
    """Строка источников рубрики: файл › раздел (+ дата пересмотра гайдлайна)."""
    seen, parts = set(), []
    for c in block.get("kept", [])[:3]:
        src = c.get("source", "")
        sec = (c.get("section") or "").strip(" #—")
        if not src or src in seen:
            continue
        seen.add(src)
        rev = meta.get(src, {}).get("reviewed", "")
        tag = src.replace(".md", "").replace("nhs-", "NHS ").replace("cdc-", "CDC ")
        parts.append(f"{tag}" + (f" › {sec}" if sec else "") + (f" (пересмотр {rev.split('·')[0].strip()})" if rev else ""))
    return "; ".join(parts)


TRUST = {"supported": "✔ подтверждено источником", "partial": "◐ частично подтверждено",
         "unsupported": "✘ опора не подтверждена", "unknown": "? проверка не удалась"}


# ---------- fallback §14: без LLM — выдержки прямо из источника ----------
def _raw_extract(query: str) -> dict | None:
    """Модель недоступна → показываем дословный топ-кусок гайдлайна, ничего не генерим."""
    hits = search_docs(query, k=1)
    if not hits or hits[0]["score"] < config.THRESHOLD:
        return None
    h = hits[0]
    text = h["text"]
    return {"answer": text[:400] + ("…" if len(text) > 400 else ""),
            "kept": [h], "status": "raw_fallback", "faithfulness": None,
            "checked": [], "provider": "none"}


# ---------- главный сборщик ----------
def build_digest(today: date | None = None) -> dict:
    """Собрать дайджест на дату. Возвращает {markdown, telegram, metrics, phase, ...}."""
    t0 = time.time()
    info = baby_age(today)
    meta = _corpus_meta()
    if info.phase == "unknown":
        return {"markdown": "Даты ребёнка не заданы — впишите BABY_DUE_DATE в .env.",
                "telegram": "", "metrics": {}, "phase": "unknown"}

    blocks, answered, abstained, fallback_used, verified_total = [], 0, 0, 0, 0
    provider_seen = set()
    for r in info.rubrics:
        b = rag.grounded_answer(r["query"])
        # рубрика без опоры и модель что-то ответила «нет» → пробуем fallback-выдержку
        if b["status"] in ("model_abstained", "unverifiable") or (b.get("provider") == "none"):
            raw = _raw_extract(r["query"])
            if raw:
                b = {**b, **raw}
                fallback_used += 1
        if b.get("provider"):
            provider_seen.add(b["provider"])
        if b["status"] == "answered" or b.get("status") == "raw_fallback":
            answered += 1
            verified_total += b.get("verified_n", 0)
        else:
            abstained += 1
        blocks.append({"rubric": r, "block": b})

    dt = round(time.time() - t0, 1)
    provider = "+".join(sorted(provider_seen - {"none"})) or "none (только источники)"
    metrics = {
        "phase": info.phase, "label": info.label, "rubrics": len(info.rubrics),
        "answered": answered, "abstained": abstained, "fallback_used": fallback_used,
        "verified_quotes": verified_total, "seconds": dt, "provider": provider,
        "corpus_files": len(meta),
    }
    md = _render_markdown(info, blocks, meta, metrics, today or date.today())
    tg = _render_telegram(info, blocks, meta, metrics, today or date.today())
    return {"markdown": md, "telegram": tg, "metrics": metrics, "phase": info.phase,
            "label": info.label, "blocks": blocks}


# ---------- рендер: markdown-заметка (файл-архив) ----------
def _render_markdown(info, blocks, meta, metrics, today) -> str:
    icon = "🤰" if info.phase == "pregnancy" else "🍼"
    out = [f"# {icon} Родительский дайджест — {info.label}",
           f"_{today.isoformat()} · собрано по гайдлайнам NHS/CDC_\n"]
    any_body = False
    for item in blocks:
        r, b = item["rubric"], item["block"]
        if not b.get("answer"):                      # честный отказ — рубрику пропускаем
            continue
        any_body = True
        out.append(f"## {r['title']}")
        out.append(b["answer"])
        src = _sources_line(b, meta)
        if src:
            out.append(f"\n📎 _{src}_")
        if b.get("status") == "raw_fallback":
            out.append("_⚙️ выдержка напрямую из источника (модель была недоступна)_")
        elif b.get("faithfulness"):
            out.append(f"_{TRUST.get(b['faithfulness']['verdict'], '')}_")
        out.append("")
    if not any_body:
        out.append("_На эту неделю уверенного ответа из источников не нашлось — "
                   "лучше свериться с врачом/акушеркой напрямую._\n")
    out.append("\n---")
    out.append(DISCLAIMER)
    out.append(f"\n🤖 Сгенерировано ИИ (модель: {metrics['provider']}), {today.isoformat()}. "
               f"Рубрик отвечено {metrics['answered']}/{metrics['rubrics']}, "
               f"подтверждённых цитат {metrics['verified_quotes']}, время {metrics['seconds']} с.")
    return "\n".join(out)


# ---------- рендер: короткий текст для Telegram ----------
def _render_telegram(info, blocks, meta, metrics, today) -> str:
    icon = "🤰" if info.phase == "pregnancy" else "🍼"
    out = [f"{icon} Дайджест — {info.label}", ""]
    for item in blocks:
        r, b = item["rubric"], item["block"]
        if not b.get("answer"):
            continue
        out.append(f"▸ {r['title']}")
        out.append(b["answer"])
        src = _sources_line(b, meta)
        if src:
            out.append(f"📎 {src}")
        out.append("")
    out.append(DISCLAIMER)
    return "\n".join(out)


def save_digest(result: dict, today: date | None = None) -> Path:
    """Сложить заметку в архив на диск (второй, приватный выход)."""
    config.DIGEST_DIR.mkdir(exist_ok=True)
    day = (today or date.today()).isoformat()
    path = config.DIGEST_DIR / f"digest-{day}.md"
    path.write_text(result["markdown"], encoding="utf-8")
    return path


if __name__ == "__main__":
    res = build_digest()
    print(res["markdown"])
    print("\n===== МЕТРИКИ =====")
    for k, v in res["metrics"].items():
        print(f"  {k}: {v}")
