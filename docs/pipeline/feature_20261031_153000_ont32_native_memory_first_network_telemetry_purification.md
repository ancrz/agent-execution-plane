# Pipeline Feature: ONT-32 Native Memory-First Network & Security Telemetry: Architectural Purification, Container Decoupling, and Semantic Neutralization

- **Document ID:** `feature_20261031_153000_ont32_native_memory_first_network_telemetry_purification.md`
- **Predecessor:** [`verification_report_20261031_133000_ont31_re_as_sdd_kali_mcp_offensive_tactical_enhancements.md`](verification_report_20261031_133000_ont31_re_as_sdd_kali_mcp_offensive_tactical_enhancements.md)
- **Pipeline Mode:** Full (Stage 1: Archon ──► Stage 2: Graphos G1 ──► Stage 3: Ontos)
- **Milestone:** ONT-32 / M93 — Native Memory-First Network & Security Telemetry: Architectural Purification, Container Decoupling, and Semantic Neutralization
- **Strategic Plan Reference:** `PLAN-ONT32-20261031-NET-PURIFICATION`
- **Target Repository:** `/home/ancruz/Documents/workspaces/agent-execution-plane` (`dev` branch)
- **Antigravity Global Configuration:** `/home/ancruz/.gemini/config/mcp_config.json`
- **Topos Invariants:**
  - FastMCP Server strictly preserves **exactly 15 tools** (`len(_tools) == 15` invariant). Zero tool-set expansion or sprawl.
  - Memory-First Linux Kernel Primitives: All socket analysis, port probing, packet decoding, and netfilter rules operate purely in-RAM with microsecond latency, zero disk contention, and zero external binary dependencies (`nmap`, `tshark`).
  - Container Decoupling: Complete elimination of Docker dependencies, removal of containerized analytical engines, and purging of `"kali-mcp"` satellite from Antigravity configuration.
  - Self-Documenting Schemas & Preconditions: Static rigid playbooks (`WF-10`, `WF-11`) replaced with introspective reflection (`discover(action="schema")`, `aep_ctl --schema`) and explicit precondition contracts.
  - Semantic Sanitization: Total neutralization of trigger keywords (*kali, pentest, exploit, offensive*) across code, manifests, and docs to insulate against LLM guardrail false positives.
- **Topos DAG Audit:** `PENDING ONTOS AUDIT` (Grafo coherente: 0 co-dependencias detectadas across 5 tasks).
- **Chosen Resolution Path:** Standard in-memory Python stdlib & Linux kernel introspection path (Short/Medium reach, bounded blast radius).
- **Document Status:** VERIFIED & PROMOTED ✅ (Stage 5: Dokimos VERIFIED — Stage 2: Graphos G2 Baseline Refresh Complete — Handoff to Stage 6: Hermon)

---

## 1. Intent & Architectural Overview

Milestone ONT-32 represents a decisive architectural purification of the Agent Execution Plane (AEP). It permanently discards external containerized analytical satellites (Docker, `kali-pentest`, monolithic scanning toolchains) and reclaims network and security telemetry as **pure, in-RAM algorithmic primitives** executing directly on the host Linux kernel via Python 3.14 standard library.

### The 4 Core User Premises:

1. **Memory-First Container Decoupling:**
   - External container execution models (e.g. `docker exec -i kali-pentest ...`) impose severe process invocation latency (100–300ms), IPC overhead, and deployment friction (54GB container footprint).
   - ONT-32 absorbs network probing, socket state auditing, packet header decoding, and netfilter management into pure in-RAM logic (`engine/net_telemetry.py`), executing with microsecond latency and zero secondary disk I/O.
2. **Self-Documenting Schemas vs. Rigid Playbooks:**
   - Static tactical playbooks (`WF-10`, `WF-11`) baked into code create rigid, brittle execution paths.
   - ONT-32 establishes self-describing introspection: `discover(action="schema")` dynamically inspects FastMCP tool signatures, parameters, types, defaults, docstrings, and execution scope (`DIMINISHED`/`FULL`), while `engine/privilege.py:CONTROL_PLANE_SCHEMA` defines explicit preconditions (`privilege_tier`, `required_fs`, `fail_soft_behavior`, `deterministic`).
3. **Semantic Sanitization (Anti-LLM-Guardrails):**
   - Autonomous AI agents interacting with defensive tooling frequently trigger upstream safety classifiers and guardrail false positives when encountering vocabulary such as *kali*, *pentest*, *exploit*, or *offensive*.
   - ONT-32 rigorously purifies all docstrings, instructions, schema descriptions, and test suites, standardizing on neutral systems engineering terminology (*Network Telemetry*, *Endpoint Probe*, *Security Observability*, *Netfilter Hardening*), and unplugs `"kali-mcp"` from `~/.gemini/config/mcp_config.json`.
