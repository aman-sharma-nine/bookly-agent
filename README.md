# Bookly Agent

A demo customer-support agent for **Bookly**, a fictional online bookstore, built with the [OpenAI Agents SDK](https://github.com/openai/openai-agents-python).

The agent handles two customer journeys:

- **Delayed orders** — look up an order, explain its status, and offer an express replacement when appropriate.
- **Refund requests** — resolve straightforward refunds autonomously within a fixed dollar limit, and escalate anything above that limit or involving a collector's edition for human review.

The interesting part of this project isn't the chat UI, it's the boundary between what the model decides and what's independently enforced in code: refund authority and collector-edition review are checked in `policies.py`/`tools.py`, not left to the model to police itself against prompt text alone.

## Project layout

```
agent.py          # Agent definition, session handling, tool wiring
prompts.py        # System prompt: CX principles, operational policy, tool-use rules
tools.py          # The four tools the agent can call (order lookup, replacement, refund, escalation)
policies.py       # Independent enforcement of refund/escalation rules — the actual authority
data.py           # Mock order and customer data the tools read from
app.py            # Streamlit chat UI
ui/               # UI styling and trace-rendering helpers for the Streamlit app
evals/            # Eval suite, graders, and comparison scripts (see below)
tests/            # Offline unit tests (no API calls)
```

## Setup

Requires Python 3.10+ and an OpenAI API key.

```bash
git clone https://github.com/aman-sharma-nine/bookly-agent.git
cd bookly-agent
python -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

Create a `.env` file in the project root with your API key:

```
OPENAI_API_KEY=sk-...
```

## Usage

### Chat UI

```bash
streamlit run app.py
```

Opens a Streamlit chat interface. Each browser session gets its own in-memory conversation (via `SQLiteSession`) — history doesn't persist across restarts.

### Command line

```bash
python agent.py
```

Runs a short scripted conversation against the agent and prints each turn to stdout — a quick sanity check without the UI.

## Evals

The `evals/` directory holds a small suite of scripted conversations that check the agent's behavior against expected tool calls and outcomes, using a mix of deterministic checks (tool name/args/order) and model-based grading (tone, judgement, context use).

Run the suite against the live agent:

```bash
python -m evals.run_evals --label my-run
```

Useful flags:

- `--split {dev,held_out,all}` — which case split to run (default `dev`; held-out cases are meant to be run sparingly, not iterated against)
- `--mode {code_only,full}` — `full` also runs the model-based qualitative grader, which makes API calls and costs more

Results are written to `evals/results/` and appended to `evals/results/history.csv`.

### Model/reasoning comparison

`evals/run_model_comparison.py` runs the same suite across different model and reasoning-effort configurations to compare quality, latency, and cost:

```bash
python -m evals.run_model_comparison --config gpt-5.6-low --repeat 1
```

## Tests

Offline unit tests (no API calls, no live agent runs):

```bash
python -m unittest discover -s tests
```

## Notes

This is a demo project, not a production system. In particular:

- Sessions are in-memory only and not tied to any real customer authentication.
- There's no order-ownership check — any session can look up any order ID.
- The eval graders are a mix of deterministic and heuristic/model-based checks; they're a development aid, not a certification of correctness.
