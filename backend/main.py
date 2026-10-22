import asyncio, json, os, random, time, uuid
from pathlib import Path
import httpx
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

load_dotenv(Path(__file__).parent.parent / ".env")
import cube
from models import MODELS, get_move

MAX_MOVES = int(os.getenv("MAX_MOVES", "30"))
TIME_LIMIT = float(os.getenv("TIME_LIMIT_S", "300"))
RECENT_N = int(os.getenv("RECENT_N", "6"))
MOCK = os.getenv("MOCK_MODE", "0") == "1"
ROOT = Path(__file__).parent.parent
app = FastAPI(title="Rubik's Cube Race")
RUNS = {}


class RunReq(BaseModel):
    scramble_min: int = 4
    scramble_max: int = 5
    puzzles: int = 5


@app.get("/api/config")
def config():
    return {"mock": MOCK, "max_moves": MAX_MOVES, "time_limit": TIME_LIMIT, "student": os.getenv("STUDENT_NAME", ""),
            "roll": os.getenv("ROLL_NO", ""), "has_key": bool(os.getenv("OPENROUTER_API_KEY")),
            "models": {k: {"label": v["label"], "kind": v["kind"], "id": v["id"]} for k, v in MODELS.items()}}


@app.post("/api/run")
async def start(req: RunReq):
    if not MOCK and not os.getenv("OPENROUTER_API_KEY"):
        raise HTTPException(400, "Set OPENROUTER_API_KEY in .env (or MOCK_MODE=1 to test the UI offline).")
    if not (1 <= req.scramble_min <= req.scramble_max <= 30 and 1 <= req.puzzles <= 50):
        raise HTTPException(400, "invalid scramble range / puzzle count")
    puzzles = []
    for i in range(req.puzzles):
        scr = cube.random_scramble(random.randint(req.scramble_min, req.scramble_max))
        st = cube.apply_moves(cube.SOLVED, scr)
        opt = await asyncio.to_thread(cube.optimal_distance, st)
        puzzles.append({"index": i, "scramble": scr, "state": st, "optimal": opt, "trials": {
            k: {"status": "waiting", "state": st, "moves": [], "latencies": [], "confidences": [], "retries": 0,
                "invalid": 0, "errors": [], "outcome": None, "start_ts": None, "end_ts": None, "elapsed": None}
            for k in MODELS}})
    run = {"id": uuid.uuid4().hex[:8], "status": "running", "mock": MOCK, "current": 0, "models": list(MODELS),
           "config": req.model_dump(), "puzzles": puzzles}
    RUNS[run["id"]] = run
    asyncio.create_task(execute(run))
    return {"id": run["id"]}


@app.get("/api/run/{rid}")
def poll(rid: str):
    run = RUNS.get(rid)
    if not run:
        raise HTTPException(404)
    return {**run, "server_time": time.time(), "summary": summarize(run)}


def _mean(xs):
    xs = [x for x in xs if x is not None]
    return sum(xs) / len(xs) if xs else None


