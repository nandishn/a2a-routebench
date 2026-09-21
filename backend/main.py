from __future__ import annotations

import json
import os
import re
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field


ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = ROOT / "data"
PROJECT_RE = re.compile(r"^[A-Za-z0-9_]+$")
PROVIDERS = {"gemini", "openai", "anthropic", "grok"}

app = FastAPI(title="A2A RouteBench API")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://127.0.0.1:5173", "http://localhost:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


class ProjectCreate(BaseModel):
    name: str


class ProjectRename(BaseModel):
    name: str


class AgentInput(BaseModel):
    name: str
    url: str
    auth_env_name: str | None = None


class EvalInput(BaseModel):
    name: str
    prompt: str
    expected_agent: str


class LlmSettings(BaseModel):
    provider: str
    key_env_name: str | None = None
    api_key: str | None = Field(default=None, exclude=True)


@app.on_event("startup")
def startup() -> None:
    DATA_DIR.mkdir(exist_ok=True)


@app.get("/api/projects")
def list_projects() -> dict[str, Any]:
    DATA_DIR.mkdir(exist_ok=True)
    projects = []
    for item in sorted(DATA_DIR.iterdir()):
        if item.is_dir() and (item / "agents.json").exists() and (item / "evals.json").exists():
            projects.append({"name": item.name})
    return {"projects": projects}


@app.post("/api/projects")
def create_project(payload: ProjectCreate) -> dict[str, Any]:
    name = validate_project_name(payload.name)
    project_dir = project_path(name)
    if project_dir.exists():
        raise HTTPException(status_code=409, detail="Project name already exists.")
    project_dir.mkdir(parents=True)
    write_json(project_dir / "agents.json", [])
    write_json(project_dir / "evals.json", [])
    write_json(project_dir / "runs.json", [])
    return read_project(name)


@app.get("/api/projects/{project_name}")
def read_project(project_name: str) -> dict[str, Any]:
    project_dir = existing_project_path(project_name)
    return {
        "name": project_dir.name,
        "agents": read_json(project_dir / "agents.json", []),
        "evals": read_json(project_dir / "evals.json", []),
        "runs": read_json(project_dir / "runs.json", []),
    }


@app.patch("/api/projects/{project_name}")
def rename_project(project_name: str, payload: ProjectRename) -> dict[str, Any]:
    current = existing_project_path(project_name)
    new_name = validate_project_name(payload.name)
    target = project_path(new_name)
    if target.exists() and target != current:
        raise HTTPException(status_code=409, detail="Project name already exists.")
    current.rename(target)
    return read_project(new_name)


@app.post("/api/projects/{project_name}/agents")
def add_agent(project_name: str, payload: AgentInput) -> dict[str, Any]:
    project_dir = existing_project_path(project_name)
    agents = read_json(project_dir / "agents.json", [])
    agent = {
        "id": str(uuid.uuid4()),
        "name": clean_required(payload.name, "Agent name"),
        "url": clean_required(payload.url, "Agent URL"),
        "auth_env_name": clean_optional(payload.auth_env_name),
        "created_at": now_iso(),
    }
    agent.update(fetch_agent_card(agent))
    agents.append(agent)
    write_json(project_dir / "agents.json", agents)
    return {"agent": agent}


@app.patch("/api/projects/{project_name}/agents/{agent_id}")
def update_agent(project_name: str, agent_id: str, payload: AgentInput) -> dict[str, Any]:
    project_dir = existing_project_path(project_name)
    agents = read_json(project_dir / "agents.json", [])
    for agent in agents:
        if agent["id"] == agent_id:
            agent["name"] = clean_required(payload.name, "Agent name")
            agent["url"] = clean_required(payload.url, "Agent URL")
            agent["auth_env_name"] = clean_optional(payload.auth_env_name)
            agent["updated_at"] = now_iso()
            agent.update(fetch_agent_card(agent))
            write_json(project_dir / "agents.json", agents)
            return {"agent": agent}
    raise HTTPException(status_code=404, detail="Agent not found.")


@app.delete("/api/projects/{project_name}/agents/{agent_id}")
def delete_agent(project_name: str, agent_id: str) -> dict[str, Any]:
    project_dir = existing_project_path(project_name)
    agents = read_json(project_dir / "agents.json", [])
    next_agents = [agent for agent in agents if agent["id"] != agent_id]
    write_json(project_dir / "agents.json", next_agents)
    return {"removed": len(agents) - len(next_agents)}


