#!/usr/bin/env bash
set -u

usage() {
    cat <<'EOF'
Usage: pt-profile-workload.sh --name NAME --duration SECONDS [options]

Options:
  --interval SECONDS       sample interval, default 1
  --output-dir DIRECTORY   results directory; default ./pt-profile-TIMESTAMP
  --summary-file FILE      copy a completed kpro-workload --summary JSON file
  --help                   show this help

The script samples existing processes only. It never starts/stops PowerTune,
changes CAN settings, or installs packages.
EOF
}

workload_name=""
duration=""
interval=1
output_dir=""
summary_file=""

while (($#)); do
    case "$1" in
        --name) workload_name=${2-}; shift 2 ;;
        --duration) duration=${2-}; shift 2 ;;
        --interval) interval=${2-}; shift 2 ;;
        --output-dir) output_dir=${2-}; shift 2 ;;
        --summary-file) summary_file=${2-}; shift 2 ;;
        --help) usage; exit 0 ;;
        *) echo "pt-profile-workload: unknown option: $1" >&2; usage >&2; exit 2 ;;
    esac
done

if [[ -z "$workload_name" || ! "$duration" =~ ^[1-9][0-9]*$ ||
      ! "$interval" =~ ^[1-9][0-9]*$ ]]; then
    echo "pt-profile-workload: --name, positive integer --duration, and positive integer --interval are required" >&2
    exit 2
fi
if ((duration > 3600)); then
    echo "pt-profile-workload: duration is capped at 3600 seconds" >&2
    exit 2
fi

if [[ -z "$output_dir" ]]; then
    output_dir="pt-profile-$(date -u +%Y%m%dT%H%M%SZ)"
fi
if [[ -e "$output_dir" ]]; then
    echo "pt-profile-workload: output path already exists: $output_dir" >&2
    exit 2
fi
mkdir -p -- "$output_dir"

printf 'workload=%s\nduration_seconds=%s\ninterval_seconds=%s\nstarted_utc=%s\n' \
    "$workload_name" "$duration" "$interval" "$(date -u +%FT%TZ)" \
    > "$output_dir/run-info.txt"

if [[ -n "$summary_file" ]]; then
    if [[ -r "$summary_file" ]]; then
        cp -- "$summary_file" "$output_dir/workload-summary.json"
    else
        echo "Waiting for concurrent workload summary: $summary_file" \
            > "$output_dir/workload-summary.txt"
    fi
else
    echo "No workload summary file supplied; run kpro-workload with --summary and pass it using --summary-file." \
        > "$output_dir/workload-summary.txt"
fi

target_pids=""
for cmdline_file in /proc/[0-9]*/cmdline; do
    [[ -r "$cmdline_file" ]] || continue
    pid=${cmdline_file#/proc/}
    pid=${pid%/cmdline}
    command_line=$(tr '\0' ' ' < "$cmdline_file" 2>/dev/null || true)
    lower_command=${command_line,,}
    case "$lower_command" in
        *powertunedash*|*kpro-powertune-bridge.py*|*kpro-workload.py*)
            if [[ -n "$target_pids" ]]; then
                target_pids+=","
            fi
            target_pids+="$pid"
            ;;
    esac
done

if command -v pidstat >/dev/null 2>&1 && [[ -n "$target_pids" ]]; then
    echo "pidstat=available" >> "$output_dir/run-info.txt"
    pidstat -u -r -w -p "$target_pids" "$interval" "$(( (duration + interval - 1) / interval ))" \
        > "$output_dir/pidstat.txt" 2>&1 &
    pidstat_pid=$!
    trap 'kill "$pidstat_pid" 2>/dev/null || true' EXIT
    trap 'exit 130' INT TERM
elif command -v pidstat >/dev/null 2>&1; then
    echo "pidstat=available; no target processes found at startup" >> "$output_dir/run-info.txt"
