# Rubik's Cube Race: fast decision models vs a frontier LLM (OpenRouter)

Python 3.10+ · FastAPI backend · plain HTML/JS frontend · own deterministic cube engine.

## Setup
```bash
python -m venv .venv && source .venv/bin/activate      
pip install -r requirements.txt
cp .env.example .env       
uvicorn main:app --app-dir backend --reload
```
Open http://127.0.0.1:8000. The key lives only in the backend `.env` and is never sent to the browser.
`MOCK_MODE=1` runs simulated players so you can test the UI offline (do not use for the graded benchmark).

## Design
- `backend/cube.py`: 54-facelet URFDLB state, 18 moves (HTM: quarter and half turns each count 1), solved check, random scramble, exact shortest distance (meet-in-the-middle BFS, exact when distance <= 8).
- `backend/models.py`: Decisions API adapter (`/api/alpha/decisions`, typed `choice` question, 18 move options) for Jev / Luna / Clef and chat-completions adapter (JSON-schema enum) for Opus. Same prompt wording, move list, recent-move policy (last 6), timeout and retry policy for all.
- `backend/main.py`: run orchestration. Per puzzle all four models start from the same state and play concurrently. Limits: 30 turns, 300 s per trial. Reaching either limit = NOT solved. An invalid/malformed output (after retries) is logged and counted, never converted into a move, and it consumes one turn.
- Metrics: per-move latency (includes retries), total solve time, moves, success rate, optimal gap = model moves − exact shortest (solved trials, scramble <= 8 turns; extension puzzles show gap as unknown). Full results saved to `results/run_<id>.json`.
