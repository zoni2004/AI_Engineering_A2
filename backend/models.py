"""OpenRouter adapters. Both interfaces expose the same contract: get_move(...) -> {move, confidence, latency, ...}."""
import json, os, time
import httpx
from cube import MOVES

API_BASE = "https://openrouter.ai/api"
REQUEST_TIMEOUT = float(os.getenv("REQUEST_TIMEOUT_S", "60"))
MAX_RETRIES = int(os.getenv("MAX_RETRIES", "1"))  # identical for every model

MODELS = {
    "jev": {"label": "Jev 1.13", "kind": "decision", "id": os.getenv("MODEL_JEV", "typesafe/jev-1.13")},
    "luna": {"label": "GPT-6 Luna Decisions", "kind": "decision", "id": os.getenv("MODEL_LUNA", "openai/gpt-6-luna-decisions")},
    "clef": {"label": "Cloudflare Clef", "kind": "decision", "id": os.getenv("MODEL_CLEF", "cloudflare/clef")},
    "opus": {"label": "Claude Opus 5.5", "kind": "llm", "id": os.getenv("MODEL_OPUS", "anthropic/claude-opus-5.5")},
}

FACE_NAME = {"U": "upper", "R": "right", "F": "front", "D": "down", "L": "left", "B": "back"}
LAYOUT = ("54 chars: faces in order U,R,F,D,L,B, 9 stickers each, row-major as seen looking at that face from outside "
          "(U: back row first; D: front row first). Each char is the face whose centre that colour belongs to. "
          "Solved = " + "".join(f * 9 for f in "URFDLB") + ". Moves are standard: X = 90 deg clockwise viewed from "
          "face X, X' = counterclockwise, X2 = 180 deg.")
INSTRUCTIONS = "Choose the single next move most likely to progress toward the solved cube."


def move_desc(m):
    how = {"": "clockwise by 90 degrees", "'": "counterclockwise by 90 degrees", "2": "by 180 degrees"}[m[1:]]
    return f"Turn the {FACE_NAME[m[0]]} face {how}"


class InvalidMove(Exception):
    pass


def _headers():
    key = os.getenv("OPENROUTER_API_KEY")
    if not key:
        raise RuntimeError("OPENROUTER_API_KEY is not set (backend .env)")
    return {"Authorization": f"Bearer {key}", "Content-Type": "application/json",
            "X-Title": "Rubik's Cube Race"}


def _post(client, path, payload):
    return client.post(API_BASE + path, json=payload, headers=_headers(), timeout=REQUEST_TIMEOUT)


def extract_decision(resp, valid=frozenset(MOVES)):
    """Tolerant parser for the (alpha) Decisions response: finds the 'next_move' answer + any confidence."""
    def find(o, key):
        if isinstance(o, dict):
            if key in o:
                return o[key]
            for v in o.values():
                r = find(v, key)
                if r is not None:
                    return r
        elif isinstance(o, list):
            for v in o:
                r = find(v, key)
                if r is not None:
                    return r
        return None

    node = find(resp, "next_move")
    node = resp if node is None else node
    conf = None
    for k in ("confidence", "probability", "score"):
        c = find(node, k)
        if isinstance(c, (int, float)):
            conf = float(c)
            break
    if isinstance(node, str) and node in valid:
        return node, conf
    if isinstance(node, dict):
        for k in ("choice", "selected", "selection", "answer", "value", "option", "decision", "result"):
            v = node.get(k)
            if isinstance(v, dict):  # e.g. {"choice": {"key": "R"}}
                v = next((x for x in v.values() if x in valid), None)
            if v in valid:
                return v, conf
        for k in ("probabilities", "scores", "distribution"):
            d = node.get(k)
            if isinstance(d, dict) and d and all(x in valid for x in d):
                best = max(d, key=lambda x: d[x])
                return best, float(d[best])
        v = next((x for x in node.values() if isinstance(x, str) and x in valid), None)
        if v:
            return v, conf
    raise InvalidMove("no legal move in decision response: " + json.dumps(resp)[:200])


async def _decision(client, spec, facelets, recent, left):
    payload = {
        "model": spec["id"],
        "state": {"cube_facelets": facelets, "layout": LAYOUT, "recent_moves": recent, "moves_remaining": left},
        "questions": {"next_move": {"type": "choice", "instructions": INSTRUCTIONS,
                                    "criteria": {m: move_desc(m) for m in MOVES}}},
    }
    r = await _post(client, "/alpha/decisions", payload)
    if r.status_code >= 400:
        raise RuntimeError(f"HTTP {r.status_code}: {r.text[:200]}")
    return extract_decision(r.json())


async def _chat(client, spec, facelets, recent, left):
    user = (f"Cube state (facelets): {facelets}\nLayout: {LAYOUT}\nRecent moves: {recent}\nMoves remaining: {left}\n"
            f"Allowed moves: {', '.join(MOVES)}\n{INSTRUCTIONS}\nReply with exactly one move as JSON: {{\"move\": \"R'\"}}")
    payload = {
        "model": spec["id"],
        "messages": [{"role": "system", "content": "You are a Rubik's Cube move selector. Output only JSON."},
                     {"role": "user", "content": user}],
        "max_tokens": 2048,
        "response_format": {"type": "json_schema", "json_schema": {"name": "move", "strict": True, "schema": {
            "type": "object", "properties": {"move": {"type": "string", "enum": MOVES}},
            "required": ["move"], "additionalProperties": False}}},
    }
    r = await _post(client, "/v1/chat/completions", payload)
    if r.status_code >= 400:
        raise RuntimeError(f"HTTP {r.status_code}: {r.text[:200]}")
    text = (r.json()["choices"][0]["message"].get("content") or "").strip()
    text = text.removeprefix("```json").removeprefix("```").removesuffix("```").strip()
    move = json.loads(text).get("move")
    if move not in MOVES:
        raise InvalidMove(f"illegal move {move!r}")
    return move, None


async def get_move(client, spec, facelets, recent, left):
    """Same timeout/retry policy for every model. Invalid outputs are logged, never silently converted."""
    t0, err = time.perf_counter(), None
    for attempt in range(1 + MAX_RETRIES):
        try:
            fn = _decision if spec["kind"] == "decision" else _chat
            move, conf = await fn(client, spec, facelets, recent, left)
            return {"move": move, "confidence": conf, "latency": time.perf_counter() - t0, "retries": attempt, "error": None}
        except Exception as e:  # malformed output, HTTP error, timeout
            err = f"{type(e).__name__}: {e}"[:250]
    return {"move": None, "confidence": None, "latency": time.perf_counter() - t0, "retries": MAX_RETRIES, "error": err}
