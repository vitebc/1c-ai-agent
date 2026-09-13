"""Смоук 1С-стороны MCP: прямой JSON-RPC в HTTP-сервис, без прокси и зависимостей.

Только стандартная библиотека Python — запускается на Windows-VM как есть:

    python onec/smoke_check.py --url http://HOST/base --user USER [--password ...]
    [--sku стул] [--counterparty Ромашка]

Проверяет: GET /hs/mcp/health, tools/list (ищет наши 3 инструмента),
tools/call get_stock_balance / get_counterparty / run_skd_report.
Выход 0 — всё ок; 1 — с разбором, что чинить (текст присылайте разработчику).
"""

from __future__ import annotations

import argparse
import base64
import getpass
import json
import sys
import urllib.error
import urllib.request

EXPECTED_TOOLS = ("get_stock_balance", "get_counterparty", "run_skd_report")


def _basic(user: str, password: str) -> str:
    token = base64.b64encode(f"{user}:{password}".encode()).decode()
    return f"Basic {token}"


def _get(url: str, auth: str, timeout: float) -> tuple[int, str]:
    req = urllib.request.Request(url, headers={"Authorization": auth})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.status, resp.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode("utf-8", "replace")[:500]


def _rpc(base: str, auth: str, timeout: float, method: str, params: dict, call_id: int) -> dict:
    body = json.dumps({"jsonrpc": "2.0", "id": call_id, "method": method, "params": params}).encode()
    req = urllib.request.Request(
        f"{base}/hs/mcp/rpc", data=body,
        headers={"Authorization": auth, "Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        raw = e.read().decode("utf-8", "replace")[:500]
        return {"_http_error": e.code, "_body": raw}
    try:
        return json.loads(raw)
    except ValueError:
        return {"_not_json": raw[:500]}


def main() -> int:
    ap = argparse.ArgumentParser(description="Смоук MCP HTTP-сервиса 1С")
    ap.add_argument("--url", required=True, help="База, напр. http://192.168.1.10/ka2test (регистр букв важен!)")
    ap.add_argument("--user", required=True)
    ap.add_argument("--password", default="")
    ap.add_argument("--sku", default="стул")
    ap.add_argument("--counterparty", default="Ромашка")
    ap.add_argument("--timeout", type=float, default=60.0)
    args = ap.parse_args()

    password = args.password or getpass.getpass("Пароль 1С: ")
    base = args.url.rstrip("/")
    auth = _basic(args.user, password)
    failures = 0

    print(f"== 1. GET {base}/hs/mcp/health")
    code, body = _get(f"{base}/hs/mcp/health", auth, args.timeout)
    print(f"   HTTP {code}: {body[:200]}")
    if code != 200:
        print("   FAIL: нет доступа к HTTP-сервису. Проверь публикацию, пользователя и регистр имени базы в URL.")
        return 1

    print("== 2. tools/list")
    resp = _rpc(base, auth, args.timeout, "tools/list", {}, 1)
    if "error" in resp or "_http_error" in resp or "_not_json" in resp:
        print(f"   FAIL: {json.dumps(resp, ensure_ascii=False)[:500]}")
        return 1
    names = [t.get("name", "?") for t in resp.get("result", {}).get("tools", [])]
    print(f"   инструментов: {len(names)}")
    for n in names:
        print(f"   - {n}")
    missing = [t for t in EXPECTED_TOOLS if t not in names]
    if missing:
        print(f"   FAIL: нет наших инструментов: {missing}. Проверь установку расширения A1C_Инструменты.")
        failures += 1

    calls = [
        ("get_stock_balance", {"sku": args.sku, "limit": 5}),
        ("get_counterparty", {"query": args.counterparty}),
        ("run_skd_report", {"report": "debtors", "period": "2026-Q1", "limit": 5}),
    ]
    for i, (name, call_args) in enumerate(calls, start=10):
        print(f"== {i}. tools/call {name} {json.dumps(call_args, ensure_ascii=False)}")
        resp = _rpc(base, auth, args.timeout, "tools/call",
                    {"name": name, "arguments": call_args}, i)
        if "error" in resp or "_http_error" in resp or "_not_json" in resp:
            print(f"   FAIL: {json.dumps(resp, ensure_ascii=False)[:1000]}")
            failures += 1
        else:
            print(f"   OK: {json.dumps(resp.get('result'), ensure_ascii=False)[:1000]}")

    print(f"== Итог: {'OK' if failures == 0 else f'FAILURES={failures}'}")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
