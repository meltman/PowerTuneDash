# PowerTune workload performance profiling

This procedure compares synthetic integration workloads without changing
PowerTuneDash, dashboard content, CAN configuration, or system configuration.
It uses the workload utility's deterministic scenario schedule, the bridge's
bounded summary, and process metrics from `/proc`. It does not transmit CAN
unless the explicitly documented `transmit` mode is chosen.

## Questions and comparisons

Keep the same device, display, application configuration, sample duration,
and scenario rate between runs. Repeat each case and retain the scenario JSON
and summary with the sample data.

| Comparison | What it helps isolate |
|---|---|
| P0 vs P2 | Application baseline versus CAN processing and initial mapped UDP updates; P2 repeats are suppressed |
| P1 vs P2 | Decoder/bridge work versus mapped PowerTune publication work |
| P2 vs P3 | Cost associated with actual material value changes compared with identical values |
| P3 vs P4 | Incremental cost of coordinated multi-signal activity |
| P4 vs P5 | Bounded stress behavior and scaling |
| P2 vs P6 | Repeated/sub-threshold bus traffic versus material display updates |

The central question is whether PowerTune incurs expensive UI work merely
because integration traffic arrived, or primarily when a displayed value
materially changes. Compare bridge frame counts, publisher suppression,
UDP counts, and PowerTune process CPU/context-switch samples together; do
not infer rendering cost from a single CPU measurement.

## Software-only workload runs

Use the same scenario for software replay, export, and physical transmit.
Start PowerTune normally for comparisons that include its processing, then
run one bounded case at a time:

```sh
python3 tools/kpro-workload.py inspect --scenario tests/fixtures/hondata/no-telemetry.json
python3 tools/kpro-workload.py replay --scenario tests/fixtures/hondata/constant-mapped.json --summary > /tmp/P2-summary.json
python3 tools/kpro-workload.py replay --scenario tests/fixtures/hondata/unmapped-decode.json --summary --no-udp > /tmp/P1-summary.json
python3 tools/kpro-workload.py replay --scenario tests/fixtures/hondata/slow-change.json --summary > /tmp/P3-summary.json
python3 tools/kpro-workload.py replay --scenario tests/fixtures/hondata/acceleration-workload.json --summary > /tmp/P4-summary.json
python3 tools/kpro-workload.py replay --scenario tests/fixtures/hondata/maximum-activity.json --summary > /tmp/P5-summary.json
python3 tools/kpro-workload.py replay --scenario tests/fixtures/hondata/display-static-noisy.json --summary > /tmp/P6-summary.json
```

Use `--no-udp` when PowerTune is not the subject of that run. To include
PowerTune, let the local records reach `127.0.0.1:45454`. P0 is an application
baseline with the bridge/workload stopped and no telemetry; the P0 fixture
can also verify that the generator itself emits zero frames.

For a direct UDP control path, compare a mapped workload replay with
`pt-udp-sim`, which bypasses Waveshare, CAN receive, and K-Pro decoding:

```sh
python3 tools/powertune-udp-sim.py --scenario tests/fixtures/udp/direct-p2-control.json
python3 tools/kpro-workload.py replay --scenario tests/fixtures/hondata/slow-change.json --speed 1 --summary
python3 tools/powertune-udp-sim.py --scenario tests/fixtures/udp/direct-p3-profile-control.json
python3 tools/kpro-workload.py replay --scenario tests/fixtures/hondata/acceleration-workload.json --speed 1 --summary
python3 tools/powertune-udp-sim.py --scenario tests/fixtures/udp/direct-p4-acceleration-control.json
```

The paired paths are:

```text
synthetic K-Pro CAN -> decoder/publisher -> PowerTune UDP -> PowerTune
direct pt-udp-sim -----------------------> PowerTune UDP -> PowerTune
```

This comparison helps separate physical CAN/Waveshare, SocketCAN receive,
decoder, UDP publisher, and PowerTune costs. Software replay has no physical
Waveshare or CAN-bus cost. The P2 direct fixture sends the same one-time
values as `steady-cruise.json`. The P3 and P4 direct controls are generated
from the mapped trajectories in `slow-change.json` and
`acceleration-workload.json`, respectively. They contain the same PowerTune
identifier/value events at the source frame timestamps and run for the same
scenario duration. Regenerate, rather than hand-edit, them with:

```sh
python3 tools/kpro-workload.py udp-control \
  --scenario tests/fixtures/hondata/slow-change.json \
  --output tests/fixtures/udp/direct-p3-profile-control.json
python3 tools/kpro-workload.py udp-control \
  --scenario tests/fixtures/hondata/acceleration-workload.json \
  --output tests/fixtures/udp/direct-p4-acceleration-control.json
```

