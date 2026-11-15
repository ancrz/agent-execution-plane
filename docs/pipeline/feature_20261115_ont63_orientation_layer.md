# Feature: Capa de orientación básica, primitivas MVP antes de la suite AEP (ONT-63)

- **Documento**: `feature_20261115_ont63_orientation_layer.md`
- **Anterior en la cadena**: [`feature_20261115_ont62_health_and_update.md`](feature_20261115_ont62_health_and_update.md)
- **Intent**: dar a los agentes, al llegar a un host, respuestas básicas en RAM (dónde estoy, qué recursos hay, qué herramientas tengo, qué es este repo, qué es este archivo o proceso) antes de usar la suite completa de AEP, preparando el camino hacia ella. Origen: el usuario, 2026-11-15: "si la idea es cubrir lo que un agente quiere descubrir como mvp basico de forma general ... antes de usar la suite de AEP, usar lo basico antes de proceder o que prepare el camino de AEP"; después: "las de red ya estaban incluidas en unas de las tools, comprimidas como sub tools esas también se toman en cuenta. después de lo básico sí se pueden crear artefactos en memoria para resolver problemas complejos limitadas por una shell."
- **Pipeline mode**: **Short** (plan inline del orquestador; Archon y Ontos descartados). Plan y revisión 1: `/tmp/claude-1000/-home-ancruz-Documents-workspaces-agent-execution-plane/35ca3808-1a4d-4b75-ac5d-4ce0a6c2d86b/scratchpad/plan_ont63.md`.
- **Stage**: Graphos G2 tras **tres ciclos** Pragma→Dokimos. Veredicto final: `VERIFIED` (ciclo 3). Ciclo 1: `DEFECTIVE (LOGIC_ERROR)`. Ciclo 2: `DEFECTIVE (seguridad media, D3)`.
- **Base**: `dev` `df039ee`. Worktree `/home/ancruz/Documents/workspaces/agent-execution-plane/.claude/worktrees/agent-a66c3a57c6b314ef0`, rama `worktree-agent-a66c3a57c6b314ef0`, HEAD `98efe5b` (8 commits sobre la base).
- **Publicación**: **publicado en `dev`** por Hermon (fast-forward sobre `df039ee`, push a `origin/dev` autorizado por el usuario). Graphos no comprometió ni empujó nada; `main` no se tocó.

## Commits (`git log --oneline df039ee..HEAD`, creados por Pragma y el orquestador)

| Commit | Grupo | Contenido |
|---|---|---|
| `374f83d` | (a) | `host-info`, `cpu-load`, `toolchain-probe` (L0) |
| `506ec55` | (b) | `workspace-probe`, `file-fingerprint`, `dir-usage` (L0) |
| `678f07e` | (c) | `path-users`; `process_inspect(pid>0, verbosity="detail")`; `aep_ctl network probe` con puerto explícito, DNS y `error_class` |
| `c6fb6d6` | (d) | `orient` compuesto; escalera L0→L1→L2 (`escalate`); WF-0 "Orient first"; enrutado de `discover`; paso 0 en instrucciones |
| `5dc7426` | ciclo 1 D1 | enmascaramiento de credenciales en `cmdline` antes del truncado |
| `f1246a3` | ciclo 1 D2 | `engine/intent_router.py` `route_basic_intent`: pre-enrutado léxico determinista EN+ES con pliegue NFKD |
| `8b99039` | ciclo 2 R1–R5 | WF-0 en instrucciones (9353 B); `aep_python` en `host-info`; límite de 1024 B en `network probe args`; lista negra de `~/.aws`, `~/.config/gcloud`, `~/.kube`, `~/.docker/config.json`; `dir-usage` con `skipped_protected` |
| `98efe5b` | ciclo 2 D3 | `CapabilityGuard.protected_roots()` en forma léxica y resuelta; usado por `is_path_blacklisted`, por los vetos del sandbox y por `primitives_orient` |

## Resolution path y blast radius (P1)

- **Camino elegido**: estándar en Short, sin herramienta nueva. Primitivas de solo lectura en Python puro; sub-tools de `aep_ctl` y `process_inspect` extendidas en lugar de duplicarlas (regla NO DUPLICAR). Net-reach y proc-detail descartados como primitivas por esa regla.
- **Escalera de resolución** documentada en el playbook WF-0 y en la sección nueva del README: L0 primitivas en RAM → L1 sub-tools tipadas y `sandbox_run` → L2 artefactos en memoria (`artifact_lint_and_build` + `artifact_execute_in_ram`) para syscalls, parseo masivo, concurrencia, muestreo temporal o estado entre pasos.
- **Blast radius medido** (`git diff --stat df039ee..HEAD`, 15 archivos, +2355 / −101):
  - Código nuevo: `engine/primitives_orient.py` (+1186), `engine/intent_router.py` (+117).
  - Código modificado: `engine/primitives.py` (78), `engine/privilege.py` (136), `server.py` (99), `engine/net_telemetry.py` (48).
  - Tests nuevos: `tests/test_ont63_*.py` (cinco archivos y `test_ont63_cycle2.py`, `test_ont63_symlinked_roots.py`).
  - Tests existentes modificados: `tests/test_default_primitives.py` (17 líneas) y `tests/test_d11_dynamic_counts.py` (2 líneas, conteo).