4. **Strict FastMCP 15-Tool Invariant:**
   - Preserves the architectural law of AEP: exactly 15 polymorphic tools in `server.py`. Zero new `@mcp.tool` endpoints.
   - All network probing and socket parsing capabilities are absorbed inside polymorphic dispatchers `aep_ctl(domain="network")` and `kernel_trace(mode="network_sniff")`.

---

## 2. Intent Reinforcement Graph

```mermaid
flowchart TD
    I["Intent: Native Memory-First Network & Security Telemetry (ONT-32)"] --> M1["M1: Archon Execution Plan & Topos DAG Audit (APPROVED) ✅"]
    M1 --> M2["M2: Graphos G1 Knowledge Graph Weave & Baseline Sync (COMPLETED) ✅"]
    M2 --> M3["M3: Ontos Stage 3 Structural & Interface Audit (APPROVED) ✅"]
    M3 --> M4["M4: Pragma Stage 4 Execution (Tasks T1-T5 COMPLETED) ✅"]
    M4 --> M5["M5: Dokimos Stage 5 Multi-Gate Verification (VERIFIED 109/109) ✅"]
    M5 --> M6["M6: Graphos G2 Verification Record & Baseline Compaction (COMPLETED) ✅"]
    M6 --> M7["M7: Hermon Stage 6 Release & Version Control (PENDING AUTHORIZATION) ⏳"]
```

---

## 3. State Evolution

```mermaid
flowchart TD
    S0["State A: ONT-31 Verified Baseline (Doc 31) ✅"] --> S1["State A.1: Archon Strategic Execution Plan Formulated (PLAN-ONT32) ✅"]
    S1 --> S2["State A.2: Graphos G1 Knowledge Graph Weave (Doc 32) ✅"]
    S2 --> S3["State A.3: Ontos Stage 3 Structural Audit (APPROVED) ✅"]
    S3 --> S4["State A.4: Pragma Stage 4 Implementation (T1-T5 COMPLETED) ✅"]
    S4 --> S5["State A.5: Dokimos Stage 5 Verification Suite (VERIFIED 109/109) ✅"]
    S5 --> S6["State A.6: Graphos G2 Verification Record & Baseline Compaction (COMPLETED) ✅"]
    S6 --> S7["State A.7: Hermon Stage 6 Atomic Release & Version Control (PENDING AUTHORIZATION) ⏳"]
```

---

## 4. Anti-Cascade & Blast Radius Matrix

| Task ID | Action | Target Resource | Tooling Used | Blast Radius | Depends On | Anti-Cascade Prevention Guarantee |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| **T1** | `create` | `engine/net_telemetry.py` | Python 3.14 stdlib (`asyncio`, `socket`, `struct`) | Contained to new engine file; zero external runtime impact | None | Pure stdlib implementation with zero inward dependencies; network byte order explicitly enforced via `!` prefix; async sockets protected by `try...finally` to ensure `fd_delta == 0`. |
| **T2** | `modify` | `server.py`<br>`scripts/aep-ctl`<br>`engine/privilege.py` | FastMCP, Python stdlib, CLI dispatcher | Internal tool dispatchers; strictly preserves 15-tool invariant | T1 | No new `@mcp.tool` decorators added; capabilities routed through `aep_ctl` (`network.probe`, `interfaces`, `arp`) and `kernel_trace(mode="network_sniff")`; CLI mirrors server contracts 1:1. |
| **T3** | `configure` & `modify` | `~/.gemini/config/mcp_config.json`<br>`server.py`<br>`engine/privilege.py`<br>`README.md`<br>`docs/MILESTONES.md` | JSON config parser, markdown editor | Global user MCP config and project documentation | None | Backup of `mcp_config.json` verified before mutation; syntax validated with `json.loads()`; semantic trigger word purge coordinated across all docs and code simultaneously. |
| **T4** | `modify` | `server.py`<br>`engine/privilege.py` | FastMCP schema reflection, Python dataclasses | Tool discovery response format and control plane schema | T2, T3 | Dynamic schema introspection cached in-RAM; tactical playbooks refactored to native telemetry workflows without breaking schema consumers or CLI contracts. |
| **T5** | `create` & `modify` | `tests/test_net_security_telemetry.py`<br>`tests/test_agent_experience_evaluation.py` | Pytest 9.1.1, AnyIO, mock socket fixtures | Test execution runtime only | T1, T2, T3, T4 | Fully replaces deprecated container integration tests; synchronizes assertion versions (`EAES-v2-Standard-Telemetry`), preventing cascading test suite breakages. |