def summarize(run):
    out = {}
    for k in run["models"]:
        ts = [(p, p["trials"][k]) for p in run["puzzles"] if p["trials"][k]["outcome"]]
        solved = [(p, t) for p, t in ts if t["outcome"] == "SOLVED"]
        out[k] = {
            "label": MODELS[k]["label"], "kind": MODELS[k]["kind"], "trials": len(ts), "solved": len(solved),
            "success_rate": 100 * len(solved) / len(ts) if ts else None,
            "avg_latency": _mean([x for _, t in ts for x in t["latencies"]]),
            "avg_total_time": _mean([t["elapsed"] for _, t in ts]),
            "avg_moves": _mean([len(t["moves"]) for _, t in ts]),
            "avg_moves_solved": _mean([len(t["moves"]) for _, t in solved]),
            "avg_gap": _mean([len(t["moves"]) - p["optimal"] for p, t in solved if p["optimal"] is not None]),
            "invalid": sum(t["invalid"] for _, t in ts), "retries": sum(t["retries"] for _, t in ts),
            "avg_confidence": _mean([c for _, t in ts for c in t["confidences"]]),
        }
    done = {k: v for k, v in out.items() if v["trials"]}
    hl = {}
    if done:
        lat = {k: v["avg_latency"] for k, v in done.items() if v["avg_latency"] is not None}
        gap = {k: v["avg_gap"] for k, v in done.items() if v["avg_gap"] is not None}
        top = max(v["success_rate"] for v in done.values())
        hl = {"fastest": min(lat, key=lat.get) if lat else None,
              "highest_solve_rate": [k for k, v in done.items() if v["success_rate"] == top],
              "best_gap": min(gap, key=gap.get) if gap else None}
        hl["fastest_is_best"] = hl["fastest"] is not None and hl["fastest"] == hl["best_gap"] and hl["fastest"] in hl["highest_solve_rate"]
    return {"models": out, "highlights": hl}


# ---- offline simulation so the UI can be tested without a key (NOT real model output) ----------
_PROFILE = {"jev": (0.15, 0.35), "luna": (0.25, 0.30), "clef": (0.10, 0.45), "opus": (2.5, 0.05)}  # (latency s, error rate)


async def mock_move(key, t, plan):
    lat, err = _PROFILE[key]
    await asyncio.sleep(lat * random.uniform(0.7, 1.3))
    if plan and random.random() > err:
        m = plan.pop(0)
    else:
        m = random.choice(cube.MOVES)
        plan.insert(0, cube.inverse(m))
    return {"move": m, "confidence": None, "latency": lat, "retries": 0, "error": None}


async def play(run, p, key, client):
    t, spec, state = p["trials"][key], MODELS[key], p["state"]
    plan = [cube.inverse(m) for m in reversed(p["scramble"])]
    t0 = time.perf_counter()
    t["start_ts"], t["status"] = time.time(), "thinking"
    try:
        for _ in range(MAX_MOVES):  # every turn (valid or invalid) consumes one slot of the move budget
            remaining = TIME_LIMIT - (time.perf_counter() - t0)
            if remaining <= 0:
                raise asyncio.TimeoutError
            coro = mock_move(key, t, plan) if MOCK else get_move(client, spec, state, t["moves"][-RECENT_N:], MAX_MOVES - len(t["moves"]))
            r = await asyncio.wait_for(coro, remaining)
            t["retries"] += r["retries"]
            if r["move"] is None:
                t["invalid"] += 1
                t["errors"] = (t["errors"] + [r["error"]])[-5:]
                continue
            state = cube.apply_move(state, r["move"])
            t["state"], t["current"] = state, r["move"]
            t["moves"].append(r["move"])
            t["latencies"].append(r["latency"])
            if r["confidence"] is not None:
                t["confidences"].append(r["confidence"])
            if cube.is_solved(state):
                t["outcome"] = "SOLVED"
                break
        else:
            t["outcome"] = "RAN_OUT_OF_MOVES"
    except asyncio.TimeoutError:
        t["outcome"] = "OUT_OF_TIME"
    t["elapsed"], t["end_ts"], t["status"] = time.perf_counter() - t0, time.time(), "done"


async def execute(run):
    try:
        async with httpx.AsyncClient() as client:
            for p in run["puzzles"]:
                run["current"] = p["index"]
                await asyncio.gather(*[play(run, p, k, client) for k in run["models"]])  # same state, models race in parallel
        run["status"] = "done"
    except Exception as e:
        run["status"], run["error"] = "error", str(e)
    (ROOT / "results").mkdir(exist_ok=True)
    (ROOT / "results" / f"run_{run['id']}.json").write_text(json.dumps({**run, "summary": summarize(run)}, indent=1))


app.mount("/", StaticFiles(directory=ROOT / "frontend", html=True), name="ui")
