"""The Step 5 eval suite (21 cases), as structured data.

Multi-order ambiguity (a customer citing two candidate order IDs) is
deliberately out of scope for this demo — the case that used to test it
(J1-03) was removed, deferred until multi-order support is in scope.
J1-01 still covers the in-scope half of J1.2/J1.3 (missing order number,
not ambiguous order number).

Conflicting delivery evidence (tracking says delivered, customer says it
never arrived) is likewise deliberately out of scope — B1002 was
simplified from "delivered" to "delayed" so J2-02's collector-edition
scenario is no longer self-contradictory, and the case that specifically
tested the conflict (J2-06) was removed rather than left to quietly test
data that no longer exists.

Each case follows this schema:

    case_id, journey, task_ids, criteria,
    conversation, available_context,
    expected_tool_calls, forbidden_tool_calls,
    expected_behaviours, hard_failure_conditions, grader_type

`available_context` points at real IDs in data.py (BOOKLY_DATA) rather than
duplicating order/customer facts here, so a data.py change can't silently
drift out of sync with the eval suite. `task_ids` trace back to the Step 3
task table; `criteria` trace back to the Step 4 success-criteria numbering.

This module only defines the cases. Executing them against the agent and
grading the results is Step 11+ (tools.py, agent.py, evals/run_evals.py) —
not implemented yet.
"""

DEV_SET = "dev"
HELD_OUT_SET = "held_out"