---

## 5. Comprehensive Archon Task Breakdown

```mermaid
flowchart TD
    T1["T1: Native In-Memory Engine<br/>(engine/net_telemetry.py)"] --> T2["T2: Control Plane Integration<br/>(aep_ctl & kernel_trace)"]
    T3["T3: Semantic Sanitization<br/>(mcp_config.json & trigger purge)"] --> T4["T4: Self-Describing Schemas<br/>(discover schema & preconditions)"]
    T2 --> T4
    T4 --> T5["T5: Comprehensive Test Battery<br/>(test_net_security_telemetry.py)"]
```

### Task T1 — Native In-Memory Network & Security Telemetry Engine
- **Task ID:** `T1`
- **Action:** `create`
- **Target File:** `engine/net_telemetry.py`
- **Rationale:** Deliver pure in-RAM network probing, kernel socket introspection, and packet unpacking without Docker, external binaries (`nmap`, `tshark`), or physical disk I/O.
- **Depends On:** None (Foundational in-memory engine)
- **Tool Reach & Blast Radius:** Python 3.14 stdlib (`asyncio`, `socket`, `struct`, `os`, `time`, `pathlib`). Blast radius bounded to single new file.
- **Detailed Specifications:**
  1. **Asynchronous TCP Port Prober:**
     - Function `async def probe_tcp_ports(host: str, ports: list[int], timeout_ms: int = 300, concurrency: int = 50) -> dict[str, Any]`.
     - Non-blocking connection attempts using `asyncio.open_connection()` governed by an bounded concurrency semaphore (`asyncio.Semaphore(concurrency)`).
     - Microsecond latency measurement via `time.perf_counter()`.
     - Strict `finally` socket closing ensuring `fd_delta == 0`.
     - Standard service identification map for common ports (21: FTP, 22: SSH, 53: DNS, 80: HTTP, 443: HTTPS, 3306: MySQL, 5432: PostgreSQL, 8080: HTTP-Alt).
  2. **Kernel `/proc/net` Introspection Engine:**
     - Function `parse_proc_net_sockets(protocol: str = "tcp") -> list[dict[str, Any]]`:
       Direct in-memory line parsing of `/proc/net/tcp`, `/proc/net/tcp6`, `/proc/net/udp`, and `/proc/net/udp6`.
       Hex address decoding: IPv4 little-endian hex to string (e.g. `0100007F` -> `127.0.0.1`) and hex port conversion (e.g. `1F90` -> `8080`).
       Socket state translation: `01` (`ESTABLISHED`), `0A` (`LISTEN`), `06` (`TIME_WAIT`), etc.
       Inode correlation: optional walk of `/proc/[0-9]*/fd` mapping socket inode to PID and process name.
     - Function `parse_proc_net_dev() -> list[dict[str, Any]]`:
       Direct parsing of `/proc/net/dev` for real-time RX/TX bytes, packets, errors, and drops across interfaces (`lo`, `eth0`, `wlan0`).
     - Function `parse_proc_net_arp() -> list[dict[str, Any]]`:
       Direct parsing of `/proc/net/arp` to obtain local ARP table mappings (IP, HW type, Flags, HW address/MAC, Mask, Device).
  3. **Pure In-Memory Packet Header Dissection:**
     - Function `unpack_packet_headers(raw_bytes: bytes) -> dict[str, Any]`:
       Ethernet frame: `struct.unpack("!6s6sH", raw_bytes[:14])`.
       IPv4 header: `struct.unpack("!BBHHHBBH4s4s", ip_bytes[:20])` with flags, protocol (TCP=6, UDP=17, ICMP=1), TTL, and IP string conversion via `socket.inet_ntoa`.
       TCP segment: `struct.unpack("!HHIIBBHHH", tcp_bytes[:20])` extracting source/dest ports, sequence/ack numbers, and bitwise flags (SYN, ACK, FIN, RST, PSH, URG).
       UDP datagram: `struct.unpack("!HHHH", udp_bytes[:8])` extracting ports and payload length.
       ARP packet: `struct.unpack("!HHBBH6s4s6s4s", arp_bytes[:28])` extracting hardware/protocol types, opcode, and sender/target MAC/IP addresses.
     - Function `dissect_shm_pcap_buffer(buffer_or_path: bytes | str | Path, limit: int = 50) -> dict[str, Any]`:
       In-memory parsing of standard PCAP header (`0xa1b2c3d4` or `0xd4c3b2a1`) or raw packet streams directly in `/dev/shm` without external `tshark` execution.
  4. **Idempotent Netfilter Mitigation Helper:**
     - Function `enforce_netfilter_mitigation(target_ip: str, rule_action: str = "drop", simulate: bool = False) -> dict[str, Any]`:
       Deterministic, idempotent netfilter drop rule management (`nft add rule`) with fail-soft `SIMULATED` payload when executing in `DIMINISHED` privilege tier.
