"""System drivers for evaluation: Claude Code and Expert-Service RAG."""

import asyncio
import json
import os
import time
from dataclasses import dataclass, field
from uuid import uuid4

import httpx


@dataclass
class DriverResponse:
    text: str
    tool_calls: list[dict] = field(default_factory=list)
    latency_seconds: float = 0.0
    cost_usd: float | None = None
    num_turns: int | None = None


class ClaudeCodeDriver:
    """Run claude -p from a knowledge base directory."""

    def __init__(self, cwd: str):
        self.cwd = os.path.expanduser(cwd)

    async def ask(self, question: str) -> DriverResponse:
        prompt = (
            "Answer this question using only the knowledge available in this repository. "
            "Search the sources, entries, and beliefs to find the answer.\n\n"
            f"{question}\n\n"
            "End your response with:\nANSWER: <letter>"
        )
        env = {k: v for k, v in os.environ.items() if k != "CLAUDECODE"}

        t0 = time.monotonic()
        proc = await asyncio.create_subprocess_exec(
            "claude", "-p", "--output-format", "json", prompt,
            cwd=self.cwd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=env,
        )
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=300)
        elapsed = time.monotonic() - t0

        text = stdout.decode()
        tool_calls = []

        # Parse JSON output if available
        try:
            data = json.loads(text)
            if isinstance(data, dict):
                text = data.get("result", text)
                # Extract tool usage from cost_usd or messages
                if "messages" in data:
                    for msg in data["messages"]:
                        if msg.get("type") == "tool_use":
                            tool_calls.append({
                                "name": msg.get("name", "unknown"),
                                "args": msg.get("input", {}),
                            })
            elif isinstance(data, list):
                # Stream JSON format — list of message objects
                parts = []
                for msg in data:
                    role = msg.get("role", "")
                    if role == "assistant":
                        for block in msg.get("content", []):
                            if block.get("type") == "text":
                                parts.append(block["text"])
                            elif block.get("type") == "tool_use":
                                tool_calls.append({
                                    "name": block.get("name", "unknown"),
                                    "args": block.get("input", {}),
                                })
                text = "\n".join(parts) if parts else text
        except (json.JSONDecodeError, KeyError):
            pass  # Use raw text

        cost = None
        num_turns = None
        try:
            raw = json.loads(stdout.decode())
            if isinstance(raw, dict):
                cost = raw.get("total_cost_usd")
                num_turns = raw.get("num_turns")
        except (json.JSONDecodeError, KeyError):
            pass

        return DriverResponse(
            text=text, tool_calls=tool_calls, latency_seconds=elapsed,
            cost_usd=cost, num_turns=num_turns,
        )


class ExpertServiceDriver:
    """Call expert-service chat API with SSE streaming."""

    def __init__(self, base_url: str, project_id: str, model: str):
        self.base_url = base_url.rstrip("/")
        self.project_id = project_id
        self.model = model

    async def ask(self, question: str) -> DriverResponse:
        prompt = f"{question}\n\nEnd your response with:\nANSWER: <letter>"
        url = f"{self.base_url}/api/projects/{self.project_id}/chat"
        payload = {
            "message": prompt,
            "model": self.model,
            "thread_id": str(uuid4()),
        }

        tokens = []
        tool_calls = []
        current_event = None

        t0 = time.monotonic()
        async with httpx.AsyncClient(timeout=httpx.Timeout(300.0)) as client:
            async with client.stream("POST", url, json=payload) as resp:
                resp.raise_for_status()
                async for line in resp.aiter_lines():
                    line = line.strip()
                    if not line:
                        current_event = None
                        continue
                    if line.startswith("event: "):
                        current_event = line[7:]
                    elif line.startswith("data: "):
                        data_str = line[6:]
                        try:
                            data = json.loads(data_str)
                        except json.JSONDecodeError:
                            continue

                        if current_event == "tool_call":
                            tool_calls.append({
                                "name": data.get("name", "unknown"),
                                "args": data.get("args", {}),
                            })
                        elif current_event == "tool_result":
                            pass  # Captured in tool_calls already
                        elif current_event == "done":
                            break
                        elif data.get("type") == "token":
                            tokens.append(data.get("content", ""))

        elapsed = time.monotonic() - t0
        return DriverResponse(
            text="".join(tokens),
            tool_calls=tool_calls,
            latency_seconds=elapsed,
        )
