# Learning journal — Bookly CX agent (Steps 9–16)

Personal notes, written after the fact, on what actually happened building this — not a status report, just the things worth remembering next time.

## The big one: measure before you touch anything

The whole arc only worked because of the discipline in Step 15's framing: *build the harness before you trust its numbers, and don't change the thing you're measuring while you're still debugging the measurement.* I broke this rule's spirit a couple of times in small ways and it always cost time later:

- When I first ran the Step 16 model comparison, I found `fabricated_action` failures against `gpt-5.6` that turned out to be 100% false positives in the grader, not real problems with the model. If I'd trusted the raw numbers and reported "gpt-5.6 fabricates success claims," that would have been a wrong conclusion baked into a permanent decision.
- The fix: when the user explicitly said "don't touch the grader" during the comparison, I didn't — I manually corrected the numbers in the report and left a paper trail. Only in the *next* explicit request did I fix the grader itself, with regression tests built from the exact failing transcripts. Separating "notice the bug" from "fix the bug" in time turned out to matter, not just as a formality — it kept the comparison run and the fix run each individually trustworthy.

## Heuristic text-matching graders are fragile in ways that are hard to anticipate

The `SUCCESS_CLAIM_PATTERN` regex went through three rounds of bugs, each only visible once a *different* model or a *different* phrasing style hit it:

1. First bug: no negation check at all — "please allow a few days" flagged as an invented timeframe when it should've been fine, and vice versa.
2. Second bug: negation check existed but only looked *before* the match, in a fixed character window, and that window didn't tolerate markdown (`**not**` broke it) or long-distance cues (`"No refund was issued"` — the negation is at the start of the sentence, way outside a 25-character lookback).
3. Third bug, found only when comparing against `gpt-5.6`: `refunded?` (with the `?` making the "-ed" optional) matched the bare noun "refund" as if it were a completion claim — "I can issue **a refund**" tripped the same check as "your refund has been issued."

None of these were visible against `gpt-4` in isolation. They only surfaced because a different model phrased things differently. **Lesson: a regex-based grader tuned against one model's writing style is quietly overfit to that style.** If I build another one of these, I'd either (a) test it against at least two different models' phrasing before trusting it, or (b) just use a real LLM grader for anything involving negation/claim detection instead of pattern matching — Anthropic's own guidance about this ("LLM binary classification" being the right shape for exactly this kind of check) turned out to be right, and I under-invested in the LLM-graded path relative to how much time the regex path ended up costing.

## A grader model must never grade under a corrupted premise

Found late: my `grade_qualitative()` function force-overrode `passed=False` whenever a deterministic hard-failure was detected — reasonable in principle ("a hard failure should never be rescued by a soft score") but it meant the qualitative grader's own independent judgment was silently discarded even when it disagreed. When I actually read the grader's `evidence` text for the false positives, some of them said things like *"does not falsely claim the replacement was sent and correctly reports the failure"* — a correct assessment — immediately followed by a forced `passed: False`. The override hid the model's own correct judgment from view. If the override hadn't existed, I would have caught the bug faster, because the qualitative grader's disagreement with the deterministic layer would have been visible as a signal, not silenced. **Lesson: when two independent checks can disagree, surface the disagreement — don't let one silently overrule the other without a visible trace.**

## "Confirmation before acting" isn't one rule, it's a per-action judgment call

I spent three separate iterations trying to get the agent to confirm before calling `get_order` in a context-injected scenario, using increasingly forceful prompt wording. None of it worked — the model consistently ignored the instruction for that specific case. Then, completely separately, the same model asked for confirmation *unprompted* before escalating a case (`escalate_case`), which nobody had told it to do.

What this actually revealed: the model's willingness to ask before acting isn't controlled by a single global instruction, it's sensitive to how much the *customer's own message* already justifies the action. A customer message that already states "it's delayed, it's a collector's edition, I want a refund" reads as enough justification to just resolve it. A customer message with less information in it reads as needing a check first. Fighting this with more prompt wording didn't work three times in a row — the fix that actually worked was accepting the model's judgment and correcting the *eval's expectation* to match, not the model's behavior. **Lesson: when a prompt change produces zero measurable effect twice in a row, stop iterating the prompt — the thing that needs to change might be the test, not the model.**