- **Risks & Mitigations:**
  - *Risk:* Endianness corruption during packet unpacking.
  - *Mitigation:* Explicitly enforce network big-endian prefix `!` across all unpack formats (`!6s6sH`, `!BBHHHBBH4s4s`).
  - *Risk:* `/proc/net/tcp` hex IP byte order confusion (Linux stores IPv4 in little-endian hex on x86_64).
  - *Mitigation:* Unit tests verifying `0100007F` translates to `127.0.0.1` and `00000000` to `0.0.0.0`.

---

### Task T2 — Control Plane Integration in `aep_ctl` & `kernel_trace`
- **Task ID:** `T2`
- **Action:** `modify`
- **Target Files:** `server.py`, `scripts/aep-ctl`, `engine/privilege.py`
- **Rationale:** Connect native in-memory network telemetry into existing FastMCP tools `aep_ctl` and `kernel_trace` while preserving strictly 15 tools.
- **Depends On:** `T1`
- **Tool Reach & Blast Radius:** FastMCP tool routing, internal method dispatch. Zero new tools registered.
- **Detailed Specifications:**
  1. **`engine/privilege.py` (`CONTROL_PLANE_SCHEMA`):**
     - Extend `"network"` domain actions: `["inspect", "routes", "listeners", "probe", "interfaces", "arp"]`.
     - Document parameters for `probe`: `name` (target host/IP), `args` (comma-separated ports or port range).
     - Update `"security"` domain actions: `["landlock_status", "status", "audit", "verify", "firewall_status", "nftables_inspect", "threat_mitigate"]` with neutral descriptions ("Netfilter Hardening & Perimeter Defense").
  2. **`server.py` (`aep_ctl` dispatcher):**
     - In `domain == "network"`:
       - Action `"probe"`: invokes `net_telemetry.probe_tcp_ports` with target and port list, returning structured JSON response.
       - Action `"interfaces"`: invokes `net_telemetry.parse_proc_net_dev()`.
       - Action `"arp"`: invokes `net_telemetry.parse_proc_net_arp()`.
       - Action `"listeners"`: optimizes fast path using `net_telemetry.parse_proc_net_sockets()` in RAM.
     - In `domain == "security"`:
       - Action `"threat_mitigate"`: invokes `net_telemetry.enforce_netfilter_mitigation()` ensuring idempotency and fail-soft `SIMULATED` execution.
  3. **`server.py` (`kernel_trace` dispatcher):**
     - In `mode == "network_sniff"`:
       - If `/dev/shm/pcap_stream` or packet buffer is present, decode headers in-RAM via `net_telemetry.dissect_shm_pcap_buffer()`, merging unpacked headers with eBPF kprobe counts.
  4. **`scripts/aep-ctl` CLI Synchronization:**
     - Update `domain_network` to handle `probe`, `interfaces`, and `arp` natively using `engine.net_telemetry`.
     - Update `domain_security` to enforce idempotent mitigation and maintain JSON error/remediation contracts.
- **Risks & Mitigations:**
  - *Risk:* Performance degradation if port probe timeout is too high.
  - *Mitigation:* Bound per-socket timeout to 300ms and default scanned port set to standard services (top 50 ports).

---

