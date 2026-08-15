# M14 Research: Non-Root Per-Process Network Visibility on Android 11

**Device probed:** Vivo V2026 (`ZP4XTCTGFIXKIFPZ`), Android 11, kernel `vivo`,
shell uid. All findings below were produced live on this device through
`adb shell` on **2026-08-15**; nothing here is assumed from desktop Linux.

Capability labels used throughout:

* **VERIFIED** — observed working on the Vivo through adb as `shell`.
* **PROBABLE** — consistent across Android 11/Linux kernels but not observed.
* **UNAVAILABLE** — observed blocked, or no non-root path exists.

---

## A. Network sources available on Android 11 (investigated)

| Source | Contents | Readable as shell (probed) |
|---|---|---|
| `/proc/net/tcp` | IPv4 TCP socket table: endpoints, state, uid, inode | VERIFIED (`-r--r--r--`) |
| `/proc/net/tcp6` | IPv6 TCP socket table (same columns) | VERIFIED |
| `/proc/net/udp` | IPv4 UDP socket table | VERIFIED |
| `/proc/net/udp6` | IPv6 UDP socket table | VERIFIED |
| `/proc/net/{raw,raw6,unix,netlink,packet,…}` | other socket families | mostly world-readable; out of scope |
| `/system/bin/ss` | inet_diag socket dump incl. process info | **netlink socket open DENIED** |
| `pm list packages -U` | installed package → uid mapping | VERIFIED |
| `/proc/<pid>/fd` | fd → socket inode (inode→PID mapping) | **Permission denied** (app and system) |
| `dumpsys netstats` | per-uid byte counters | readable, but *bytes*, not sockets |
| `/proc/net/dev` | per-interface counters (no sockets) | already consumed by M13 |

## B. What is readable without root — VERIFIED on the Vivo

* `/proc/net/tcp`, `/proc/net/tcp6`, `/proc/net/udp`, `/proc/net/udp6`
  world-readable (mode `-r--r--r--`, root:root).
* `pm list packages -U` (e.g. `package:com.android.chrome uid:10183`).
* The socket tables expose: local/remote endpoints (hex), TCP state (hex),
  UID (decimal) and inode (decimal).

## C. Socket → UID / PID

* **UID → socket: VERIFIED.** The socket tables carry a decimal UID column
  (observed `0`, `1000`, `10164`, `10183`, `10203`, …).
* **socket → PID: UNAVAILABLE without root.** The only non-root path is
  inode → `/proc/<pid>/fd` scanning, and on this device
  `ls -l /proc/<pid>/fd` returns **Permission denied** for *both* a normal
  app (`com.android.chrome`) and even `system_server`. `ss -p` needs the
  netlink diag socket, which is also denied. → **PID attribution is
  impossible on this device; we will not fabricate it.**

## D. UID → Android package

**VERIFIED.** `pm list packages -U` maps packages to uids without root:
`com.android.chrome → 10183`, `com.google.android.youtube → 10181`,
`com.instagram.android → 10203`. Multiple packages can share one UID
(`sharedUserId`); the mapping is presented as a *set* of packages per UID,
never an arbitrary single pick.

## E. TCP / UDP

* TCP: **VERIFIED** (all fields present).
* UDP: **VERIFIED** as a distinct table. UDP rows always report `st 07`
  (kernel "unconnected" marker) and have no TCP-style connection states;
  UDP is represented without state, never forced into the TCP model.

## F. IPv4 — VERIFIED

Little-endian hex decode, e.g. `B900A8C0` → `192.168.0.185` (observed in
real rows).

## G. IPv6 — VERIFIED

`tcp6/udp6` use the standard 32-hex-digit little-endian word-swapped form
(observed live). Rows included **native IPv6** (`2402:8100:…`) and
**NAT64** (`64:ff9b::…`) endpoints. Decoding is implemented and tested; a
native IPv6 row must never be mis-decoded into IPv4.

## H. Connection states — VERIFIED

TCP states present in real data: `01` ESTABLISHED, `04` FIN-WAIT-1,
`09` LAST-ACK, `0A` LISTEN (others per the standard table; unknown hex
values render as the raw code, never invented). `TIME_WAIT`/`CLOSE_WAIT`
come from the same documented table and are covered by unit tests.

## I. Interface association — UNAVAILABLE

`/proc/net/tcp*` has no interface column; per-socket interface attribution
requires root (`netlink inet_diag` / `skb` internals). Interface names
(ccmni0-7, wlan0, …) are *never* guessed from IP ranges.

## J. Permission limitations (device-verified)

1. `/proc/<pid>/fd` — denied for every process, including system services.
2. netlink inet_diag (`ss`, `ss -p`) — "Cannot open netlink socket:
   Permission denied".
3. Everything else we use is world-readable.

## K. Expected Vivo V2026 behaviour (observed, so "expected" = what we saw)

* 4 socket tables readable; tiny volumes (probed: TCP 5, TCP6 49, UDP 6,
  UDP6 16 rows ≈ 76 rows total) — trivially cheap to read.
* `tcp6` rows carry extra trailing kernel columns (e.g. `ref pointer`),
  so parsers must tolerate variable trailing fields.
* NAT64 endpoints appear as IPv6 `64:ff9b::` addresses.
* Interfaces: `ccmni0..7`, `wlan0`, `dummy0`, `lo` (existing M13 classifier
  already handles naming).

## L. Security / privacy implications

* Feature is **local read-only observability**: socket table dumps expose
  endpoints/ports/state and the owning UID. No packet contents, no
  interception, no capture.
* PID-level attribution is impossible on this device; claiming it would be a
  security-relevant lie. The UI therefore attributes at the
  **UID/package level with explicit confidence wording**.
* The socket table contains kernel UIDs (`0`, `1000`, `1020`…) that map to
  no package → those rows are shown as "system/unknown", never assigned a
  guessed package.
* No remote lookups (reputation, geolocation, DNS) are added in M14.

## M. Performance implications

* One collection pass = 4 tiny `cat` reads of `/proc/net/tcp{,6,udp,udp6}`
  plus `pm list packages -U` at a **dedicated 10 s cadence**
  (configurable), not at CPU-poll frequency (2 s).
* Local correlation only after the pass — **zero per-process ADB commands**,
  no unbounded caches; each snapshot replaces the previous one (fixed-size).

## N. What CANNOT reliably be provided (stated explicitly in the UI)

* **PID → socket attribution** (fd hidden; netlink denied).
* **Socket → interface association** (no source; never inferred from IPs).
* Per-process realtime byte totals merged with socket state (netstats is
  per-UID cumulative bytes, not sockets).
* Process command line / name from the socket layer.
* Threat-intelligence style enrichment (by M14 scope).

---

## Bottom line

| Capability | Status |
|---|---|
| TCP sockets (IPv4 + IPv6) with endpoints/state/uid | VERIFIED |
| UDP sockets (IPv4 + IPv6), no TCP-style state | VERIFIED |
| UID → installed package mapping | VERIFIED |
| PID attribution | UNAVAILABLE (fd denied) |
| Interface association | UNAVAILABLE |
| `ss`/netlink process info | UNAVAILABLE (netlink denied) |

**Design consequence:** per-process network investigation on this device is
implemented as **UID-attributed socket visibility with package mapping**;
attribution confidence is shown honestly, and the impossibility of
PID-level attribution is documented in the UI ("per-process socket
attribution unavailable at PID granularity").