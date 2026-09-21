from __future__ import annotations

import json
import os
import signal
import subprocess
import sys
import time
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from urllib.request import Request, urlopen


ROOT = Path(__file__).resolve().parents[1]
STATE_PATH = ROOT / ".local-agent-cards.json"
TOKEN = "local-demo-token"


AGENTS = [
    {
        "id": "benefits-agent",
        "port": 4711,
        "card": {
            "name": "Benefits Navigator",
            "description": "Answers employee benefits questions about health insurance, dental and vision plans, open enrollment, 401k matching, PTO, leave of absence, wellness programs, and eligibility rules.",
            "version": "1.0.0",
            "provider": {"organization": "RouteBench Demo Agents", "url": "https://example.com/routebench-demo"},
            "documentationUrl": "https://example.com/routebench-demo/benefits",
            "supportedInterfaces": [{"url": "http://127.0.0.1:4711/a2a", "protocolBinding": "JSONRPC", "protocolVersion": "1.0"}],
            "capabilities": {"streaming": False, "pushNotifications": False, "extendedAgentCard": False},
            "defaultInputModes": ["application/json", "text/plain"],
            "defaultOutputModes": ["application/json", "text/plain"],
            "skills": [
                {
                    "id": "benefits-policy-lookup",
                    "name": "Benefits Policy Lookup",
                    "description": "Finds policy answers for employee benefits, health insurance, dental coverage, vision plans, 401k matching, open enrollment windows, PTO accrual, leave programs, dependent eligibility, wellness stipends, and plan comparison questions.",
                    "tags": ["benefits", "insurance", "401k", "pto", "leave", "open enrollment"],
                    "examples": ["What is my 401k match?", "When is open enrollment for health insurance?"],
                }
            ],
        },
    },
    {
        "id": "payroll-agent",
        "port": 4712,
        "auth": True,
        "card": {
            "name": "Payroll Desk",
            "description": "Helps employees with paychecks, pay statements, W2 tax forms, tax withholding, direct deposit, deductions, reimbursements, bonuses, payroll calendars, and pay discrepancy questions.",
            "version": "1.0.0",
            "provider": {"organization": "RouteBench Demo Agents", "url": "https://example.com/routebench-demo"},
            "documentationUrl": "https://example.com/routebench-demo/payroll",
            "supportedInterfaces": [{"url": "http://127.0.0.1:4712/a2a", "protocolBinding": "JSONRPC", "protocolVersion": "1.0"}],
            "capabilities": {"streaming": False, "pushNotifications": True, "extendedAgentCard": False},
            "securitySchemes": {"demoBearer": {"type": "http", "scheme": "bearer", "description": "Demo bearer token."}},
            "securityRequirements": [{"demoBearer": []}],
            "defaultInputModes": ["application/json", "text/plain"],
            "defaultOutputModes": ["application/json", "text/plain"],
            "skills": [
                {
                    "id": "payroll-support",
                    "name": "Payroll Support",
                    "description": "Answers employee payroll questions about paychecks, pay statements, W2 availability, tax forms, tax withholding, deductions, direct deposit setup, reimbursements, bonus payments, payroll calendars, and missing or incorrect pay.",
                    "tags": ["payroll", "paycheck", "w2", "tax", "direct deposit", "reimbursement"],
                    "examples": ["Where can I download my W2 tax form?", "How do I update my direct deposit bank account?"],
                    "securityRequirements": [{"demoBearer": []}],
                }
            ],
        },
    },
    {
        "id": "it-helpdesk-agent",
        "port": 4713,
        "card": {
            "name": "IT Helpdesk Router",
            "description": "Supports employee technology requests including password resets, Okta login issues, VPN connectivity, laptop hardware problems, Slack access, email configuration, device enrollment, software installation, and incident triage.",
            "version": "1.0.0",
            "provider": {"organization": "RouteBench Demo Agents", "url": "https://example.com/routebench-demo"},
            "documentationUrl": "https://example.com/routebench-demo/it-helpdesk",
            "supportedInterfaces": [{"url": "http://127.0.0.1:4713/a2a", "protocolBinding": "JSONRPC", "protocolVersion": "1.0"}],
            "capabilities": {"streaming": True, "pushNotifications": True, "extendedAgentCard": False},
            "defaultInputModes": ["application/json", "text/plain"],
            "defaultOutputModes": ["application/json", "text/plain"],
            "skills": [
                {
                    "id": "technical-support",
                    "name": "Technical Support",
                    "description": "Troubleshoots employee IT issues including password resets, Okta authentication, VPN connectivity, laptop hardware, Slack access, email configuration, device enrollment, software installs, and common workplace application problems.",
                    "tags": ["it", "password", "vpn", "okta", "laptop", "slack", "email"],
                    "examples": ["My VPN will not connect from my laptop.", "Slack stopped working after my laptop rebooted."],
                }
            ],
        },
    },
]


