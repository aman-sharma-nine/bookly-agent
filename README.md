# Bookly Agent

A demo customer-support agent for **Bookly**, a fictional online bookstore, built with the [OpenAI Agents SDK](https://github.com/openai/openai-agents-python). All order, customer, and policy data is synthetic and lives in `data.py` — there is no real backend behind it.

The interesting part of this project isn't the chat UI, it's the boundary between what the model decides and what's independently enforced in code: refund limits, replacement eligibility, return eligibility, and identity verification are all checked in `policies.py`/`tools.py`, not left to the model to police itself against prompt text alone.

## What the agent can do

The agent has eight tools:

| Tool | Purpose |
|---|---|
| `get_order` | Look up an order and its book context — status, tracking, delivery date, value, replacement eligibility. |
| `send_express_replacement` | Simulate sending a free express replacement for a delayed order, subject to policy. |
| `issue_refund` | Simulate issuing a refund, subject to a deterministic autonomous refund limit and collector-edition review. |
| `request_return` | Create a return request for a delivered, return-eligible order; automatically opens a human-review case for collector editions or high-value returns. |
| `search_policy` | Look up Bookly's shipping, returns, payments, and password-reset policies from a fixed knowledge base — never invents an answer. |
| `verify_identity` | Deterministically verify a customer's identity by matching a stated email against the account on file. |
| `send_password_reset` | Send a password-reset link, but only for a customer_id that `verify_identity` has already confirmed in the same conversation. |
| `escalate_case` | Open a human-review case for a customer's order, with a neutral, non-accusatory reason. |

### Workflows

- **Delayed-order lookup and express replacement** — the agent looks up an order, explains its status, and — if the customer agrees — arranges an express replacement when one is available and the order hasn't already shipped.
- **Refund eligibility and deterministic limits** — refunds up to a fixed autonomous limit are issued directly; refunds above that limit, or involving a collector edition, are declined for autonomous processing and routed for human review instead.
- **Return-request eligibility and human review** — a return can be requested for a delivered, return-eligible order within its return window; a collector edition or high-value item is routed to a real, idempotent human-review case rather than being silently approved or rejected.
- **Shipping and returns policy lookup** — general policy questions (shipping methods and prices, delivery estimates, returns, payments, password reset) are answered only from `data.py`'s fixed knowledge base; an unmatched question is reported as unknown, never guessed.
- **Identity verification and password-reset flow** — the agent never asks for a customer's current password. To send a reset link, it must first get a matching account email from the customer and confirm it via `verify_identity`; a conversational claim of identity ("it's me") is not sufficient on its own.
- **Escalation for cases requiring human review** — refund, return, and dispute cases that fall outside autonomous authority are escalated to a human-review case with a case ID and a neutral (never accusatory) reason, and never claimed as an approval.

## Architecture

This project deliberately separates four responsibilities:

- **The LLM** interprets the customer's intent, handles ambiguity, asks clarifying questions when information is missing, and decides which tool (if any) to call and when. It never has direct write access to order data or policy limits.
- **Tools** (`tools.py`) retrieve authoritative synthetic data from `data.py` or simulate a customer-support action (replacement, refund, return, escalation, password reset). Every tool is a plain, directly testable Python function, wrapped separately as an Agents SDK `FunctionTool` for the agent to call.
- **Python business logic** (`policies.py`, plus deterministic checks inside `tools.py`) independently enforces refund limits, replacement eligibility, return eligibility, and review requirements — these rules are checked in code every time a tool runs, regardless of what the model asks for or what the prompt says.
- **`messages.py`** is the single, centralized source of customer-safe text: every tool result gets a `customer_message` and, where relevant, a `next_step`, mapped from stable internal reason codes to neutral, non-blaming language. No tool branch writes its own ad hoc customer-facing wording.
- **The UI** (`app.py`, `ui/`) renders the model's final response, a collapsible tool-activity trace, and action cards for completed/blocked/review-required actions — all sourced from the same `customer_message`/`next_step` fields, so the trace and the reply never say different things.

The model is instructed never to invent order facts and never to claim an action succeeded unless a tool result actually confirms it — and because the underlying policy checks are enforced in code, that instruction is a backstop, not the only thing standing between a customer and an unauthorized action.

## Project structure

```
agent.py          # Agent definition, model configuration, session handling, and tool wiring
app.py             # Streamlit customer-support application
prompts.py         # CX behavior, tool-use, clarification, and response rules
tools.py           # Eight support tools and workflow orchestration
policies.py        # Deterministic business-rule checks
messages.py        # Centralized customer-safe messages and next steps
data.py            # Synthetic orders, customers, policies, and demo state
ui/trace.py        # Tool trace extraction and action-card rendering
ui/styles.py       # Streamlit styling
evals/             # Scenario cases, graders, and evaluation harness
tests/             # Offline unit and contract tests
```

## Setup

Requires Python 3.10 or newer and an OpenAI API key.

```bash
git clone https://github.com/aman-sharma-nine/bookly-agent.git
cd bookly-agent
python3 -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env
```

Then edit `.env` and set your real key:

```
OPENAI_API_KEY=your_api_key_here
```

## Try the demo

```bash
streamlit run app.py
```

Opens a Streamlit chat interface. Each browser session gets its own in-memory conversation (via `SQLiteSession`) — history doesn't persist across restarts. All order IDs below are synthetic demo fixtures from `data.py`, not real orders.

Things to try:

- "Where is order B1001?"
- "My order is late and it is for my daughter's birthday."
- "Can I return order B1023?"
- "What are your shipping options?"
- "I forgot my password."
- "I need a refund for order B1002."

### Command line

```bash
python agent.py
```

Runs a short scripted conversation against the agent and prints each turn to stdout — a quick sanity check without the UI.

## Testing and evaluation

### Offline unit and contract tests

No API calls, no live agent runs — pure Python logic and data-shape checks:

```bash
python -m unittest discover -s tests
```

Currently: 188 tests, all passing.

### Live evaluation suite

`evals/` holds a 33-case scenario suite covering delayed orders, refunds, returns, policy lookup, identity verification, and escalation. It runs against the *real* agent and grades observable behavior:

```bash
python -m evals.run_evals --label my-run --split all --mode code_only
```

- **`code_only` mode (default)** — deterministic checks only (tool name, arguments, call order, forbidden calls, a handful of pattern-matched hard-failure conditions). Still calls the live agent, so it requires `OPENAI_API_KEY`.
- **`full` mode** — runs the deterministic checks and adds a separate model-based qualitative grader for observable qualities such as tone, judgement, context use, customer effort, and explanation quality. Set `BOOKLY_GRADER_MODEL` in `.env` to a model different from the agent's model (`gpt-5.6`) before running it:

  ```bash
  BOOKLY_GRADER_MODEL=your-separate-grader-model
  python -m evals.run_evals --label my-qualitative-run --split all --mode full
  ```

  The grader is never allowed to be the same model as the agent. If it is not configured, qualitative cases are reported as `not_scored` rather than being treated as passed.

Results are written to `evals/results/` and appended to `evals/results/history.csv` (both untracked/local — see `.gitignore`).

The suite has development and held-out cases. The `S-01` identity/ownership case is intentionally blocked because production authentication is outside this demo's scope, so an `all` run executes 32 of the 33 cases. Overall results can be `passed`, `failed`, `not_scored`, or `blocked`.

Use deterministic results for hard behavioral guarantees such as correct tool use, policy enforcement, forbidden actions, and false-success claims. Use qualitative results as model-judged signals for communication and judgement, not as a universal accuracy score. Always record the agent model, grader model, prompt version, and result file when comparing runs.

## Limitations

This is a local prototype, and its boundaries are deliberate, not oversights:

- All order, customer, and policy data is synthetic (`data.py`) — there is no real inventory, catalog, or customer database behind it.
- Every support action (replacement, refund, return, escalation, password reset) is simulated in memory; nothing is sent to a real carrier, payment processor, or email system.
- Conversation sessions are in-memory only (`SQLiteSession`) and reset on restart — there is no persistent chat history.
- There is no production authentication or order-ownership enforcement: any session can look up any order ID by number.
- `verify_identity` is a demo-grade email match against synthetic data, not production identity-verification infrastructure (no OTP, no session-bound login, no MFA).
- There is no integration with a real payment provider, logistics/carrier system, transactional email service, or identity provider.
- The Streamlit app is a local, single-process demo, not a deployed or multi-tenant service.