@app.post("/api/projects/{project_name}/agents/evaluate")
def evaluate_agents(project_name: str) -> dict[str, Any]:
    project_dir = existing_project_path(project_name)
    agents = read_json(project_dir / "agents.json", [])
    for agent in agents:
        agent.update(fetch_agent_card(agent))
        agent["updated_at"] = now_iso()
    write_json(project_dir / "agents.json", agents)
    return {"agents": agents}


@app.post("/api/projects/{project_name}/evals")
def add_eval(project_name: str, payload: EvalInput) -> dict[str, Any]:
    project_dir = existing_project_path(project_name)
    evals = read_json(project_dir / "evals.json", [])
    item = {
        "id": str(uuid.uuid4()),
        "name": clean_required(payload.name, "Eval name"),
        "prompt": clean_required(payload.prompt, "Prompt"),
        "expected_agent": clean_required(payload.expected_agent, "Expected agent"),
        "created_at": now_iso(),
    }
    evals.append(item)
    write_json(project_dir / "evals.json", evals)
    return {"eval": item}


@app.delete("/api/projects/{project_name}/evals/{eval_id}")
def delete_eval(project_name: str, eval_id: str) -> dict[str, Any]:
    project_dir = existing_project_path(project_name)
    evals = read_json(project_dir / "evals.json", [])
    next_evals = [item for item in evals if item["id"] != eval_id]
    write_json(project_dir / "evals.json", next_evals)
    return {"removed": len(evals) - len(next_evals)}


@app.get("/api/projects/{project_name}/runs")
def list_runs(project_name: str) -> dict[str, Any]:
    project_dir = existing_project_path(project_name)
    return {"runs": read_json(project_dir / "runs.json", [])}


@app.post("/api/projects/{project_name}/runs")
def run_evals(project_name: str) -> dict[str, Any]:
    project_dir = existing_project_path(project_name)
    agents = read_json(project_dir / "agents.json", [])
    evals = read_json(project_dir / "evals.json", [])
    if not agents:
        raise HTTPException(status_code=400, detail="Add at least one agent before running evals.")
    if not evals:
        raise HTTPException(status_code=400, detail="Add at least one eval before running.")

    results = [score_eval(item, agents) for item in evals]
    correct = len([item for item in results if item["correct"]])
    run = {
        "id": str(uuid.uuid4()),
        "created_at": now_iso(),
        "summary": {
            "total": len(results),
            "correct": correct,
            "accuracy": round((correct / len(results)) * 100, 2) if results else 0,
        },
        "results": results,
    }
    runs = read_json(project_dir / "runs.json", [])
    runs.insert(0, run)
    write_json(project_dir / "runs.json", runs)
    return {"run": run, "runs": runs}


@app.get("/api/settings/llm")
def get_llm_settings() -> dict[str, Any]:
    return {"settings": read_json(DATA_DIR / "llm.config", {})}


@app.put("/api/settings/llm")
def save_llm_settings(payload: LlmSettings) -> dict[str, Any]:
    provider = payload.provider.lower()
    if provider not in PROVIDERS:
        raise HTTPException(status_code=400, detail="Unsupported LLM provider.")
    settings = {
        "provider": provider,
        "key_env_name": clean_optional(payload.key_env_name),
        "masked_api_key": mask_key(payload.api_key) if payload.api_key else None,
        "updated_at": now_iso(),
    }
    write_json(DATA_DIR / "llm.config", settings)
    return {"settings": settings}


def fetch_agent_card(agent: dict[str, Any]) -> dict[str, Any]:
    url = normalize_agent_url(agent["url"])
    headers = {"accept": "application/json, application/a2a+json"}
    env_name = agent.get("auth_env_name")
    if env_name:
        token = os.environ.get(env_name)
        if token:
            headers["authorization"] = f"Bearer {token}"
    request = Request(url, headers=headers)
    try:
        with urlopen(request, timeout=10) as response:
            body = response.read().decode("utf-8")
            return {
                "url": url,
                "status": "ok",
                "http_status": response.status,
                "agent_card": json.loads(body),
                "last_fetched_at": now_iso(),
                "error": None,
            }
    except HTTPError as error:
        return failed_fetch(url, f"HTTP {error.code}: {error.read().decode('utf-8', 'ignore')[:200]}")
    except (URLError, TimeoutError, json.JSONDecodeError) as error:
        return failed_fetch(url, str(error))