def main() -> None:
    command = sys.argv[1] if len(sys.argv) > 1 else "help"
    if command == "serve":
        serve()
    elif command == "up":
        up()
    elif command == "down":
        down()
    else:
        print("Usage: python3 scripts/local_agent_cards.py up|down|serve")
        raise SystemExit(1)


def up() -> None:
    existing = read_state()
    if existing and is_running(existing["pid"]):
        print_state(existing)
        return
    process = subprocess.Popen(
        [sys.executable, str(Path(__file__).resolve()), "serve"],
        cwd=str(ROOT),
        start_new_session=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    state = {
        "pid": process.pid,
        "token": TOKEN,
        "agents": [
            {
                "id": agent["id"],
                "url": f"http://127.0.0.1:{agent['port']}/.well-known/agent-card.json",
                "authRequired": bool(agent.get("auth")),
            }
            for agent in AGENTS
        ],
    }
    STATE_PATH.write_text(json.dumps(state, indent=2) + "\n")
    wait_until_ready(state)
    print_state(state)


def down() -> None:
    state = read_state()
    if not state:
        print("No local Agent Card servers were running.")
        return
    try:
        os.kill(state["pid"], signal.SIGTERM)
    except ProcessLookupError:
        pass
    STATE_PATH.unlink(missing_ok=True)
    print(f"Stopped local Agent Card servers. PID: {state['pid']}")


def serve() -> None:
    servers = []
    for agent in AGENTS:
        server = HTTPServer(("127.0.0.1", agent["port"]), handler_for(agent))
        servers.append(server)
    try:
        import threading

        threads = [threading.Thread(target=server.serve_forever, daemon=True) for server in servers]
        for thread in threads:
            thread.start()
        while True:
            time.sleep(3600)
    finally:
        for server in servers:
            server.shutdown()


def handler_for(agent: dict):
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            if self.path != "/.well-known/agent-card.json":
                self.send_response(404)
                self.end_headers()
                return
            if agent.get("auth") and self.headers.get("authorization") != f"Bearer {TOKEN}":
                self.send_json({"error": "Missing or invalid demo token."}, status=401)
                return
            self.send_json(agent["card"])

        def log_message(self, *_args) -> None:
            return

        def send_json(self, value: dict, status: int = 200) -> None:
            body = json.dumps(value, indent=2).encode()
            self.send_response(status)
            self.send_header("access-control-allow-origin", "*")
            self.send_header("cache-control", "public, max-age=60")
            self.send_header("content-type", "application/a2a+json")
            self.send_header("content-length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

    return Handler


def print_state(state: dict) -> None:
    print(f"Local Agent Card servers running. PID: {state['pid']}")
    for agent in state["agents"]:
        suffix = " (auth required)" if agent["authRequired"] else ""
        print(f"- {agent['id']}: {agent['url']}{suffix}")
    print(f"Use ROUTEBENCH_DEMO_TOKEN={state['token']} for protected demo cards.")


def wait_until_ready(state: dict) -> None:
    deadline = time.time() + 3
    while time.time() < deadline:
        ready = True
        for agent in state["agents"]:
            headers = {}
            if agent["authRequired"]:
                headers["authorization"] = f"Bearer {TOKEN}"
            try:
                with urlopen(Request(agent["url"], headers=headers), timeout=1) as response:
                    ready = ready and response.status == 200
            except Exception:
                ready = False
        if ready:
            return
        time.sleep(0.1)
    raise RuntimeError("Local Agent Card servers did not start in time.")


def read_state() -> dict | None:
    if not STATE_PATH.exists():
        return None
    return json.loads(STATE_PATH.read_text())


def is_running(pid: int) -> bool:
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


if __name__ == "__main__":
    main()
