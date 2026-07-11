# Preserved Failure Analysis

## SMD-Bench-1400

The main benchmark achieved 0.941429 end-to-end policy conformance and 0.996429 controller-only conformance. Seventy-two expected external delegations were handled locally. These disagreements remain visible rather than being relabeled to match the controller.

Evidence detection achieved macro F1 0.935488. The weakest main-set evidence class was `internal_infrastructure`, where broad contextual patterns produced false positives. This demonstrates why detector performance must be separated from controller-only evaluation.

Rule-based utility-label agreement was 0.915. Weight sensitivity changed route conformance from 0.744286 to 0.990714. By construction, the sensitivity analysis re-scores only routes already admitted by hard policy; it therefore evaluates operational preference sensitivity, not the security boundary itself.

## SMD-Challenge-210

The post-freeze challenge achieved 0.876190 end-to-end policy conformance and 0.914286 controller-only conformance. It produced no security-relevant target-policy violation and no automatic direct, canonicalized, or structural leakage. Eighteen cases were overblocked.

The challenge detector macro F1 was 0.867244. `proprietary_code` recall was zero in its unseen phrasing, and `internal_infrastructure` F1 was 0.363636. These failures were discovered after the controller freeze and have not been used to tune the controller.

The challenge provides a less optimistic post-freeze stress signal than the authored main-template score because its lower performance and class-specific failures are preserved. It is not independent external validation, and its human review remains pending.

## SMD-Egress-Challenge-36

The targeted egress set achieved 0.666667 end-to-end policy conformance. It exposed eight security-relevant target-policy violations and eight direct findings. All eight came from approved or high-risk external cases whose authored `business_sensitive` evidence was not detected.

Known-class controller-only conformance remained 1.0 on 18 evaluable cases. This does not rescue the end-to-end result. It demonstrates the boundary of the formal claim: hard-policy arbitration can constrain only the evidence supplied to it. The controller and policy remain frozen, and these failures define future semantic-evidence work.