Run each case separately with the same PowerTune state and sample duration.
`--speed 1` preserves the K-Pro scenario's frame/publication cadence; direct
event controls use their absolute offsets and preserve the full scenario
duration. Tests compare generated direct event sequences and timestamps
against the corresponding K-Pro decoder/publisher trajectories. The former
one-second `direct-p3-rpm-control.json` was removed; it duplicated a
hand-authored trajectory and was not a profiling-matched control. A one-shot
direct sanity check is also:

```sh
pt-udp-sim --signal rpm --value 2500
pt-udp-sim --signal rpm --min 800 --max 8000 --step 200 --interval-ms 100 --bounce
```

## Device 0 process sampling

Run the bounded workload/bridge separately, then sample existing PowerTune,
bridge, and workload processes:

```sh
python3 tools/kpro-workload.py replay \
  --scenario tests/fixtures/hondata/constant-mapped.json --summary \
  > /tmp/P2-summary.json
bash tools/pt-profile-workload.sh --name P2 --duration 30 --interval 1 \
  --summary-file /tmp/P2-summary.json --output-dir /tmp/pt-profile-P2
```

For concurrent process sampling, start the workload in another terminal
before starting the profiler. The script locates processes by command line,
records UTC timestamped CPU%, RSS, thread count, and voluntary/involuntary
context switches from `/proc`, and uses `pidstat` when installed. It falls
back to `/proc` when `pidstat` is unavailable. Sampling is capped at one hour,
does not install packages, and never starts/stops PowerTune or configures CAN.
Use a new output directory for each run; the script refuses an existing path.
Pass the workload's `--summary` output with `--summary-file` to keep its
generated/decoded/UDP counts with the process samples.

These process metrics do not measure GPU utilization, compositor work,
frame-time, display latency, or energy use. A CPU delta cannot establish the
GPU rendering cost. Use separate target-appropriate instrumentation for
those questions, and treat synthetic performance as a workload comparison,
not evidence of actual K-Pro/vehicle performance.

## Physical CAN caution

`kpro-workload transmit` intentionally transmits synthetic frames through the
Waveshare adapter. It requires a properly terminated bench and explicit
device selection when discovery is ambiguous. It must not be used on a
connected ECU or vehicle as part of these performance comparisons. This
change does not run physical transmission, alter CAN settings, or validate
actual K-Pro timing.

## Changing-value CPU investigation (P0/P2/P3/P4)

This section records measured evidence, then source-trace inference, then
hypotheses. Only the first is established fact.

### Measured evidence (Device 0)

Canonical benchmark dashboard, SHA-256
`6f227adba4e1ee11c1c55d48e0ef17fd5b585fe79d508e3057561239ad25ae7a`
(`performance-reference-v1.txt`; five round gauges: RPM, Speed, ECT, TPS, MAP).

| Phase | Workload | PowerTune CPU |
|-------|----------|---------------|
| P0 | no telemetry | 8.53% |
| P2 | constant realtime telemetry | 8.57% |
| P3 | K-Pro path, RPM changing | 13.70% |
| P3 | matched direct UDP | 14.20% |
| P4 | K-Pro path, acceleration | 20.80% |
| P4 | matched direct UDP | 21.00% |

Conclusions the data supports: unchanged continuous telemetry costs about the
same as idle; the K-Pro/CAN path adds negligible PowerTune-side cost versus
direct UDP; the cost appears when displayed property values change.

### Source trace (static reading, not yet measured)

1. `udpreceiver::processPendingDatagrams()` builds a `QString` per datagram,
   splits on `,`, then dispatches via a large `switch` (identifiers 179 RPM,
   199 speed, 221 ECT, 210 TPS, 155 MAP).
2. `DashBoard::setrpm / setSpeed / setWatertemp / setTPS / setMAP` update the
   value and emit the property's NOTIFY signal. All but `setMAP` return early
   when the value is unchanged; `setMAP` emits unconditionally (affects MAP
   only, and the UDP records for MAP are the same count as the other gauges in
   the P4 fixture).
3. `RoundGauge.qml` rebinds `gauge.value` to `Dashboard[mainvaluename]` after
   its intro animation. Each integer-or-fractional change of `gauge.value`
   causes:
   - `CircularGauge.onValueChanged` -> `warn()` (colour/boolean property
     updates; no signal on identical assignment);
   - `needletrail` (a full-gauge `Canvas`, `onValueChanged: requestPaint()`):
     software 2D repaint using a four-stop radial gradient and a wide arc
     stroke, then a texture upload; it repaints when the integer part of the
     value changes;
   - re-evaluation of every tick, minor-tick and label delegate colour binding
     (`styleData.value <= gauge.value ? active : inactive`).
4. Other `Dashboard` signal consumers: `Settings/main.qml` (`onRpmChanged`,
   `onWatertempChanged` threshold checks) and `Gauges/WarningLoader.qml`
   (`onRpmChanged`, `onWatertempChanged`, ...), each a short JavaScript handler.

