"""Drift handling. Owner: MEMORY.

When a system answers in a shape we do not understand:
  1. Summarize the failure (system, endpoint, what we expected, what we got).
  2. recall() similar incidents.
  3. Ask the LLM for a proposed mapping, giving it the failure and the recalled fixes.
  4. Write a proposal document and STOP until a human approves it in the UI.
  5. On approval, store it as an `approved_rule` memory and apply it to the rest of the run.

An approved rule is applied without asking again. That is the proof memory changed behaviour:
the second shipment that hits the same drift does not fail first.
"""


def propose_fix(failure: dict) -> dict:
    raise NotImplementedError


def apply_rule(rule: dict, raw_response: dict) -> dict:
    """Translate a response using an approved rule. Must be deterministic, no LLM call here."""
    raise NotImplementedError