- **Alcance de `engine/net_telemetry.py`** (resuelto por el orquestador): extensión de `aep_ctl network probe` del grupo (c) (DNS y `parse_probe_ports`), dentro del alcance. Tampoco `engine/telemetry.py` cambió, así que no hay estados nuevos que clasificar.
- **Cambios en tests existentes** (resuelto por el orquestador): `tests/test_default_primitives.py` y `tests/test_d11_dynamic_counts.py` solo actualizan conteos (5 a 13) y la lista WF-0..WF-11; los legacy siguen comprobando `PERMISSION_DENIED` a `4r--`. No se relajó ninguna aserción.

## Tool reach y herencia

- Primitivas `4r--`: `host-info`, `cpu-load`, `toolchain-probe`, `workspace-probe`, `file-fingerprint`, `dir-usage`, `orient`. Primitiva `5r-x`: `path-users`. `process_inspect` detallado: por debajo de 7rwx solo procesos del propio uid; `cwd` y `env_names` ocultos para otros uid.
- Ninguna primitiva escribe en disco ni usa `shell=True`; subprocesos con timeout y entorno mínimo; `toolchain-probe` no ejecuta `sudo`; `git` con `GIT_OPTIONAL_LOCKS=0`.
- Rutas vetadas: `file-fingerprint` y `dir-usage` rechazan con `PARAM_ERROR` por ruta, sin metadatos. El veto compara la forma léxica y la resuelta de cada entrada (ciclo 3).
- La DB real no se toca desde las pruebas (`AEP_DATA_HOME` temporal).

## Veredictos por ciclo

| Ciclo | Veredicto | Hallazgos | Corrección |
|---|---|---|---|
| 1 | `DEFECTIVE (LOGIC_ERROR)`, 1572 passed | D1 (seguridad, alta): `cmdline` sin enmascarar `--token VALOR`, `--api-key VALOR`, `-p VALOR`, `Authorization: Bearer VALOR`, `https://user:VALOR@host`. D2 (media): frases naturales EN/ES no enrutaban (similitud semántica < 0.12); el solapamiento no plegaba acentos | `5dc7426` (D1), `f1246a3` (D2). Ciclo 2 además recibió R1–R5 aceptadas por el orquestador (`8b99039`) |
| 2 | `DEFECTIVE (seguridad media)`, 1630 passed | D3: `~/.docker` es symlink a `/mnt/apps/docker-desktop-data`; `is_path_blacklisted` resolvía el candidato pero comparaba contra `Path.home()/rel` sin resolver, así que `~/.docker/config.json` no quedaba vetado (`fingerprint` devolvía sha256). Mismo patrón en tres sitios | `98efe5b`: lista única `CapabilityGuard.protected_roots()` en forma léxica y resuelta |
| 3 | `VERIFIED`, 1637 passed, 0 failed | Verificación de la corrección: DB real con md5 y mtime sin cambio; D3 rechazado por symlink, por ruta real y por symlink externo; sandbox con Go sigue montando solo `/mnt/apps/tools/go`; `orient` 1297 B en 0.11 s; `aep-ctl` intacto | Ninguna |

Observaciones no bloqueantes del ciclo 3:
- `aep_python.path` recorta "Documents" a "…cuments" (recorte por caracteres, no por límite de directorio). Cosmético; pendiente.
- `-p` siempre se enmascara (también `mkdir -p dir`). Fail-safe aceptado por el orquestador.

## State evolution

```mermaid
flowchart LR
    A["A: plan inline ONT-63 (base dev df039ee)"] --> A1["A.1: revisión 1, NO DUPLICAR, net-reach y proc-detail descartados"]
    A1 --> P1["Pragma (a) a (d): 374f83d a c6fb6d6"]
    P1 --> C1["Ciclo 1 DEFECTIVE LOGIC_ERROR: D1 cmdline, D2 lenguaje natural"]
    C1 --> P2["Pragma: 5dc7426, f1246a3, 8b99039"]
    P2 --> C2["Ciclo 2 DEFECTIVE seguridad: D3 symlink ~/.docker"]
    C2 --> P3["Pragma: 98efe5b (protected_roots)"]
    P3 --> C3["Ciclo 3 VERIFIED 1637 passed"]
    C3 --> G2["Graphos G2: este documento y docs"]
    G2 --> H["Hermon: publicado en dev (ff sobre df039ee)"]
```

## Lecciones

1. Las pruebas con frases que contienen la palabra clave ocultan fallos de enrutado. Probar con frases naturales en EN y ES.
2. Las listas de vetos deben compararse en forma léxica y resuelta y construirse en un único sitio. Repetir la lista en tres lugares produjo el mismo fallo tres veces.
3. Los tests sin symlinks no reflejan hosts reales: Docker Desktop enlaza `~/.docker`.

## Pendientes y ruteo

- **Hermon** (hecho): commit de docs y fast-forward de `dev` a los ocho commits de Pragma, push a `origin/dev`. `main` no se tocó.
- **Pragma (opcional, cosmético)**: `aep_python.path` debe recortar por límite de directorio.
- **Rollup**: ONT-65 es el quinto documento de la cadena (ONT-61 a ONT-65).

Ruteo: Graphos devuelve al orquestador, que decide el siguiente paso. Pipeline completo: Hermon publicó en `dev`; queda solo el cosmético opcional de `aep_python.path`.
