# Rubik's Cube Race: fast decision models vs a frontier LLM (OpenRouter)

**Student:** Zunaira Amjad · **Roll no:** 23k-0013

## 🎥 Demo video
**[Watch the demo here](https://drive.google.com/file/d/1wt6mOHxI075UBCFN9JgdR9S6II67vx5G/view?usp=sharing)**

<!-- To upload the video: on github.com open README.md, click the pencil (edit) icon, and drag your .mp4 into the editor.
     GitHub gives you a link and plays it inline (max 100 MB). Or paste a Google Drive / YouTube (unlisted) link above. -->

Python 3.10+ · FastAPI backend · plain HTML/JS frontend · own deterministic cube engine.

## Setup
```bash
python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env             # Windows: copy .env.example .env  (then add your OpenRouter key)
uvicorn main:app --app-dir backend --reload
```
Open http://127.0.0.1:8000. The key lives only in the backend `.env` and is never sent to the browser.
`MOCK_MODE=1` runs simulated players so you can test the UI offline (not used for the graded benchmark).

## Design
- `backend/cube.py`: 54-facelet URFDLB state, 18 moves (HTM: quarter and half turns each count 1), solved check, random scramble, exact shortest distance (meet-in-the-middle BFS, exact when distance <= 8).
- `backend/models.py`: Decisions API adapter (`/api/alpha/decisions`, typed `choice` question, 18 move options) for Jev / Luna / Clef and a chat-completions adapter (JSON-schema enum) for Opus. Same prompt wording, move list, recent-move policy (last 6), timeout and retry policy for all.
- `backend/main.py`: run orchestration. Per puzzle all four models start from the same state and play concurrently. Limits: 30 turns, 300 s per trial. Reaching either limit = NOT solved. An invalid/malformed output (after retries) is logged and counted, never converted into a move, and it uses up one turn.
- Metrics: per-move latency (includes retries), total solve time, moves, success rate, optimal gap = model moves − exact shortest (solved trials, scramble <= 8 turns). Full results are saved to `results/run_<id>.json`.

## Results (primary benchmark: 5 puzzles, 4–5 move scrambles)

| Model | Solved | Success | Avg latency / move | Avg total time | Avg moves | Invalid | Retries |
|---|---|---|---|---|---|---|---|
| Jev 1.13 | 0/5 | 0% | 0.76 s | 0:22.66 | 30.0 | 0 | 0 |
| GPT-6 Luna Decisions | 0/5 | 0% | 0.84 s | 0:27.82 | 17.2 | 64 | 64 |
| Cloudflare Clef | 0/5 | 0% | 1.51 s | 0:45.17 | 30.0 | 0 | 1 |
| Claude Opus 5.5 | 0/5 | 0% | 17.05 s | 5:00.01 | 15.2 | 2 | 5 |

Optimal gap is blank for every model because none of them solved a puzzle.

## Answers

**1. Which model is fastest at making decisions?**
Jev 1.13, at about 0.76 s per move. Luna is right behind it (0.84 s). Opus is the slowest at 17 s per move, roughly 22× slower than Jev.

**2. Which model had the highest solve rate?**
Nobody. All four solved 0 out of 5, so it's a four-way tie at 0%.

**3. Which model found the shortest solutions, and how close to the optimum?**
None, since no model solved a puzzle. The scrambles were only 4–5 moves, so the best possible answer was 5 moves or fewer, and every model stayed far from that within the 30-move limit.

**4. Did the fastest model also give the best solution quality?**
No. Jev was the fastest, but it still used all 30 moves every time without solving anything. Being quick didn't help it, and being slow didn't help Opus either.

**5. Fast decision model, frontier LLM, or a hybrid?**
From this experiment I wouldn't trust any of them to solve the cube on their own. The fast models were quick but didn't solve anything, and Opus was too slow, with every run hitting the 5-minute limit after only about 15 moves. Luna also gave 64 unusable answers. For a real application I'd use a hybrid: a classic solver (like Kociemba's algorithm) for the actual solving, and a model only for the parts it's good at, like explaining moves or talking to the user. Models should only take over the cube itself if a later test shows them solving puzzles reliably.

**Caveats:** only 5 puzzles per model, and each model chose one move at a time with a short move history. Different prompting, or giving models more of the history, could change the results.