Fan-out points: one Dashboard NOTIFY signal -> gauge binding, warning
Connections, `main.qml` Connections; one gauge value change -> Canvas repaint +
tick/label delegate bindings + `warn()`.

### Inference (not measured)

Excess CPU over P2 is about 5 points for about 5 RPM changes/s (P3) and about
12.4 points for about 15.7 gauge changes/s (P4): roughly 0.8-1.1 CPU-percentage
points per gauge-value change per second, linear in change rate. That
linearity is consistent with a fixed per-change repaint cost, such as the
`needletrail` Canvas repaint plus scene-graph update, rather than with
receive/decode cost (which the direct-UDP and K-Pro runs show is negligible).
It does not identify which stage dominates. The harness reports
percent-of-one-core style values; confirm against `run-info.txt` before
converting to milliseconds.

### Instrumentation (opt-in, default off)

`ptprofile.h/.cpp` add counters that only run when PowerTune is started with
`PT_PROFILE=1` (optional `PT_PROFILE_INTERVAL_MS`, 1000-60000, default 5000).
Without the variable each probe is one relaxed atomic load; no timer is
created and no QML counter runs (`PTProfile.enabled` is false). Probes only
count and time; they do not change values, appearance, animation, UDP handling
or publication rates. Do not leave profiling enabled in production images.

Example, for a one-off run (for instance a systemd drop-in with
`Environment=PT_PROFILE=1`, removed afterwards):

```sh
PT_PROFILE=1 PT_PROFILE_INTERVAL_MS=5000 <normal PowerTune start>
```

Each interval logs three lines (visible in the PowerTune log):

- `INFO PowerTune profile: interval_ms=... process_cpu_pct=... threads_cpu_pct="name=pct,..."`
  - per-thread CPU from `/proc/self/task/*/stat`. The split between the main
    (GUI) thread and the render thread is the most useful single discriminator:
    a large GUI-thread share points at QML/JS/Canvas painting; a large render
    thread share points at scene-graph/GL.
- `INFO PowerTune profile counters: name=delta ...` with:
  - `udp.datagrams`, `udp.records`, `udp.id.{155,179,199,210,221}`
  - `dash.<prop>.setter` and `dash.<prop>.emit` for rpm, speed, Watertemp,
    TPS, MAP (setter minus emit = suppressed duplicates)
  - `gauge.valueChanged.<name>` (QML-facing value changes per gauge),
    `gauge.needletrail.requestPaint`, `gauge.needletrail.onPaint=N(avg_us=...)`
  - `qml.main.on{Rpm,Watertemp}Changed`, `qml.warningloader.on{Rpm,Watertemp}Changed`
  - `timer.calculations.25ms`, `timer.networkmanager.refresh` (idle work)
  - `frame.sync`, `frame.render`, `frame.swapped`
  - one-time `gauge.delegates.{majortick,minortick,label}` instantiation counts
- one-time `INFO PowerTune profile fanout ...` with the receiver count on each
  of the five NOTIFY signals (best effort; includes QML endpoints).

Run P0, P2 and P4 (direct UDP is sufficient) once each with profiling on and
compare: `gauge.needletrail.onPaint` count x avg_us versus total GUI-thread
CPU gives the Canvas share directly; `frame.*` rates show whether changes are
coalesced into frames; the same counters in P0 show recurring idle work.
Instrumentation itself has a small cost, so compare instrumented runs with
instrumented runs.

### Recurring idle work (P0 candidates, hypotheses)

Not yet attributed; each needs the per-thread split and counters above:

- render-loop activity and swap on eglfs (`frame.*` in P0);
- `QtSensors` sensors started at launch, if enabled;
- `NetworkManagerClient` refresh timer (driven by D-Bus signals), GPS/serial
  reconnect timers, status updates;
- the 25 ms `calculations` timer (believed not to run unless Connect/odometer
  start is invoked; the `timer.calculations.25ms` counter will confirm);
- QML Connections and hidden components on `Settings/main.qml`;
- log writes.

Do not combine an idle-cost change with a changing-value change unless the
counters show a shared root cause.

### Ranked optimization opportunities (hypotheses; none applied)

| Rank | Candidate | Expected benefit | Behavioral risk |
|------|-----------|------------------|-----------------|
| 1 | Cheaper or conditional `needletrail` repaint (only when trail is enabled, coarser repaint threshold, or a non-Canvas item) | highest if Canvas time dominates | medium: affects trail appearance |
| 2 | Avoid per-change re-evaluation of tick/label colour bindings (state-change only when crossing a tick) | moderate | low if visually identical |
| 3 | Coalesce Dashboard updates per frame | moderate | medium: changes interpolation/latency |
| 4 | Merge redundant per-event JS handlers (`main.qml`, `WarningLoader`) | small | low |
| 5 | Dedupe in `setMAP` | small, MAP only | low |
| 6 | Idle work (after P0 attribution) | up to ~8.5 points | depends on source |

