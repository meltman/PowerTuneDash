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
