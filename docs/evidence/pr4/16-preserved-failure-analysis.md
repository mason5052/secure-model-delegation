# Preserved Failure Analysis

## Regression Transformation Failure

During final validation, legacy regression case `B025` initially produced one
direct and one canonicalized leakage finding. The source-code detector matched
only the JavaScript declaration prefix and left a following return statement in
the generalized payload.

Classification: transformation failure caused by an incomplete source-code
span. The benchmark label was not changed. The detector was updated to treat a
JavaScript declaration and its adjacent return statement as one code span, and
a dedicated regression test was added. After the implementation fix, `B025`
and the complete 63-case regression set produced zero automatic leakage
findings.

## Utility Disagreements

Six SMD-Bench cases remain disagreements between the runtime utility heuristic
and the independent utility oracle. All belong to one F4 internal service-mesh
template for the local target: the heuristic reports `sufficient`, while the
oracle reports `partial`.

Classification: utility mismatch. These labels were intentionally not changed
to match the controller output. They remain visible in
`10-utility-results.json` and reduce overall utility-oracle agreement to
0.995714.

## Pilot Findings

The pilot gate also exposed encoded-secret and injection coverage misses plus
false-positive evidence patterns. Those implementation defects were corrected
before full generation. No label was changed merely to obtain a passing route
result. The final 140-case pilot and 1,400-case benchmark pass the automated
schema, duplication, distribution, route, and leakage gates.
