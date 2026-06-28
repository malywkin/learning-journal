"""
День 19 — CLI к цепочке из трёх MCP-инструментов (search → summarize → save_to_file).

Один и тот же сервер, два оркестратора — выбираешь флагом --mode:
  • pipeline (по умолчанию) — порядок ведёт КОД (1 вызов LLM, 0 решений-выборов);
  • agent                   — порядок выбирает МОДЕЛЬ (tool_choice=auto, несколько вызовов).

ВАЖНО: сначала в отдельном окне подними сервер  →  python mcp_server.py
Потом:
  python task19.py --sub LocalLLaMA
  python task19.py --sub LocalLLaMA --mode agent
  python task19.py --sub MachineLearning --query "agents" --mode pipeline
"""

import argparse
import asyncio

import agent
import pipeline


def _print(res: dict) -> None:
    print(f'\nрежим: {res["mode"]} | к модели всего: {res["llm_calls"]} '
          f'(работа {res["work_calls"]} + руление {res["steering_calls"]}) | '
          f'токенов: {res.get("total_tokens", 0)} '
          f'(работа {res.get("work_tokens", 0)} + руление {res.get("steering_tokens", 0)}) | '
          f'итог: {"ok" if res["ok"] else "не дошло"}')
    print("шаги:")
    for t in res["trace"]:
        if t.get("kind") == "offer":
            print(f'  • предложены инструменты: {", ".join(t["tools"])}')
        elif t.get("kind") == "final":
            print(f'  • финал модели: {t["text"][:160]}')
        elif "step" in t:
            mark = "✓" if t.get("ok") else "✗"
            mcall = f' [вызов LLM #{t["model_call_no"]}]' if t.get("model_call_no") else ""
            print(f'  {mark} {t["step"]:13} {t["role"]:20} {t["result_line"]}{mcall}')
            if t.get("handoff"):
                print(f'        → передаёт: {t["handoff"]}')
    if res.get("file_path"):
        print(f'\nфайл: {res["file_path"]}')
    if res.get("summary"):
        print(f'\nсводка:\n{res["summary"]}')


def main() -> None:
    ap = argparse.ArgumentParser(description="Цепочка из трёх MCP-инструментов")
    ap.add_argument("--sub", default="LocalLLaMA", help="сабреддит без r/")
    ap.add_argument("--query", default="", help="слово для поиска (необязательно)")
    ap.add_argument("--mode", default="pipeline", choices=["pipeline", "agent"])
    args = ap.parse_args()

    if args.mode == "agent":
        res = asyncio.run(agent.run_agent(args.sub, args.query))
    else:
        res = asyncio.run(pipeline.run_pipeline(args.sub, args.query))
    _print(res)


if __name__ == "__main__":
    main()