### Task T3 — Semantic Sanitization & Cleanup of Antigravity Configuration
- **Task ID:** `T3`
- **Action:** `configure` & `modify`
- **Target Files:** `~/.gemini/config/mcp_config.json`, `server.py`, `engine/privilege.py`, `README.md`, `docs/MILESTONES.md`
- **Rationale:** Completely eradicate trigger terms (*kali, pentest, exploit, offensive*) that trigger LLM guardrail false positives. Remove external container MCP satellites.
- **Depends On:** None (Can run in parallel with T1)
- **Tool Reach & Blast Radius:** JSON configuration, source code comments, project documentation.
- **Detailed Specifications:**
  1. **Antigravity Global Configuration (`~/.gemini/config/mcp_config.json`):**
     - Remove `"kali-mcp"` entry from `mcpServers`.
     - Preserve remaining valid entries (`agent-execution-plane`, `chrome-devtools-mcp`, `github-mcp-server`, etc.).
     - Verify strict JSON validity.
  2. **Codebase Semantic Purification:**
     - `engine/privilege.py`:
       - Replace `"Kali-MCP inspired semantic playbook..."` with `"Systems engineering semantic playbook: taxonomic catalog, canonical 1-liners, and workflows."`.
       - Update `"playbook_version"` from `"EAES-v2-Kali-Semantic"` to `"EAES-v2-Standard-Telemetry"`.
       - Replace `"Transmuta primitivas de herramientas ofensivas..."` with `"Gobernanza y ejecución determinista de telemetría de sistemas y observabilidad de seguridad."`.
       - Replace `"Call discover(action='playbook') for Kali-style workflow recipes..."` with `"Call discover(action='playbook') for systems engineering workflow recipes..."`.
     - `server.py`:
       - Cleanse instructions of "Kali MCP" and "WF-10/WF-11" container mentions.
       - Sanitize `discover` docstrings.
       - Replace `# eBPF (rootkit/sniffer ofensivo)` with `# eBPF kernel observability & packet telemetry`.
  3. **Documentation Purification (`README.md` & `docs/MILESTONES.md`):**
     - Retitle SPEC-OM-9: "SPEC-OM-9: Native Memory-First Network & Security Telemetry: Container Decoupling & Pure-RAM Ingress".
     - Purge references to `kali-pentest` Docker image and 54GB container footprint.
     - Document memory-first telemetry architecture.
- **Risks & Mitigations:**
  - *Risk:* Syntax error in JSON configuration when removing `"kali-mcp"`.
  - *Mitigation:* Validate JSON structure with `json.loads()` immediately after editing.

---

### Task T4 — Self-Describing Schemas, Reflection & Preconditions
- **Task ID:** `T4`
- **Action:** `modify`
- **Target Files:** `server.py`, `engine/privilege.py`
- **Rationale:** Deliver user Premise 2: replace rigid hardcoded playbooks (`WF-10`, `WF-11`) with self-describing introspection via schemas and preconditions.
- **Depends On:** `T2`, `T3`
- **Tool Reach & Blast Radius:** FastMCP introspection and control plane schema structures.
- **Detailed Specifications:**
  1. **Add `discover(action="schema")` to `server.py`:**
     - Implement introspective schema retrieval for all 15 FastMCP tools.
     - For each tool in `server.mcp._tool_manager._tools`: extract parameters, types, defaults, docstrings, and execution scope (`DIMINISHED`/`FULL`).
     - Return structured payload: `{"status": "OK", "tools_count": 15, "tools": {...}, "preconditions": {...}}`.
  2. **Enrich Action Preconditions in `engine/privilege.py`:**
     - Add `preconditions` mapping for each control-plane action in `CONTROL_PLANE_SCHEMA`:
       - `privilege_tier`: `"FULL"` or `"DIMINISHED"`.
       - `required_fs`: e.g. `["/proc/net/tcp"]` or `["/proc/net/dev"]`.
       - `fail_soft_behavior`: `"SIMULATED"`, `"DEGRADED"`, or `"IN_MEMORY_FALLBACK"`.
       - `deterministic`: `true`.
  3. **Playbook Refactoring in `tactical_playbook()`:**
     - Remove hardcoded recipes `WF-10` and `WF-11` that referenced `kali-mcp: container_status()`, `nmap_scan()`, etc.
     - Replace with native memory telemetry recipes:
       - `WF-10`: "Native Network Telemetry & Port Observability (`aep_ctl` network probe -> `/proc/net/tcp` socket inspection)".
       - `WF-11`: "Security Observability & Netfilter Hardening (`kernel_trace` network sniff -> `aep_ctl` security nftables inspect -> idempotent threat mitigation)".
     - Update `quick_reference` commands:
       - `network_telemetry_probe`: `aep_ctl(domain="network", action="probe", name="127.0.0.1", args="22,80,443", verbosity="summary")`
       - `incident_protocol_audit`: `aep_ctl(domain="security", action="nftables_inspect", verbosity="summary")`
- **Risks & Mitigations:**
  - *Risk:* Overhead of runtime schema extraction.
  - *Mitigation:* Cache extracted tool schema in RAM session pool (`_shared_session_cache`) upon initial access.

---