## Eval-only overrides need to preserve the tool's real name and shape

Building the Step 15 harness (`evals/harness.py`), the constraint that mattered most was: an eval-only wrapped tool has to be indistinguishable from the real one *to the model* — same name, same schema, same docstring shape — so the grader is testing the same tool-selection behavior it would see in production, not a harness artifact. The trick that made this clean: write the wrapper as a plain function with a factory (`make_get_order_wrapper(forced_value)` returning a real callable), decorate it with `function_tool()` only at the point of use. That kept the wrapper independently unit-testable (call it directly, no agent runtime needed) *and* kept the tool-name matching automatic (Python just uses the function's own `__name__`).

## Subset-matching on tool arguments, not exact-equality, from day one

Every tool that takes a `reason` argument (`issue_refund`, `escalate_case`) would have failed 100% of its eval cases under exact-argument-equality, the moment the agent correctly generated real reason text the case's `expected_tool_calls` didn't literally spell out. This was flagged and fixed before any grading code was written, which avoided a very avoidable category of false failures — worth remembering as a default assumption for *any* tool-calling eval, not just this project: **expected arguments are a required subset, never an exact match, unless a case has a specific reason to need one.**

## Data changes and eval changes need to move together, explicitly

Simplifying `B1002` (removing the deliberate "delivered but customer says never arrived" contradiction) had a blast radius I didn't fully see until I went looking: it touched the case that used it directly (`J2-02`), the case that shared it (`J2-06`, which had to be retired, not just moved to held-out — held-out doesn't fix a case testing data that no longer exists), a sibling task-ID reference in two *other* unrelated cases (`J2-01`, `J2-09`, which had been carrying a stale `J2.3` task tag for a scenario they never actually tested), and five separate places in the original planning narrative that described the old "delivered" scenario. None of these were hard to fix individually, but every one of them was found by deliberately grepping for the changed fact across the whole repo, not by memory. **Lesson: after a data-model change, grep for the old value across the whole project before declaring the change done — don't trust that you remember every place that referenced it.**

## Cost/latency numbers are only meaningful if you verify pricing, not guess it

Before reporting per-model cost estimates, I fetched the actual current pricing docs rather than relying on a remembered number — and it's a good thing I did, because I had no real basis for the exact `gpt-5.6` pricing tiers otherwise. A demo can tolerate a rough estimate; a decision ("switch the production model") should not be made on a guessed number dressed up as a measured one. Same principle as verifying the `reasoning.effort` parameter actually worked against the live API before assuming it from a doc citation — assumptions about a fast-moving API surface age badly, verify empirically when the cost of being wrong is a real recommendation.

## The uncomfortable one: my own reports contained real errors, more than once

A few times across this project, the person reviewing my work caught something I'd gotten wrong — an inconsistent summary line, a heuristic-grader false positive I hadn't looked closely enough at, a "13/16" table that (from their side) read as incomplete. Not all of these turned out to be *my* error on inspection (one "inconsistency" they flagged wasn't actually present in what I'd sent), but several were real, and the ones that were real were only caught because someone else looked closely at output I'd already called "done." **Lesson: "the numbers look right" is not the same as "I verified the numbers," and a fresh pair of eyes reliably found things a second self-check pass by the same author did not.** Worth internalizing rather than getting defensive about — the corrections made the final artifact better every time.

## What I'd do differently starting over

- Build the LLM-based (not regex-based) hard-failure grader *first*, even for a demo, rather than reaching for regex because it's cheap and fast to write. The regex path felt faster in the moment and cost more time in aggregate once a second model exposed its blind spots.
- Test any text-pattern grader against at least two stylistically different model outputs before trusting it, not just the one model it was written against.
- When adding a "confirm before acting" rule, decide up front whether it's a per-tool property (replacement: yes: something the agent proposes) or a general instruction — don't assume a general prompt rule will generalize to a different action with a different justification shape.
