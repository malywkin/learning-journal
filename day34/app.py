"""
День 34 — веб-лицо ассистента-редактора (тонкий FastAPI). Продукт — ОКНО в браузере,
не терминал (память prefers-gui-app-not-terminal): ставишь цель → видишь, как агент
ходит по файлам → смотришь предложенный diff → сам жмёшь «Применить».

Здесь живёт ГЕЙТ §11: содержимое подготовленных правок сервер держит У СЕБЯ (PENDING)
и НЕ отдаёт в браузер. На диск попадает только то, что человек подтвердил кнопкой —
через /apply. Логика правок — в fs_tool/router, тут только HTTP.
"""
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import HTMLResponse, JSONResponse
from pydantic import BaseModel

import config
import fs_tool
import router

BASE = Path(__file__).resolve().parent
app = FastAPI(title="Ассистент файлов проекта — День 34")

# token → {relpath, new_text}: содержимое правок живёт на сервере до подтверждения.
PENDING: dict[str, dict] = {}
_SEQ = {"n": 0}


class Goal(BaseModel):
    goal: str


class Apply(BaseModel):
    token: str


@app.get("/", response_class=HTMLResponse)
async def index():
    return (BASE / "index.html").read_text(encoding="utf-8")


@app.get("/project")
async def project():
    return {"name": config.PROJECT_ROOT.name}


@app.post("/run")
async def run(g: Goal):
    goal = (g.goal or "").strip()
    if not goal:
        return JSONResponse({"answer": "Пустая цель.", "trace": [], "provider": "none", "changes": []})
    res = await router.run_goal(goal)
    # Каждой правке — серверный токен; new_text прячем на сервере (в UI уходит только diff).
    _SEQ["n"] += 1
    public = []
    for ch in res["changes"]:
        token = f"c{_SEQ['n']}-{ch['id']}"
        PENDING[token] = {"relpath": ch["relpath"], "new_text": ch["new_text"]}
        public.append({"token": token, "kind": ch["kind"], "relpath": ch["relpath"], "diff": ch["diff"]})
    res["changes"] = public
    return JSONResponse(res)


@app.post("/apply")
async def apply(a: Apply):
    item = PENDING.get(a.token)
    if not item:
        return JSONResponse({"error": "правка не найдена (уже применена или сервер перезапущен)"})
    r = fs_tool.apply_change(item["relpath"], item["new_text"])
    if r.get("applied"):
        PENDING.pop(a.token, None)          # применили — токен одноразовый
    return JSONResponse(r)


@app.post("/reject")
async def reject(a: Apply):
    PENDING.pop(a.token, None)              # человек отклонил — просто забываем правку
    return JSONResponse({"rejected": True})


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=8034, log_level="warning")
