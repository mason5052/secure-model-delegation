# SMD-Bench-1400 Human Review Instructions

This stratified sample contains 210 synthetic cases: 30 per family, 10 per target profile, and 15 each from development and holdout. Every semantic template is represented.

For each row, Mason should independently review the expected route, transformation, utility, and rationale. Set `review_status` to `approved`, `corrected`, or `rejected` only after a real human review. Automated or AI-assisted checks do not count as human approval.

Record corrections without changing labels merely to match controller output. If a label is corrected, document why the oracle policy or template interpretation required the change.
