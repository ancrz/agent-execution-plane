# Context Compaction Guidance: AEP (ONT-42b B1–B9 VERIFIED + `autonomous_session_steward` CERTIFIED; ONT-42c pendiente; sin push)
**Preservar:**
- **Modo y baseline:** Full (ONT-42b) + Short (`autonomous_session_steward`). `dev` sincronizado localmente con B1–B9 VERIFIED y `D-01b` cerrado (`0 xfailed`). 17 tools, 19 capacidades.
- **Hechos cerrados:**
  - **Autogestión Autónoma de Sesión (`autonomous_session_steward`)**: `aep_ctl(domain="ipc", action="harness_reconnect")` estandarizada para `claude`, `agy`, `codex` y `gemini`, con autocertificación `mode="certify"` (`certify_loopback("hello world")` verificada en vivo sobre `/dev/pts/3`, SHA-256 `b94d27b9...`, `certified=True`, `audit_degraded=False`).
  - **ONT-42b G1–G4 + B9 Dogfood (`ACCEPT`)**: G1 (`run_tests_batched` síncrono $\le 20$ por lote en `sandbox_run`), G2 (herencia de hasta 10 `pins` de callers públicos para helpers privados), G3 (fixtures sintéticos en `test_ont42_gap_priority.py` y `test_ont42_spec_change.py`), G4 (`_reap_orphan_cycles` limpió `72871021d7de`). B9 cerró `D-01b` (`_TOOL_ACTIONS`) con `verdict="ACCEPT"` en ciclo `d6aabe764afd` (`fixed=1`, `gaps: 98->97`, `pins=10`, `batches=2`).
- **Decisiones del usuario:** push de `dev` solo con autorización explícita. R7 (tier de push en ONT-42c) y ONT-42d (acuerdo previo vs confirmación por llamada en `harness_reconnect`) pendientes de decisión si se abordan.
- **Fuentes:** `docs/pipeline/feature_20261106_182001_ont42_judge_evolve.md` §14; `docs/sdd/sdd_ont42a_harness_reconnect.md` §5.
**Pendiente (próximas 2):**
1. ONT-42c (C1–C7): máquina de estados `evolve`, `GitPort`, gate final con `run_tests_batched`, ledger e idempotencia, rollback `git revert` y Merkle `R_before`/`R_after`.
2. Autorización del usuario antes de cualquier `git push` de `dev`.
**Descartar:** logs de pytest, trazas de subagentes, ciclos huérfanos ya cosechados (`72871021d7de`, `01a97f09e77b`).