else
    echo "pidstat=unavailable; /proc samples will be used" >> "$output_dir/run-info.txt"
fi

clk_tck=$(getconf CLK_TCK 2>/dev/null || echo 100)
printf 'timestamp_utc,workload,role,pid,comm,cpu_percent,rss_kb,threads,voluntary_ctxt_switches,nonvoluntary_ctxt_switches\n' \
    > "$output_dir/process-samples.csv"

declare -A previous_cpu
elapsed=0
sample=0
sample_window=$interval
while :; do
    timestamp=$(date -u +%FT%TZ)
    for cmdline_file in /proc/[0-9]*/cmdline; do
        [[ -r "$cmdline_file" ]] || continue
        pid=${cmdline_file#/proc/}
        pid=${pid%/cmdline}
        command_line=$(tr '\0' ' ' < "$cmdline_file" 2>/dev/null || true)
        lower_command=${command_line,,}
        role=""
        case "$lower_command" in
            *powertunedash*) role="powertunedash" ;;
            *kpro-powertune-bridge.py*) role="bridge" ;;
            *kpro-workload.py*) role="workload" ;;
            *) continue ;;
        esac

        stat_file="/proc/$pid/stat"
        status_file="/proc/$pid/status"
        [[ -r "$stat_file" && -r "$status_file" ]] || continue
        stat_values=$(awk '{sub(/^.*\) /, ""); print $12, $13, $18}' "$stat_file" 2>/dev/null) || continue
        read -r user_ticks system_ticks stat_threads <<< "$stat_values"
        cpu_ticks=$((user_ticks + system_ticks))
        cpu_percent=0
        if [[ -n "${previous_cpu[$pid]+present}" && sample -gt 0 ]]; then
            delta=$((cpu_ticks - previous_cpu[$pid]))
            cpu_percent=$(awk -v d="$delta" -v hz="$clk_tck" -v seconds="$sample_window" \
                'BEGIN { if (seconds > 0) printf "%.2f", (d * 100.0 / hz) / seconds; else print "0.00" }')
        fi
        previous_cpu[$pid]=$cpu_ticks

        status_values=$(awk '
            /^Name:/ { name=$2 }
            /^VmRSS:/ { rss=$2 }
            /^Threads:/ { threads=$2 }
            /^voluntary_ctxt_switches:/ { voluntary=$2 }
            /^nonvoluntary_ctxt_switches:/ { involuntary=$2 }
            END { printf "%s,%s,%s,%s,%s", name, rss, threads, voluntary, involuntary }
        ' "$status_file")
        IFS=, read -r comm rss_kb threads voluntary involuntary <<< "$status_values"
        printf '%s,%s,%s,%s,%s,%s,%s,%s,%s,%s\n' \
            "$timestamp" "$workload_name" "$role" "$pid" "$comm" "$cpu_percent" \
            "${rss_kb:-0}" "${threads:-$stat_threads}" "${voluntary:-0}" "${involuntary:-0}" \
            >> "$output_dir/process-samples.csv"
    done
    ((elapsed >= duration)) && break
    sample_window=$interval
    if ((sample_window > duration - elapsed)); then
        sample_window=$((duration - elapsed))
    fi
    sleep "$sample_window"
    elapsed=$((elapsed + sample_window))
    sample=$((sample + 1))
done

if [[ -n "${pidstat_pid:-}" ]]; then
    kill "$pidstat_pid" 2>/dev/null || true
    wait "$pidstat_pid" || true
    trap - EXIT INT TERM
fi
if [[ -n "$summary_file" && ! -r "$output_dir/workload-summary.json" && -r "$summary_file" ]]; then
    cp -- "$summary_file" "$output_dir/workload-summary.json"
    rm -- "$output_dir/workload-summary.txt"
fi
printf 'finished_utc=%s\n' "$(date -u +%FT%TZ)" >> "$output_dir/run-info.txt"
echo "Results written to $output_dir"