Smallest first Device 0 A/B candidate: with profiling data in hand, run P4
direct with the `needletrail` repaint disabled behind a temporary local build
flag (diagnostic only, not for release) to isolate the Canvas share of the
12.4-point increase before designing any appearance-preserving replacement.

## Diagnostic A/B switches (Canvas vs tick/label bindings)

### Device 0 evidence that motivated the switches

Build `PowerTune i.MX8 Appliance 2026.11.05`, revision `6662850`, canonical
dashboard SHA-256 `6f227adba4e1ee11c1c55d48e0ef17fd5b585fe79d508e3057561239ad25ae7a`,
matched direct-UDP P4. Instrumented full active intervals:

| Metric | Interval 1 | Interval 2 |
|--------|-----------|-----------|
| process CPU | 22.4% | 18.0% |
| GUI thread | 16.2% | 13.2% |
| QSGRenderThread | 6.0% | 4.8% |

Per interval: 139 UDP records, 139 visible gauge changes, 139 needletrail
requests and paints, 71 scene renders and swaps, 142 frame syncs. Measured
`needletrail.onPaint` callback time: 78 paints at 420 us and 61 at 438 us, about
59.5 ms per 10 s (about 0.6% of one core). The Canvas JavaScript body alone
therefore does not explain the roughly 12-point P0 to P4 increase. Remaining
candidates: Canvas texture invalidation/upload and scene-graph work (not in
`onPaint`), and tick/label binding fan-out. These switches separate them.

### Switches (environment, default off, diagnostic only)

| Variable | Effect |
|----------|--------|
| `PT_PROFILE_DISABLE_NEEDLETRAIL=1` | `needletrail` skips `requestPaint()` on value change. Gauge values, needle, ticks, labels and telemetry are unchanged. The trail keeps whatever it last painted (initial paint only). |
| `PT_PROFILE_DISABLE_DYNAMIC_TICK_COLORS=1` | tick, minor-tick and label colour bindings no longer depend on `gauge.value`, so they are not re-evaluated on value change; they stay at their inactive colour. Needletrail and needle motion are unchanged. |
| `PT_PROFILE_DISABLE_BOTH=1` | both of the above (or set the two switches together). |

The switches work without `PT_PROFILE=1`, but use `PT_PROFILE=1` to see counters.
When any switch is active a `WARN PowerTune diagnostic switches active` line is
logged. They do not touch UDP handling, Dashboard setters, update rate,
interpolation, geometry, dashboard serialization or the number of QML
components; appearance differs only as described (trail not redrawn, ticks and
labels shown inactive). Never enable them in production images.

### Added counters (with `PT_PROFILE=1`)

- `gauge.valueChanged.<name>` - gauge value change
- `gauge.needletrail.requestPaint` - Canvas request issued
- `gauge.needletrail.suppressed` - request skipped by the switch
- `gauge.needletrail.onPaint` - Canvas callback (count, `avg_us`)
- `frame.render`, `frame.swapped`, `frame.sync` - scene render, swap, sync
- `gauge.colorEval.majortick`, `.minortick`, `.label` - dynamic colour
  evaluations (aggregate counts; each is an extra C++ call per evaluation, so
  compare instrumented runs with instrumented runs only)

### A/B procedure

Same build, same dashboard SHA, same P4 direct-UDP workload, same duration, a
fresh PowerTune start for each case, profiling on:

| Case | Environment |
|------|-------------|
| A normal | `PT_PROFILE=1` |
| B needletrail disabled | `PT_PROFILE=1 PT_PROFILE_DISABLE_NEEDLETRAIL=1` |
| C dynamic colours disabled | `PT_PROFILE=1 PT_PROFILE_DISABLE_DYNAMIC_TICK_COLORS=1` |
| D both disabled | `PT_PROFILE=1 PT_PROFILE_DISABLE_BOTH=1` |

Record process CPU, GUI-thread and QSGRenderThread CPU, and the counters for
full active intervals; also run the external `pt-profile-workload.sh` CPU
sampling. Repeat each case at least twice.

### Interpretation

- B clearly lowers GUI/render CPU despite the small `onPaint` time: Canvas
  texture invalidation/upload and re-render is expensive.
- C clearly lowers CPU: tick/label binding fan-out is expensive
  (`gauge.colorEval.*` counts show the evaluation volume).
- D substantially better than either alone: both paths contribute.
- None materially reduces CPU: investigate needle/transform scene-graph
  updates and frame scheduling (`frame.sync` is about twice `frame.render`
  above, so look at why syncs occur without renders).

No production optimization is made until this matrix is measured.