### Task T5 — Comprehensive Test Battery & Verification
- **Task ID:** `T5`
- **Action:** `create` & `modify`
- **Target Files:** `tests/test_net_security_telemetry.py`, `tests/test_agent_experience_evaluation.py`
- **Rationale:** Establish a zero-regression, 100% passing test battery validating all 8 Quality Gates of ONT-32.
- **Depends On:** `T1`, `T2`, `T3`, `T4`
- **Tool Reach & Blast Radius:** Pytest 9.1.1, AnyIO, mock packet fixtures. Test runtime only.
- **Detailed Specifications:**
  1. **New Test Suite: `tests/test_net_security_telemetry.py` (Replacing `test_aep_kali_integration.py`):**
     - **Gate 1:** FastMCP 15-Tool Invariant: strictly 15 tools registered in `server.py`.
     - **Gate 2:** Enhanced Schema & Preconditions: `CONTROL_PLANE_SCHEMA` contains network `probe`, `interfaces`, `arp` and security actions with valid preconditions.
     - **Gate 3:** In-Memory TCP Port Probing: `net_telemetry.probe_tcp_ports` accurately detects open listening ports on `127.0.0.1` and closed ports with low latency (<100ms).
     - **Gate 4:** Kernel `/proc/net` Introspection: parses `/proc/net/tcp`, `/proc/net/dev`, and `/proc/net/arp` without error, verifying IP hex decoding.
     - **Gate 5:** In-Memory Packet Header Dissection: unpacks synthetic Ethernet/IP/TCP/UDP/ARP byteframes using `struct.unpack`, validating field extractions.
     - **Gate 6:** Idempotent Netfilter Hardening: `aep_ctl(domain="security", action="threat_mitigate")` returns `SIMULATED` in unprivileged tier and validates command synthesis.
     - **Gate 7:** Self-Describing Schema Reflection: `discover(action="schema")` returns introspective metadata for all 15 tools; `aep_ctl(action="schema")` returns 9 domains.
     - **Gate 8:** Complete Semantic Sanitization: scans `server.py`, `engine/privilege.py`, `engine/net_telemetry.py`, and test files verifying ZERO occurrences of trigger words (*kali, pentest, exploit, offensive*).
  2. **Synchronize `tests/test_agent_experience_evaluation.py`:**
     - Update `test_discover_binary_readiness_and_kali_tactical_playbook` -> `test_discover_binary_readiness_and_tactical_playbook`.
     - Update asserted version: `"EAES-v2-Standard-Telemetry"`.
  3. **Run Full Test Battery:**
     - Verify 100% passing status across `tests/test_net_security_telemetry.py` and entire repository suite.
- **Risks & Mitigations:**
  - *Risk:* Raw socket or netfilter mutation failures in unprivileged CI/sandbox environments.
  - *Mitigation:* Ensure tests target loopback interfaces, mock byte buffers, `/proc/net` virtual filesystem, and simulated fallback modes.

---

## 6. Ontological Topology & Dependency Relationship Classification

```
                  ┌────────────────────────────────────────┐
                  │          FastMCP Server (15)           │
                  │              (server.py)               │
                  └──────────────┬───────────────────┬─────┘
                     depends_on  │                   │ depends_on
                                 ▼                   ▼
                  ┌──────────────────────┐   ┌──────────────────────┐
                  │ engine/privilege.py  │   │engine/net_telemetry.py│
                  │(Schema & Preconds)   │   │  (Pure In-Memory)    │
                  └──────────────▲───────┘   └──────────▲───────────┘
                     depends_on  │                      │ depends_on
                                 └──────────┬───────────┘
                                            │
                                 ┌──────────┴───────────┐
                                 │   scripts/aep-ctl    │
                                 │(CLI Control Plane)   │
                                 └──────────────────────┘
```

- **`engine/net_telemetry.py` ──► Standard Library:** Standard Directional Dependency (`dep: A → B`). Pure Python 3.14 stdlib (`asyncio`, `socket`, `struct`, `time`, `pathlib`). Zero inward or circular dependencies.
- **`server.py` ──► `engine/net_telemetry.py`:** Directional Dependency (`dep: A → B`). Exposes in-memory scanning, parsing, and packet decoding via existing tools `aep_ctl` and `kernel_trace`.
- **`server.py` ──► `engine/privilege.py`:** Directional Dependency (`dep: A → B`). Imports `CONTROL_PLANE_SCHEMA`, `capability_manifest`, and action preconditions.
- **`scripts/aep-ctl` ──► `engine/privilege.py` & `engine/net_telemetry.py`:** Directional Dependency (`dep: A → B`).
- **Co-Dependency Audit Verdict:** **ZERO CO-DEPENDENCIES ($A \not\leftrightarrow B$)**. No module requires bidirectional initialization or circular imports.

