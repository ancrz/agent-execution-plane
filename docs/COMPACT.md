# Instrucción de Compactación — AEP (qué preservar / qué descartar)

Guía harness-neutral para compactar la conversación sin perder el hilo.

## PRESERVAR (imprescindible)
1. **Identidad:** AEP = runtime FastMCP (stdio) *agents-for-agents* sobre Ubuntu. Entregar artefacto,
   expandir eficiencia agéntica sin fricción de consola; transparente al usuario.
2. **Motores:** `engine/ponder.py` (CONFIANZA, multidimensional+veto) y `engine/matcher.py` (RELEVANCIA, BM25F).
3. **Flujo:** `discover(use_case, action)` → process_inspect → reutilizar/sintetizar/despachar/forense/automatizar → gestionar/ponderar (kanban_board).
4. **Invariantes:** memoria auto-indexada; telemetría cerrada; promoción↔degradación; kanban_board reversible;
   GC seguro (protect plantillas, cold-aging immunity); atajo 1-paso síntesis en RAM; auto-canary en RAM;
   desacoplamiento Playwright (`ThreadPoolExecutor`); enmascaramiento de secretos en salidas/Pueue (`engine/security.py`);
   fail-soft; stdio; hot-reload Connect/JSON-RPC (Antigravity/Codex; Claude opt-in);
   aislamiento subprocess/FD (`pass_fds=(fd,)`, `timeout=30`, daemons detached con `DEVNULL` stdio, y `_safe_run` con `close_fds=True`, `timeout=15`);
   15 herramientas activas / 16 capacidades 100% mapeadas (1:1 parity).
5. **Estado Actual:** 15 tools MCP; 16 capacidades; rama `main`; Semgrep 0; Tarea 110 PROMOTED (0.9958 TRUST).
   Milestone ONT-09 (Memory-Mapped Hybrid SQLite Optimization: PRAGMA mmap_size 256MB & 64MB Cache) VERIFICADO por Dokimos.
   Documento Pipeline G2: `docs/pipeline/feature_20261024_115500_mmap_hybrid_sqlite_ram_persistence.md`.
6. **Pendientes Inmediatos:** Hermon (Stage 6) Release Engine & Commits Atómicos (`perf(db)` y `docs(state)`).
7. **Decisiones firmes:** factoría centralizada `engine/db.py`; 256MB mmap zero-copy; 64MB cache RAM; WAL mode para concurrencia multiagente; no-recursión en playbook_run; enmascaramiento de tokens en todo canal.
8. **Fuentes:** `docs/STATE.md`, `docs/MILESTONES.md`, este archivo, y la memoria `aep-state-and-pendings`.

## DESCARTAR (ruido de proceso)
- Salidas largas de probes/semgrep/compilaciones ya resueltas (basta el veredicto).
- Diffs completos y hashes de commit intermedios (`git log` los tiene).
- Warnings de entorno repetidos (Node CVE, HF token, avisos del embedder).
- Iteraciones de depuración superadas; detalles de llamadas MCP individuales.

## Regla
Conserva **decisiones, invariantes y pendientes con su porqué**; descarta la **evidencia de ejecución**
una vez que el veredicto quedó registrado. Ante la duda, preserva el *porqué*, no el *cómo*.

---

### Foco listo para pegar en `/compact`
```
/compact Conserva estado AEP: premisa agents-for-agents (entregar artefacto, IA expande
eficiencia), 2 motores (ponder.py=confianza, matcher.py=relevancia), flujo discover→process_inspect→
reutilizar/sintetizar/despachar/forense/automatizar→kanban_board→ponderar, invariantes (auto-index,
telemetría, promoción↔degradación, kanban_board reversible, GC seguro con cold-aging immunity,
auto-canary en RAM, atajo 1-paso síntesis, blindaje subprocess/FD pass_fds+DEVNULL daemons+timeout 15s,
enmascaramiento secretos engine/security.py, Playwright ThreadPoolExecutor, fail-soft, stdio, hot-reload,
Claude opt-in), 15 tools (16 capacidades 1:1), en main (Semgrep 0), Tarea 110 PROMOTED (0.9958 TRUST).
Activo: Milestone ONT-09 SQLite Hybrid mmap 256MB / 64MB Cache VERIFICADO (Dokimos Gates 1-5, Graphos G2 listo para Hermon Stage 6).
Fuentes: docs/pipeline/feature_20261024_115500_mmap_hybrid_sqlite_ram_persistence.md, docs/STATE.md, docs/COMPACT.md.
```
