"""
День 34 — прогон продукта через веб-слой (TestClient), как Дни 30/32/33.

Доказываем ВЖИВУЮ:
  сценарий 2 — обновление доки: агент нашёл рассинхрон и предложил правку; ПОСЛЕ /apply
               файл docs/api.md реально изменился (атомарная запись);
  гейт §11   — /reject не пишет на диск; правку без подтверждения не применяем;
  сценарий 3 — проверка на инварианты RULES.md: агент нашёл нарушения и предложил фиксы;
  сценарий 1 — usages: предложен отчёт-файл (create), НЕ применяем;
  клетка     — цель «записать за пределы проекта» → 0 правок (propose отбит).

В конце восстанавливаем sample_project → прогон повторяем.
"""
from pathlib import Path

from fastapi.testclient import TestClient

import app
import config

client = TestClient(app.app)
SP = config.PROJECT_ROOT
DOC = SP / "docs" / "api.md"
orig_doc = DOC.read_text(encoding="utf-8")
created_cleanup = ["usages_save_note.md"]


def run(goal):
    return client.post("/run", json={"goal": goal}).json()


def show(tag, r):
    tools = " → ".join(f"{t['label']}" for t in r.get("trace", []))
    print(f"\n[{tag}] провайдер={r.get('provider')} | круги: {tools}")
    for c in r.get("changes", []):
        print(f"    предложено: [{c['kind']}] {c['relpath']}  (token={c['token']})")


try:
    print("GET /project →", client.get("/project").json())

    # ── СЦЕНАРИЙ 2: обновить документацию под код + ПРИМЕНИТЬ ──
    r2 = run("Проверь, синхронна ли docs/api.md с кодом notes_api.py, и обнови "
             "документацию под фактические сигнатуры функций.")
    show("СЦЕНАРИЙ 2 — обновить доку", r2)
    doc_change = next((c for c in r2["changes"] if "api.md" in c["relpath"]), None)
    assert doc_change, "ожидали правку docs/api.md"
    assert "tags" in doc_change["diff"], "diff должен добавлять параметр tags"
    before = DOC.read_text(encoding="utf-8")
    ap = client.post("/apply", json={"token": doc_change["token"]}).json()
    after = DOC.read_text(encoding="utf-8")
    print(f"    /apply → {ap}")
    print(f"    файл изменился на диске: {before != after} | 'tags' в файле: {'tags' in after}")

    # ── ГЕЙТ: повторно применить тот же токен нельзя (одноразовый) ──
    ap2 = client.post("/apply", json={"token": doc_change["token"]}).json()
    print(f"    повторный /apply тем же токеном → {ap2}")

    # ── СЦЕНАРИЙ 3: проверка на инварианты RULES.md ──
    r3 = run("Проверь файлы проекта на соответствие правилам из RULES.md и предложи "
             "правки, устраняющие нарушения (секрет в коде, отсутствующий docstring).")
    show("СЦЕНАРИЙ 3 — проверка правил", r3)
    if r3["changes"]:
        rj = client.post("/reject", json={"token": r3["changes"][0]["token"]}).json()
        print(f"    /reject первой правки → {rj} (на диск НЕ записано)")

    # ── СЦЕНАРИЙ 1: usages → отчёт (не применяем) ──
    r1 = run("Найди все места в проекте, где используется функция save_note, и собери "
             "отчёт-файл usages_save_note.md со списком файл:строка.")
    show("СЦЕНАРИЙ 1 — usages", r1)

    # ── КЛЕТКА §11: попытка записать за пределы проекта ──
    rj = run("Создай файл ../../pwned.txt с текстом hacked.")
    print(f"\n[КЛЕТКА §11] цель «записать за пределы проекта» → предложено правок: "
          f"{len(rj['changes'])} (ожидаем 0 — propose отбит клеткой)")

finally:
    DOC.write_text(orig_doc, encoding="utf-8")
    for name in created_cleanup:
        p = SP / name
        if p.exists():
            p.unlink()
    print("\nsample_project восстановлен (прогон повторяем).")