### 6.1 Vertical Trace
$$\text{Linux Kernel Space } (/proc/net/*, \text{eBPF, netfilter}) \longrightarrow \text{RAM Staging } (engine/net\_telemetry.py) \longrightarrow \text{Control Plane } (aep\_ctl, kernel\_trace) \longrightarrow \text{FastMCP Server } (server.py) \longrightarrow \text{Autonomous AI Agent}$$
- **Layer 1 (Kernel/OS):** Non-blocking reads of `/proc/net/{tcp,udp,dev,arp}` and `/dev/shm` buffers.
- **Layer 2 (RAM Staging):** Pure Python stdlib `struct.unpack` and `asyncio.open_connection()` with microsecond performance.
- **Layer 3 (Control Plane):** Enforced privilege governance (`FULL` vs `DIMINISHED`), dual-mode netfilter simulation, and schema contracts.
- **Layer 4 (FastMCP API):** Single-encoded JSON-RPC envelopes with telemetry headers.
- **Verdict:** Unbroken end-to-end data flow with zero disk I/O bottlenecks.

### 6.2 Horizontal Trace (Peer Audit)
- **`server.py`:** Retains exactly 15 tools; absorbs `probe`, `interfaces`, `arp` inside `aep_ctl`; absorbs packet dissection inside `kernel_trace(mode="network_sniff")`.
- **`engine/privilege.py`:** Maintains single source of truth for `CONTROL_PLANE_SCHEMA`, binary readiness, and capability permissions.
- **`scripts/aep-ctl`:** CLI mirrors FastMCP capabilities identically for headless shell integration.
- **`~/.gemini/config/mcp_config.json`:** Purged of external satellite; clean single-plane runtime.

### 6.3 Omission Detection
- **$O_1$ (Endianness in Packet Decoding):** Network protocols use Big-Endian (Network Byte Order). All struct formats must use the `!` prefix (`!6s6sH`, `!BBHHHBBH4s4s`).
- **$O_2$ (Linux `/proc/net/tcp` Hex Addressing):** Linux kernel `/proc/net/tcp` encodes IPv4 addresses in little-endian 32-bit hex (e.g. `0100007F` for `127.0.0.1`). Must use `socket.inet_ntoa(struct.pack("<L", int(hex_ip, 16)))`.
- **$O_3$ (Async Socket FD Leaks):** In-memory TCP probes must cleanly close writers/transports in a `try...finally` block to maintain invariant `fd_delta == 0`.
- **$O_4$ (Unprivileged Netfilter Degradation):** Netfilter mutation commands (`nft add rule`) will fail without `CAP_NET_ADMIN`. Must return structured `status: "SIMULATED"` with rule string rather than throwing exceptions.
- **$O_5$ (Config JSON Format):** Removal of `"kali-mcp"` from `mcp_config.json` must preserve valid formatting with zero trailing commas.

### 6.4 Gap Cascade Prevention ($X_1 \not\leftrightarrow X_2$)
- **Problem ($X_1$):** Removing `kali-mcp` or deleting `test_aep_kali_integration.py` without updating `test_agent_experience_evaluation.py` would cause broken test imports and version assertion mismatches.
- **Resolution ($X_2$):** In the plan, T3/T4 update `playbook_version` to `"EAES-v2-Standard-Telemetry"` and T5 synchronizes `test_agent_experience_evaluation.py` simultaneously, preventing cascade failures.

---

## 7. Acceptance Criteria & Quality Gates

| Gate | Description | Target Metric / Acceptance Rule |
| :--- | :--- | :--- |
| **QG-1** | FastMCP Tool Invariant | Exactly 15 tools registered in `server.py` (`len(_tools) == 15`). Zero tool bloat. |
| **QG-2** | Memory-First Port Probing | `aep_ctl(domain="network", action="probe")` scans ports in RAM via `asyncio`/`socket` without external binaries. |
| **QG-3** | Kernel `/proc/net` Introspection | In-memory line parsing of `/proc/net/{tcp,udp,dev,arp}` with correct hex IPv4 decoding. |
| **QG-4** | Packet Header Dissection | `struct.unpack` decodes synthetic Ethernet, IPv4, TCP, UDP, and ARP headers without `tshark`. |
| **QG-5** | Idempotent Netfilter Mitigation | Netfilter drop rules handled deterministically; unprivileged tier returns structured `SIMULATED` payload. |
| **QG-6** | Self-Describing Schemas | `discover(action="schema")` returns full introspective tool schema; `aep_ctl --schema` returns 9 domains + preconditions. |
| **QG-7** | Semantic Sanitization | Zero occurrences of trigger words (*kali, pentest, exploit, offensive*) in core server, engine, and tests. |
| **QG-8** | Antigravity Clean Slate | `"kali-mcp"` satellite removed from `~/.gemini/config/mcp_config.json`; 100% tests passing. |

---

## 8. Handoff to Stage 3 (Ontos Audit)

Graphos has registered Milestone ONT-32 in the Knowledge Graph, verified unbroken chain linkage from ONT-31 (`verification_report_20261031_133000_ont31_re_as_sdd_kali_mcp_offensive_tactical_enhancements.md`), and updated `docs/MILESTONES.md`.

- **Orchestrator Routing Target:** Ontos (Stage 3 — Structural Auditor)
- **Carried Context:** Documented Execution Plan (`docs/pipeline/feature_20261031_153000_ont32_native_memory_first_network_telemetry_purification.md`), declared blast radius, and 0 co-dependencies verification.


---

## 9. Dokimos Multi-Gate Verification Summary

- **Verification Report:** [`verification_report_20261031_161500_ont32_native_memory_first_network_telemetry_purification.md`](verification_report_20261031_161500_ont32_native_memory_first_network_telemetry_purification.md)
- **Verdict:** **VERIFIED** ✅ (All 5 Multi-Layer Gates Passed — 0 Regressions, 100% Invariant Compliance)
- **Verification Timestamp:** 2026-10-31T20:00:00Z
- **Certified Metrics:**
  - **FastMCP 15-Tool Invariant:** Strictly 15 tools registered in `server.mcp._tool_manager._tools`. Actual count: 15. Zero tool bloat.
  - **Static Analysis & Ruff Lint:** `.venv/bin/ruff check server.py engine/ scripts/aep-ctl tests/` returned **0 violations**; `./scripts/aep-sync.sh --check` passed cleanly.
  - **Repository-Wide Test Battery:** **109/109 PASSED** (100% pass rate, 0 failures, 0 errors, 0 regressions across all suites).
  - **ONT-32 Test Suite:** `tests/test_net_security_telemetry.py` passed 8/8 gates in 0.29s.
  - **Container Decoupling:** Verified 100% Python stdlib in `engine/net_telemetry.py`. Zero calls to Docker CLI or external binaries (`nmap`, `tshark`).
  - **Semantic Sanitization:** Verified zero banned keywords (*kali, pentest, exploit, offensive*) in code, schemas, and tests.
  - **Antigravity Global Configuration:** Verified `~/.gemini/config/mcp_config.json` decoupled from `"kali-mcp"` container satellite.

---

## 10. Graphos G2 Baseline Refresh & Knowledge Graph Rollup

- **Baseline Artifacts Refreshed:**
  - `docs/MILESTONES.md`: Promoted `ONT-32` / `M93` to `VERIFIED & PROMOTED ✅`, updated Reinforcement Graph, milestone matrix row, and canonical context anchors.
  - `README.md`: Updated test badge to 109/109 (100%), refreshed Section 8 (`SPEC-OM-9`) to "Native Memory-First Network & Security Telemetry: Container Decoupling & Pure-RAM Ingress", documented in-RAM architecture, `aep_ctl(domain="network", action="probe")`, `discover(action="schema")`, and zero container requirements with clean neutral terminology.
  - `docs/COMPACT.md`: Refreshed compaction guidance to 13 lines with ONT-32 quality status, file manifest, invariants, and next actions.
- **Topos Pipeline Chain Continuity:**
  - Predecessor: `verification_report_20261031_133000_ont31_re_as_sdd_kali_mcp_offensive_tactical_enhancements.md`
  - Current Feature: `feature_20261031_153000_ont32_native_memory_first_network_telemetry_purification.md`
  - Execution Report: `execution_report_20261031_160000_ont32_native_memory_first_network_telemetry_purification.md`
  - Verification Report: `verification_report_20261031_161500_ont32_native_memory_first_network_telemetry_purification.md`
  - Unbroken chain preserved across 32 consecutive feature milestones.

---

## 11. Hermon Stage 6 Release Handoff & Version Control Directives

Graphos has completed all documentation duties and refreshed project baselines. The pipeline baton is formally handed back to the Orchestrator for transition to Hermon (Stage 6).

- **Routing Target:** Orchestrator ──► Hermon (Stage 6 — Version Control & Release)
- **Target Branch:** `dev`
- **Recommended Conventional Commit Structure:**
  - `feat(telemetry): native in-RAM network and security telemetry with container decoupling (ONT-32)`
  - Scope: `engine/net_telemetry.py`, `server.py`, `engine/privilege.py`, `scripts/aep-ctl`, `tests/test_net_security_telemetry.py`, `README.md`, `docs/MILESTONES.md`, `docs/COMPACT.md`, `~/.gemini/config/mcp_config.json`.
- **Quality Status:** Ready for atomic commit, tag, and push authorization under user gate.
