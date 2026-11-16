# ONT-67 — Uso de RAM: optimizaciones medidas y aplicables (Short)
Usuario 2026-11-16: de un prompt de contexto (ADN/PIM), "que podemos aplicar realmente ... solo afectaria la forma en que usamos la memoria RAM, si es posible alguna optimizacion, entonces debemos aplicarla segun tu inferencia, y si implementa algo nuevo el instalador deberia tomarlo en cuenta en futuras fresh start. investiga primero como se hace en la industria y como es compatible."
Base dev 2317d8d. Solo dev.

## Medición del orquestador (host real, 2026-11-16)
- Backend vivo: VmRSS 306 128 kB (RssAnon 294 948, RssFile 11 180), 19 hilos. process_inspect(pid=0) reporta 31 596 kB → BUG de medición.
- Host: 30 GB, disponible 3,4 GB; swap 7,9/8 GB (96 %). THP=madvise; KSM run=1; vm.memfd_noexec=0; /dev/shm 51 MB usados (aep_pool 12 kB).
- server.py:2109 `os.memfd_create(name, 0)`: sin MFD_CLOEXEC, sin sellos, sin MFD_EXEC explícito. Python 3.14 no expone os.MFD_EXEC/MFD_NOEXEC_SEAL (sí MFD_ALLOW_SEALING).
- SQLite ya usa mmap_size 256 MB, cache_size -64000 (64 MB POR CONEXIÓN), temp_store MEMORY, WAL.
- Sin MALLOC_ARENA_MAX ni malloc_trim. Embedder fastembed se carga perezosamente y nunca se descarga.
- compression.zstd disponible en la stdlib (zstd 1.5.7).

## Industria (investigado)
- memfd: kernel ≥6.3 añade MFD_EXEC (0x10) / MFD_NOEXEC_SEAL (0x08) y vm.memfd_noexec (0 exec por defecto, 1 noexec por defecto, 2 rechaza memfd sin NOEXEC_SEAL; jerárquico por pidns) — docs.kernel.org/userspace-api/mfd_noexec.html. Patrón runc (CVE-2019-5736): memfd sellado (F_SEAL_WRITE|SHRINK|GROW|SEAL) antes de ejecutar.
- glibc: MALLOC_ARENA_MAX=2 recomendado (Heroku) pero resultados mixtos; malloc_trim no siempre libera (arenas ≠ 0). → aplicar solo si se mide ganancia.
- ONNX Runtime: desactivar CPU mem arena reduce RSS 8–16 % con 3–7 % más latencia (reportes); fastembed (Python) puede no exponer SessionOptions → verificar con Context7.
- No aplicable sin hardware/caso de uso: PIM (UPMEM, HBM-PIM, AiM), CXL, Arrow/DuckDB, Bloom/VSA/SIMD, THP para heap de Python. KSM y zram son cambios de host privilegiados: solo diagnóstico/recomendación, no se aplican.