def failed_fetch(url: str, error: str) -> dict[str, Any]:
    return {
        "url": url,
        "status": "error",
        "http_status": None,
        "agent_card": None,
        "last_fetched_at": now_iso(),
        "error": error,
    }


def normalize_agent_url(value: str) -> str:
    value = value.strip()
    if "/.well-known/agent-card.json" in value:
        return value
    if not re.match(r"^https?://", value):
        value = f"https://{value}"
    return f"{value.rstrip('/')}/.well-known/agent-card.json"


def score_eval(item: dict[str, Any], agents: list[dict[str, Any]]) -> dict[str, Any]:
    ranked = sorted(
        [agent_score(item["prompt"], agent) for agent in agents],
        key=lambda value: value["score"],
        reverse=True,
    )
    best = ranked[0] if ranked else None
    selected = best["agent_name"] if best and best["score"] > 0 else None
    expected = item["expected_agent"]
    return {
        "eval_id": item["id"],
        "name": item["name"],
        "prompt": item["prompt"],
        "expected_agent": expected,
        "selected_agent": selected,
        "correct": selected == expected,
        "confidence": best["score"] if best else 0,
        "reason": best["reason"] if best else "No agents available.",
        "ranking": ranked[:5],
    }


def agent_score(prompt: str, agent: dict[str, Any]) -> dict[str, Any]:
    card = agent.get("agent_card") or {}
    haystack = " ".join(
        [
            agent.get("name") or "",
            card.get("name") or "",
            card.get("description") or "",
            *skill_texts(card.get("skills") or []),
        ]
    )
    prompt_tokens = set(tokens(prompt))
    text_tokens = set(tokens(haystack))
    hits = sorted(prompt_tokens.intersection(text_tokens))
    score = round(len(hits) / len(prompt_tokens), 4) if prompt_tokens else 0
    return {
        "agent_id": agent.get("id"),
        "agent_name": agent.get("name"),
        "score": score,
        "reason": f"Matched tokens: {', '.join(hits) if hits else 'none'}",
    }


def skill_texts(skills: list[dict[str, Any]]) -> list[str]:
    values = []
    for skill in skills:
        values.extend(
            [
                skill.get("id") or "",
                skill.get("name") or "",
                skill.get("description") or "",
                " ".join(skill.get("tags") or []),
                " ".join(skill.get("examples") or []),
            ]
        )
    return values


def tokens(value: str) -> list[str]:
    stop_words = {"a", "an", "and", "are", "for", "from", "how", "i", "is", "it", "my", "of", "on", "the", "to", "with"}
    return [
        token
        for token in re.sub(r"[^a-z0-9]+", " ", value.lower()).split()
        if len(token) > 1 and token not in stop_words
    ]


def validate_project_name(name: str) -> str:
    value = name.strip()
    if not PROJECT_RE.match(value):
        raise HTTPException(status_code=400, detail="Use a single word project name. Letters, numbers, and underscores only.")
    return value


def project_path(name: str) -> Path:
    return DATA_DIR / validate_project_name(name)


def existing_project_path(name: str) -> Path:
    path = project_path(name)
    if not path.exists() or not path.is_dir():
        raise HTTPException(status_code=404, detail="Project not found.")
    return path


def read_json(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    return json.loads(path.read_text())


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(f"{path.suffix}.{os.getpid()}.tmp")
    temp.write_text(json.dumps(value, indent=2) + "\n")
    temp.replace(path)


def clean_required(value: str, field: str) -> str:
    cleaned = value.strip()
    if not cleaned:
        raise HTTPException(status_code=400, detail=f"{field} is required.")
    return cleaned


def clean_optional(value: str | None) -> str | None:
    cleaned = (value or "").strip()
    return cleaned or None


def mask_key(value: str | None) -> str | None:
    if not value:
        return None
    if len(value) <= 8:
        return "*" * len(value)
    return f"{value[:4]}...{value[-4:]}"


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()