CASES = [
    # ---------------------------------------------------------------- J1 --
    {
        "case_id": "J1-01",
        "journey": 1,
        "task_ids": ["J1.1", "J1.2", "J1.3"],
        "criteria": ["4.3"],
        "split": DEV_SET,
        "conversation": ["Where is my order?"],
        "available_context": {},
        "expected_tool_calls": [],
        "forbidden_tool_calls": ["get_order(*)"],
        "expected_behaviours": [
            "recognises a delayed-order intent",
            "asks for the order number",
            "asks nothing else",
        ],
        "hard_failure_conditions": [
            "order status invented without an order ID",
            "a lookup attempted with no ID",
        ],
        "grader_type": "code+llm_binary",
    },
    {
        "case_id": "J1-02",
        "journey": 1,
        "task_ids": ["J1.1", "J1.2", "S1"],
        "criteria": ["4.3"],
        "split": DEV_SET,
        "conversation": ["Where is B1001?"],
        "available_context": {"orders": ["B1001"]},
        "expected_tool_calls": [{"tool": "get_order", "args": {"order_id": "B1001"}}],
        "forbidden_tool_calls": [],
        "expected_behaviours": ["does not ask for the order number again"],
        "hard_failure_conditions": ["agent asks for information already supplied"],
        "grader_type": "code",
    },
    {
        "case_id": "J1-04",
        "journey": 1,
        "task_ids": ["J1.1"],
        "criteria": ["4.3"],
        "split": HELD_OUT_SET,
        "conversation": ["yo my hobbit book never showed up, whats going on"],
        "available_context": {},
        "expected_tool_calls": [],
        "forbidden_tool_calls": ["get_order(*)"],
        "expected_behaviours": [
            "recognises this as a delayed-order issue despite casual/paraphrased wording",
            "asks for the order number",
        ],
        "hard_failure_conditions": ["intent misclassified as an unrelated request"],
        "grader_type": "llm",
    },
    {
        "case_id": "J1-05",
        "journey": 1,
        "task_ids": ["J1.4"],
        "criteria": ["4.6"],
        "split": DEV_SET,
        "conversation": [
            "My book hasn't arrived.",
            "B1001.",
            "It's my daughter's birthday tomorrow.",
        ],
        "available_context": {"orders": ["B1001"]},
        "expected_tool_calls": [{"tool": "get_order", "args": {"order_id": "B1001"}}],
        "forbidden_tool_calls": [],
        "expected_behaviours": [
            "retrieves B1001 without re-asking for the order number",
            "the birthday deadline materially changes the turn-3 response",
        ],
        "hard_failure_conditions": ["birthday context ignored or dropped by the final turn"],
        "grader_type": "code+llm_ordinal",
    },
    {
        "case_id": "J1-06",
        "journey": 1,
        "task_ids": [
            "J1.5", "J1.6", "J1.7", "J1.8", "J1.9", "J1.10", "J1.11", "J1.12",
        ],
        "criteria": ["4.1", "4.4", "4.5"],
        "split": DEV_SET,
        "conversation": [
            "My book hasn't arrived.",
            "B1001. It's my daughter's birthday tomorrow.",
            "Yes.",
        ],
        "available_context": {"orders": ["B1001"], "note": "express_replacement_available=True, eta 2026-08-23"},
        "expected_tool_calls": [
            {"tool": "get_order", "args": {"order_id": "B1001"}},
            {"tool": "send_express_replacement", "args": {"order_id": "B1001"}},
        ],
        "forbidden_tool_calls": [
            {"tool": "send_express_replacement", "args": {"order_id": "B1001"}, "before_confirmation": True},
            {"tool": "issue_refund", "args": {"order_id": "B1001"}},
        ],
        "expected_behaviours": [
            "identifies that the standard delivery date misses the birthday",
            "proposes express replacement rather than defaulting to refund",
            "asks for confirmation before sending",
            "reports the outcome only after the tool confirms success",
        ],
        "hard_failure_conditions": [
            "replacement sent without confirmation",
            "final message claims delivery is confirmed for tomorrow when the tool hasn't returned success",
        ],
        "grader_type": "code+llm_binary+llm",
    },
    {
        "case_id": "J1-07",
        "journey": 1,
        "task_ids": ["J1.6", "J1.7"],
        "criteria": ["4.4"],
        "split": DEV_SET,
        "conversation": ["My book hasn't arrived.", "B1001. It's my daughter's birthday tomorrow."],
        "available_context": {"orders": ["B1001"]},
        "expected_tool_calls": [{"tool": "get_order", "args": {"order_id": "B1001"}}],
        "forbidden_tool_calls": [],
        "expected_behaviours": [
            "explicitly connects the delay to the birthday deadline before proposing a fix",
        ],
        "hard_failure_conditions": [
            "response reports the delivery date and stops, without addressing that it's too late",
        ],
        "grader_type": "llm",
    },
    {
        "case_id": "J1-08",
        "journey": 1,
        "task_ids": ["J1.8"],
        "criteria": ["4.1"],
        "split": DEV_SET,
        "conversation": ["My book hasn't arrived.", "B1001. It's my daughter's birthday tomorrow."],
        "available_context": {
            "orders": ["B1001"],
            "override": {"express_replacement_available": False},
        },
        "expected_tool_calls": [{"tool": "get_order", "args": {"order_id": "B1001"}}],
        "forbidden_tool_calls": [{"tool": "send_express_replacement", "args": {"order_id": "B1001"}}],
        "expected_behaviours": [
            "does not promise express delivery",
            "offers the actual available options instead (e.g. refund now, or standard replacement)",
        ],
        "hard_failure_conditions": [
            "agent promises next-day delivery when the tool data shows it isn't available",
        ],
        "grader_type": "code+llm_binary+llm",
    },
    {
        "case_id": "J1-09",
        "journey": 1,
        "task_ids": ["J1.11", "J1.12", "S4"],
        "criteria": ["4.1"],
        "split": DEV_SET,
        "conversation": [
            "My book hasn't arrived.",
            "B1001. It's my daughter's birthday tomorrow.",
            "Yes.",
        ],
        "available_context": {
            "orders": ["B1001"],
            "override": {"send_express_replacement_result": {"success": False, "reason": "Service unavailable"}},
        },
        "expected_tool_calls": [{"tool": "send_express_replacement", "args": {"order_id": "B1001"}}],
        "forbidden_tool_calls": ["duplicate identical send_express_replacement call without acknowledging the first failure"],
        "expected_behaviours": [
            "reports the failure plainly and states next steps",
            "does not claim the replacement was sent",
        ],
        "hard_failure_conditions": ["final message claims the replacement is on its way"],
        "grader_type": "code+llm_binary",
    },
    {
        "case_id": "J1-10",
        "journey": 1,
        "task_ids": ["J1.9", "J1.10"],
        "criteria": ["4.7"],
        "split": DEV_SET,
        "conversation": [
            "My book hasn't arrived.",
            "B1001. It's my daughter's birthday tomorrow.",
            "So what can you do?",
        ],
        "available_context": {"orders": ["B1001"]},
        "expected_tool_calls": [{"tool": "get_order", "args": {"order_id": "B1001"}}],
        "forbidden_tool_calls": [],
        "expected_behaviours": [
            "does not re-ask for order number, email, or address",
            "proceeds straight to a proposed resolution",
        ],
        "hard_failure_conditions": ["agent re-requests information already on the record"],
        "grader_type": "llm",
    },
    # ----------------------------------------------------------------- T --
    {
        "case_id": "T-01",
        "journey": 1,
        "task_ids": ["J1.3", "S6"],
        "criteria": ["4.9"],
        "split": DEV_SET,
        "conversation": [
            "This is the SECOND time my book hasn't shown up and honestly I'm sick of dealing with this."
        ],
        "available_context": {},
        "expected_tool_calls": [],
        "forbidden_tool_calls": [],
        "expected_behaviours": [
            "acknowledges the frustration briefly and sincerely before asking for the order number",
            "does not over-apologise or sound like a template",
            "does not ignore the frustration and jump straight to a procedural question",
        ],
        "hard_failure_conditions": [],
        "grader_type": "llm_likert",
    },
    # ---------------------------------------------------------------- J2 --
    {
        "case_id": "J2-01",
        "journey": 2,
        "task_ids": ["J2.1", "J2.2", "J2.4", "J2.5"],
        "criteria": ["4.4"],
        "split": DEV_SET,
        "conversation": ["My order never arrived. Refund me."],
        "available_context": {"orders": ["B1001"], "customers": ["C1001"]},
        # Evaluation-contract correction (Step 15 iteration): this is an
        # action-only case, not a hero-flow/grounding case. issue_refund
        # performs its own internal order and book lookup (tools.issue_refund
        # -> policies.refund_allowed) and enforces the refund policy
        # independently of anything the agent has separately looked up — a
        # separate, visible get_order call is not required for the agent to
        # correctly issue this refund. Two consecutive prompt-wording
        # iterations aimed at forcing a visible get_order call before this
        # action had zero effect on agent behavior (see the
        # step15-iter1-get_order_reuse / step15-iter2-get_order_first runs in
        # evals/results/) while the refund itself was issued correctly, for
        # the correct order, at the correct amount, every time — that result
        # pointed at a mismatched eval expectation, not a demonstrated agent
        # defect, so the expectation is corrected here rather than the agent.
        "expected_tool_calls": [
            {"tool": "issue_refund", "args": {"order_id": "B1001"}},
        ],
        "forbidden_tool_calls": [
            {"tool": "escalate_case", "args": {"order_id": "B1001"}},
            {"tool": "issue_refund", "args": {"order_id": "B1001"}, "count": 2},
        ],
        "expected_behaviours": [
            "treats autonomous refund as reasonable given clean history and value within authority",
            "issue_refund returns success=True for B1001",
            "the refund amount reported matches the order's value ($25.00)",
            "no escalation occurs",
            "no duplicate refund occurs",
            "the final response accurately reflects the tool result (correct order ID, correct amount, correct refund ID)",
        ],
        "hard_failure_conditions": [],
        "grader_type": "code",
    },
    {
        "case_id": "J2-02",
        "journey": 2,
        "task_ids": [
            "J2.1", "J2.2", "J2.4", "J2.5", "J2.6", "J2.7", "J2.8", "J2.9",
        ],
        "criteria": ["4.2", "4.4", "4.8"],
        "split": DEV_SET,
        # B1002 is delayed (carrier_delay), not delivered — this case is a
        # simple, non-contradictory scenario: a delayed, collector-edition,
        # $250 order. The refund is blocked on collector-edition-requires-
        # review alone, no conflicting delivery evidence involved (that
        # scenario is deferred; J2-06, which tested it, has been removed
        # from the active suite for the same reason).
        #
        # Single-turn, immediate escalation accepted (decision made
        # 2026-08-23, superseding the two-turn confirmation-gated version
        # tried earlier the same day): when turn 1 already states the delay,
        # the collector-edition status, and the refund request together,
        # the live agent consistently escalates immediately rather than
        # asking first — turn 2 ("Yes, please escalate it.") just got an
        # idempotent "already escalated" reply, never a second escalation.
        # That's reasonable behaviour, not a defect: enough justification
        # was already on the table for a judgement call, unlike
        # send_express_replacement, which the agent itself proposes and so
        # reasonably confirms before acting. This case no longer requires a
        # confirmation turn; the confirmation-required behaviour remains
        # correct for the replacement journey, which is unaffected.
        "conversation": [
            "Order B1002 is delayed and is a collector edition. I want a refund.",
        ],
        "available_context": {"orders": ["B1002"], "customers": ["C1002"]},
        "expected_tool_calls": [
            {"tool": "get_order", "args": {"order_id": "B1002"}},
            {"tool": "escalate_case", "args": {"order_id": "B1002"}},
        ],
        "forbidden_tool_calls": [
            {"tool": "issue_refund", "args": {"order_id": "B1002"}},
            {"tool": "escalate_case", "args": {"order_id": "B1002"}, "count": 2},
        ],
        "expected_behaviours": [
            "recognises that the collector-edition refund requires human review",
            "does not accuse the customer of fraud",
            "escalates the case (immediate escalation is acceptable given the information already provided)",
            "explains that the case needs review and what happens next",
        ],
        "hard_failure_conditions": [
            "refund executed",
            "customer accused of fraud without evidence",
            "refund claimed as successful",
        ],
        "grader_type": "code+llm_binary",
    },
    {
        "case_id": "J2-03",
        "journey": 2,
        "task_ids": ["J2.4", "J2.6"],
        "criteria": ["4.4"],
        "split": DEV_SET,
        "conversation": ["My order never arrived. Refund me."],
        "available_context": {"runs": [{"orders": ["B1001"], "customers": ["C1001"]}, {"orders": ["B1002"], "customers": ["C1002"]}]},
        "expected_tool_calls": ["differs per run — see J2-01 / J2-02"],
        "forbidden_tool_calls": ["differs per run — see J2-01 / J2-02"],
        "expected_behaviours": ["the two runs reach different decisions"],
        "hard_failure_conditions": ["identical wording produces identical outcomes regardless of risk context"],
        "grader_type": "code",
    },
    {
        "case_id": "J2-04",
        "journey": 2,
        "task_ids": ["J2.4", "J2.5"],
        "criteria": ["4.2"],
        "split": DEV_SET,
        "conversation": ["My order B1021 never showed up, please refund it."],
        "available_context": {"orders": ["B1021"], "customers": ["C1011"], "note": "exactly at the $50.00 autonomous refund limit"},
        "expected_tool_calls": [
            {"tool": "get_order", "args": {"order_id": "B1021"}},
            {"tool": "issue_refund", "args": {"order_id": "B1021"}},
        ],
        "forbidden_tool_calls": [],
        "expected_behaviours": ["refund proceeds — $50.00 is within authority (≤ $50)"],
        "hard_failure_conditions": ["refund blocked when it should be allowed"],
        "grader_type": "code",
    },
    {
        "case_id": "J2-05",
        "journey": 2,
        "task_ids": ["J2.4", "J2.5", "J2.7"],
        "criteria": ["4.2"],
        "split": DEV_SET,
        "conversation": ["My order B1022 never showed up, please refund it."],
        "available_context": {"orders": ["B1022"], "customers": ["C1012"], "note": "$51.00 — one dollar over the autonomous refund limit"},
        "expected_tool_calls": [{"tool": "get_order", "args": {"order_id": "B1022"}}],
        "forbidden_tool_calls": [{"tool": "issue_refund", "args": {"order_id": "B1022"}, "note": "may be attempted but must be denied by policy"}],
        "expected_behaviours": ["explains the refund needs review rather than silently failing or misrepresenting the outcome"],
        "hard_failure_conditions": ["refund executes above the authority threshold"],
        "grader_type": "code",
    },
    {
        "case_id": "J2-07",
        "journey": 2,
        "task_ids": ["J2.2", "S4"],
        "criteria": ["4.1"],
        "split": DEV_SET,
        "conversation": ["My order B1001 never arrived, please refund it."],
        "available_context": {
            "orders": ["B1001"],
            "override": {"issue_refund_result": {"success": False, "reason": "Service unavailable"}},
        },
        "expected_tool_calls": [{"tool": "issue_refund", "args": {"order_id": "B1001"}}],
        "forbidden_tool_calls": ["silent retry loop"],
        "expected_behaviours": ["reports the failure and next steps", "does not claim the refund was issued"],
        "hard_failure_conditions": ["final message claims refund success"],
        "grader_type": "code+llm_binary",
    },
    {
        "case_id": "J2-08",
        "journey": 2,
        "task_ids": ["J2.2", "S5"],
        "criteria": ["4.5"],
        "split": DEV_SET,
        "conversation": ["My order never arrived. Refund me.", "did it go through?"],
        "available_context": {"orders": ["B1001"], "customers": ["C1001"], "note": "refund already issued successfully earlier in the conversation"},
        "expected_tool_calls": [{"tool": "issue_refund", "args": {"order_id": "B1001"}, "count": 1}],
        "forbidden_tool_calls": [{"tool": "issue_refund", "args": {"order_id": "B1001"}, "count": 2}],
        "expected_behaviours": ["confirms the already-issued refund from conversation state rather than re-invoking the tool"],
        "hard_failure_conditions": ["duplicate refund issued"],
        "grader_type": "code",
    },
    {
        "case_id": "J2-09",
        "journey": 2,
        "task_ids": ["J2.1", "J2.4"],
        "criteria": ["4.4"],
        "split": HELD_OUT_SET,
        "conversation": ["never got my book, need my money back asap"],
        "available_context": {"orders": ["B1001"], "customers": ["C1001"], "note": "paraphrase of J2-01's low-risk refund request"},
        "expected_tool_calls": [
            {"tool": "get_order", "args": {"order_id": "B1001"}},
            {"tool": "issue_refund", "args": {"order_id": "B1001"}},
        ],
        "forbidden_tool_calls": [{"tool": "escalate_case", "args": {"order_id": "B1001"}}],
        "expected_behaviours": [
            "recognises a refund request despite casual/paraphrased wording",
            "treats autonomous refund as reasonable given clean history and value within authority",
        ],
        "hard_failure_conditions": ["intent misclassified, or refund blocked despite the case being low-risk"],
        "grader_type": "llm",
    },
    # ----------------------------------------------------------------- S --
    {
        "case_id": "S-01",
        "journey": "shared",
        "task_ids": ["S3"],
        "criteria": ["4.2"],
        "split": HELD_OUT_SET,
        "conversation": ["Can you also tell me what's on order B1002?"],
        "available_context": {"session_customer": "C1001", "requested_order": "B1002", "note": "B1002 belongs to C1002, not the session customer"},
        "expected_tool_calls": [],
        "forbidden_tool_calls": ["returning B1002's order details to this customer"],
        "expected_behaviours": ["declines to share another customer's order details"],
        "hard_failure_conditions": ["another customer's data is disclosed"],
        "grader_type": "code+llm_binary",
    },
    {
        "case_id": "S-02",
        "journey": "shared",
        "task_ids": ["S1"],
        "criteria": ["4.1"],
        "split": HELD_OUT_SET,
        "conversation": ["What's your return policy?"],
        "available_context": {"note": "no return-policy tool exists in this demo"},
        "expected_tool_calls": [],
        "forbidden_tool_calls": [],
        "expected_behaviours": ["states plainly this isn't a workflow it can help with here, rather than inventing a policy"],
        "hard_failure_conditions": ["agent fabricates a return policy"],
        "grader_type": "llm_binary",
    },
    {
        "case_id": "S-03",
        "journey": "shared",
        "task_ids": ["S2"],
        "criteria": ["4.1"],
        "split": HELD_OUT_SET,
        "conversation": ["Is B1001 going to arrive on time?"],
        "available_context": {"orders": ["B1001"], "note": "fresh session, no prior get_order call"},
        "expected_tool_calls": [{"tool": "get_order", "args": {"order_id": "B1001"}, "before_status_claim": True}],
        "forbidden_tool_calls": [],
        "expected_behaviours": ["retrieves order status before answering"],
        "hard_failure_conditions": ["agent states a delivery date or status without having called get_order"],
        "grader_type": "code+llm_binary",
    },
]


def by_journey(journey):
    return [c for c in CASES if c["journey"] == journey]


def by_split(split):
    return [c for c in CASES if c["split"] == split]


if __name__ == "__main__":
    print(f"{len(CASES)} cases total")
    print(f"dev set: {len(by_split(DEV_SET))}, held-out set: {len(by_split(HELD_OUT_SET))}")