## Tareas (principio: MEDIR → aplicar → re-medir; se conserva solo lo que gana)
T0 Banco de medición reproducible (scripts/bench_ram.py o tests/bench): lanza un backend real con AEP_DATA_HOME temporal y una carga guionizada (discover, orient, autoevol graph, artifact_catalog query → embedder, sandbox_run con salida grande, kanban board); reporta VmRSS/RssAnon/VmSwap por fase y latencias p50. Base vs cambios, 3 corridas.
T1 process_inspect(pid=0): RSS correcto (VmRSS de /proc/self/status) + RssAnon/RssFile/VmSwap en detail. Test contra /proc/<pid>/status.
T2 memfd (compatibilidad + integridad): flags MFD_CLOEXEC|MFD_ALLOW_SEALING|MFD_EXEC(0x10); si EINVAL (kernel <6.3) reintentar sin MFD_EXEC. Tras escribir: fcntl F_ADD_SEALS F_SEAL_WRITE|F_SEAL_SHRINK|F_SEAL_GROW|F_SEAL_SEAL; ejecutar desde el fd sellado. Si vm.memfd_noexec=2 (o EACCES/EPERM al exec) → status claro (error_class memfd_noexec_enforced) con next_action (sandbox_run del binario del catálogo). fd_delta 0. Tests: sellos aplicados (F_GET_SEALS), fallback EINVAL simulado, noexec=2 simulado.
T3 Embedder: descarga por inactividad (AEP_EMBED_IDLE_S, defecto 600; 0 = nunca) + gc + recarga perezosa transparente; si fastembed permite SessionOptions, enable_cpu_mem_arena=False medido (conservar solo si RSS baja ≥10 % y latencia ≤+10 %). Thread-safe.
T4 Caché de análisis (engine/threads cached_analysis/LRU): acotar por número y/o bytes estimados; medir tamaño por entrada.
T5 SQLite: con mmap 256 MB activo, bajar cache_size por conexión (p. ej. -16000) SOLO si T0 muestra ganancia de RSS sin regresión >5 % en latencia de query; contar conexiones abiertas.
T6 Allocator: MALLOC_ARENA_MAX=2 en el entorno con que el front lanza el backend y malloc_trim(0) (ctypes, fail-soft, solo glibc) tras operaciones transitorias pesadas (analyze, reindex, embed_batch). Conservar solo con ganancia medida ≥10 % RSS en reposo y ≤5 % latencia; si no, revertir y documentar el resultado.
T7 sandbox_out (tmpfs = RAM): comprimir con compression.zstd (nivel 3) las salidas persistidas; paginación por cursor transparente; TTL/cap intactos.
T8 Instalador (fresh start): setup.sh --check añade línea "Memory" con vm.memfd_noexec (FAIL si 2: la ejecución en RAM de AEP no funciona; WARN si 1), THP, KSM, presión de swap (WARN si >90 % con recomendación de zram como acción manual del usuario, sin aplicarla) y los ajustes de memoria efectivos de AEP. Los valores por defecto viven en código (un fresh start los hereda); cualquier variable nueva (AEP_EMBED_IDLE_S, MALLOC_ARENA_MAX si se conserva) se documenta y setup.sh la escribe en toolchain.env solo si el usuario la fija. --update no la pisa.
## Reglas
No subir budgets; sin avisos → respuestas byte-idénticas (ONT-66) salvo campos nuevos de process_inspect detail; GAPS_BASELINE 0 (tests llaman funciones del proyecto); AEP_DATA_HOME temporal; ruff; nunca scripts/aep-ctl con ruff; pre-commit sin --no-verify; docs sin "<n> herramientas/tools/capacidades". Ningún cambio de sysctl/zram/KSM del host.
## Entregable de medición (obligatorio en el informe)
Tabla base vs final por fase (RSS, RssAnon, swap, latencia) y por tarea qué se conservó y qué se revirtió con su número.

## Resultados medidos (Pragma, banco scripts/bench_ram.py, 3 corridas, mediana)
Datos: docs/pipeline/ont67_bench_{base,t3,t4,final}.json. Candidato = AEP_EMBED_IDLE_S=2 y espera de 6 s en reposo.
- T0 base: reposo 548 592 kB RSS (RssAnon 499 044). T1: el rss_kb de process_inspect ya era VmRSS (330 916 vs 333 380 en vivo); los 31 596 kB no se reprodujeron; se añadió el bloque `memory` (detail).
- T2 aplicado (compatibilidad/integridad). T3 conservado: descarga por inactividad + malloc_trim, reposo -21,3 % (tras T3 solo; sin trim -3,5 %); recarga 5,9 -> ~129 ms una vez. enable_cpu_mem_arena=False: sin ganancia (529 268 vs 529 536 kB), no aplicado.
- T4 conservado: la caché de análisis retenía ~168 MB por entrada (type_index con todos los AST) -> 6,2 MB. Reposo final 328 188 kB (-40,2 %), RssAnon -44,3 %.
- T5 NO aplicado: artifacts.db de 151 MB, 90 lecturas de blob, RSS idéntico (283 MB) y latencia 1,38 vs 1,37 ms con cache_size -64000 y -16000 (las conexiones se cierran por uso).
- T6 NO aplicado: malloc_trim tras analyze/embed_batch +1,2 % RSS sin él vs con él (sin ganancia); MALLOC_ARENA_MAX=2 -0,1 %; PYTHONMALLOC=malloc +3,7 % RSS y +39 % latencia de autoevol. Solo se conserva malloc_trim en la descarga del embedder (T3).
- T7 conservado: zstd nivel 3 en salidas >= 4 KiB (17,3x en seq, 4,1x en código, 3,4x en git log); coste ~6 ms en el caso de 2,7 MB.
- T8: línea Memory en setup.sh --check (FAIL si memfd_noexec=2); AEP_EMBED_IDLE_S solo se persiste si el usuario la fija y el reescrito de toolchain.env la conserva.
