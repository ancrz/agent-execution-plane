# Instalación en sala limpia (re-test) — dev @aa468e1

Veredicto: **DEGRADACIÓN CONTROLADA** (instala con integridad verificada; 3 BUGs menores restantes, 0 bloqueantes).

Método: `git bundle` de dev; Docker ubuntu:26.04; usuario `tester` no root, sin sudo; solo git/curl/ca-certificates. x86_64 + arm64 (emulado, `--platform linux/arm64`).

## Resultados
| Paso | x86_64 | arm64 |
|---|---|---|
| `--predict` | tier 6rw-, exit 0 | — |
| 1ª instalación | exit 0, 36 s, banner «CON ADVERTENCIAS» | exit 0, 2m37 s, uv/Go 1.26.10/golangci/pueue linux-arm64 instalados |
| `--check` | HEALTHY (exit 0); WARN: bwrap ausente, 0 clientes MCP | HEALTHY, mismos WARN |
| 2ª instalación | exit 0, 2.8 s, sin re-descargas, `.bashrc` inyectado 1 vez, git limpio | — |
| Integridad | 17 tools; DB integrity ok, 18 tablas (incl. `_aep_canary`); bins 755; DB 644 | — |
| pytest (login PATH) | 747 passed, 22 failed, 5 skipped | — |

Los 7 bugs previos quedan corregidos: canario sembrado, aep-ctl CLI funciona sin python3, Chromium sin libs → WARN/DISPLAY_UNAVAILABLE, curl -f, arch mapeada, banner distingue 0 clientes, uv.lock/`--frozen` usado.

## Comprobaciones pedidas
- (a) SHA-256: checksum alterado en copia del script → Go y pueue/pueued: «SHA-256 no coincide», descartado, no instalado, degrada con aviso; golangci-lint idem; uv: aborta (exit 1), sin `.venv` ni binarios. OK.
- (b) Go previo: con checksum de Go alterado y `~/.local/share/go` existente, el directorio se conserva (sustitución solo tras descarga+extracción válidas). OK.
- (c) arm64: pasada completa OK (qemu funciona en el host).

## Hallazgos
| # | Clase | Detalle |
|---|---|---|
| 1 | BUG | `scripts/aep-sync.sh:47`: `trap ... RETURN` dentro de `validate()` no se limpia; dispara al volver de otras funciones y, con `set -u`, `err_compile: unbound variable` (línea 287). aep-sync sale 1 aunque valida y registra; setup.sh imprime «el registro MCP falló» falsamente (toda instalación limpia acaba «CON ADVERTENCIAS»). Corregir: `trap - RETURN` al final, o limpiar sin trap. |
| 2 | BUG | `server.py:3890` `cmd=["python3", AEP_CTL,...]`: la tool MCP `aep_ctl` falla con `[Errno 2] 'python3'` sin python3 de sistema (corrección del bug previo incompleta: solo se arregló el script CLI). Usar `sys.executable` o ejecutar AEP_CTL directo. |
| 3 | BUG | Pin incompatible: golangci-lint v1.61.0 (build go1.23) con Go 1.26.10 falla en cualquier fuente que importe stdlib («internal/goarch ... unsupported version: 2»); con go.mod 1.26 aborta. Lint avanzado queda inoperante (advisory). Subir golangci-lint a una versión compilada con Go ≥1.26 y re-fijar hashes. |
| 4 | AMBIENTAL/menor | Mensaje de pueue en fallo de checksum dice «red o release no disponible» (engañoso, cosmético). DB 644 (legible por otros usuarios), observación. |
| 5 | PRERREQUISITO | bwrap ausente (requiere root/apt): 15 de 22 fallos pytest (sandbox_run → DEGRADED, ont39 drainage, etc.). |
| 6 | AMBIENTAL | pytest restantes: `query_system_docs` (sin man-db), `diagnose_system_crashes` (sin apport), pueue pagination (cola vacía), gate6 service SIMULATED (sin systemd), `storage mounts` (efecto del hallazgo 2). |
| 7 | HARNESS | Fallos iniciales de `go` no encontrado fueron de `docker exec` sin PATH de login; con `bash -lc` desaparecen. No es bug. |

Ruta de prueba: contenedores aep-cr/aep-t1/aep-t2/aep-arm, imágenes aep-clean:t/arm y bundle eliminados al terminar. Sin push; repo sin tocar salvo este informe.
