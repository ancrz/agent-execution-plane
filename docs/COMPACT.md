# Context Compaction Guidance — AEP (Milestone ONT-29)

**Preserve**:
- Pipeline Mode: Full Pipeline (Stage 2 Graphos G2 Record Complete -> Hand-off to Hermon Stage 6).
- Active Milestone: ONT-29 ("AEP External Consumption Gaps Remediation & Chrysalis Bridge Stabilization") — VERIFIED & PROMOTED ✅ (8/8 Gates Passed, 37/37 pytest tests, 0 ruff errors).
- Gaps Remediated: GAP-OM-19 (single encoding), GAP-OM-16 (brief/terse deduplication), GAP-OM-17 (Bernstein hazard & co-dep), GAP-CP-04 (workspace snapshot/restore), GAP-OM-18 (audit usage), GAP-DX-04 (sandbox test parsing), GAP-DOC-02 (caching discovery).
- Key Invariants Preserved: Exactly 15 FastMCP tools, output_bytes(brief) < output_bytes(summary), tuple return contract in Topos, zero FD leaks.
- Next Actions: (1) Hermon Stage 6 release commit & push; (2) Synchronize external consumers (chrysalis-bridge).

**Drop**:
- Verbose test dumps, intermediate stdout/stderr, and superseded planning discussions.
