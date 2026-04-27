#!/bin/bash
#
# ReID HEF Benchmark Script
# Measures FPS (throughput) and Latency for OSNET & RepVGG ReID models
# Outputs results as Confluence Wiki Markup tables
#

HEF_DIR="/usr/local/hailo/resources/models/hailo8"
TIME_TO_RUN=30
BATCH_SIZES=(1 2 4 8 16)

# Auto-detect ReID HEF files
HEFS=()
HEF_NAMES=()
for f in "$HEF_DIR"/*osnet*.hef "$HEF_DIR"/*repvgg*reid*.hef; do
    if [[ -f "$f" ]]; then
        HEFS+=("$f")
        HEF_NAMES+=("$(basename "$f" .hef)")
    fi
done

if [[ ${#HEFS[@]} -eq 0 ]]; then
    echo "ERROR: No ReID HEF files found in $HEF_DIR"
    echo "Available HEFs:"
    ls "$HEF_DIR"/*.hef 2>/dev/null
    exit 1
fi

echo "Found ${#HEFS[@]} ReID HEF(s):"
for h in "${HEFS[@]}"; do echo "  - $h"; done
echo ""

# Output file
RESULTS_FILE="reid_benchmark_results_$(date +%Y%m%d_%H%M%S).txt"

# ── Helpers: extract values from hailortcli output ──
# Summary format:  FPS     (hw_only)                 = 177.864
extract_fps_hw_only() {
    grep 'hw_only' | grep -oP '=\s*\K[0-9.]+'
}

# Summary format:  (streaming)               = 177.865
extract_fps_streaming() {
    grep 'streaming' | grep -oP '=\s*\K[0-9.]+'
}

# Summary format:  Latency (hw)                      = 4.86149 ms
extract_hw_latency() {
    grep 'Latency (hw)' | grep -oP '=\s*\K[0-9.]+'
}

# Run output format:  Overall Latency: 5.58 ms
extract_overall_latency() {
    grep 'Overall Latency' | grep -oP ':\s*\K[0-9.]+'
}

# ── Run benchmarks ──
declare -A FPS_HW_RESULTS
declare -A FPS_STREAM_RESULTS
declare -A HW_LAT_RESULTS
declare -A OVERALL_LAT_RESULTS

total=$((${#HEFS[@]} * ${#BATCH_SIZES[@]}))
current=0

for i in "${!HEFS[@]}"; do
    hef="${HEFS[$i]}"
    name="${HEF_NAMES[$i]}"

    for bs in "${BATCH_SIZES[@]}"; do
        current=$((current + 1))
        echo "[$current/$total] Benchmarking $name | batch_size=$bs ..."

        # FPS + HW Latency benchmark
        bench_output=$(hailortcli benchmark "$hef" --batch-size "$bs" --time-to-run "$TIME_TO_RUN" 2>&1)
        fps_hw=$(echo "$bench_output" | extract_fps_hw_only)
        fps_stream=$(echo "$bench_output" | extract_fps_streaming)
        hw_lat=$(echo "$bench_output" | extract_hw_latency)
        FPS_HW_RESULTS["${name}_${bs}"]="${fps_hw:-N/A}"
        FPS_STREAM_RESULTS["${name}_${bs}"]="${fps_stream:-N/A}"
        HW_LAT_RESULTS["${name}_${bs}"]="${hw_lat:-N/A}"

        # Overall Latency
        run_output=$(hailortcli run "$hef" --batch-size "$bs" --time-to-run "$TIME_TO_RUN" \
            --measure-latency --measure-overall-latency 2>&1)
        overall_lat=$(echo "$run_output" | extract_overall_latency)
        OVERALL_LAT_RESULTS["${name}_${bs}"]="${overall_lat:-N/A}"

        echo "  -> FPS(hw): ${FPS_HW_RESULTS["${name}_${bs}"]} | FPS(stream): ${FPS_STREAM_RESULTS["${name}_${bs}"]} | HW Lat: ${HW_LAT_RESULTS["${name}_${bs}"]} ms | Overall Lat: ${OVERALL_LAT_RESULTS["${name}_${bs}"]} ms"
    done
done

echo ""
echo "=============================="
echo " Benchmark complete!"
echo "=============================="
echo ""

# ── Generate Confluence Wiki Markup ──
{
    # ── FPS Table (HW-only) ──
    echo "h2. ReID FPS Benchmark - HW Only"
    echo ""
    header="|| Model ||"
    for bs in "${BATCH_SIZES[@]}"; do header+=" Batch $bs ||"; done
    echo "$header"
    for i in "${!HEFS[@]}"; do
        name="${HEF_NAMES[$i]}"
        row="| $name |"
        for bs in "${BATCH_SIZES[@]}"; do row+=" ${FPS_HW_RESULTS["${name}_${bs}"]} |"; done
        echo "$row"
    done

    echo ""

    # ── FPS Table (Streaming) ──
    echo "h2. ReID FPS Benchmark - Streaming"
    echo ""
    header="|| Model ||"
    for bs in "${BATCH_SIZES[@]}"; do header+=" Batch $bs ||"; done
    echo "$header"
    for i in "${!HEFS[@]}"; do
        name="${HEF_NAMES[$i]}"
        row="| $name |"
        for bs in "${BATCH_SIZES[@]}"; do row+=" ${FPS_STREAM_RESULTS["${name}_${bs}"]} |"; done
        echo "$row"
    done

    echo ""

    # ── HW Latency Table ──
    echo "h2. ReID HW Latency (ms)"
    echo ""
    header="|| Model ||"
    for bs in "${BATCH_SIZES[@]}"; do header+=" Batch $bs ||"; done
    echo "$header"
    for i in "${!HEFS[@]}"; do
        name="${HEF_NAMES[$i]}"
        row="| $name |"
        for bs in "${BATCH_SIZES[@]}"; do row+=" ${HW_LAT_RESULTS["${name}_${bs}"]} |"; done
        echo "$row"
    done

    echo ""

    # ── Overall Latency Table ──
    echo "h2. ReID Overall Latency (ms)"
    echo ""
    header="|| Model ||"
    for bs in "${BATCH_SIZES[@]}"; do header+=" Batch $bs ||"; done
    echo "$header"
    for i in "${!HEFS[@]}"; do
        name="${HEF_NAMES[$i]}"
        row="| $name |"
        for bs in "${BATCH_SIZES[@]}"; do row+=" ${OVERALL_LAT_RESULTS["${name}_${bs}"]} |"; done
        echo "$row"
    done

    echo ""
    echo "h2. Test Configuration"
    echo "* *Time per run:* ${TIME_TO_RUN}s"
    echo "* *Batch sizes:* ${BATCH_SIZES[*]}"
    echo "* *HEF directory:* ${HEF_DIR}"
    echo "* *Date:* $(date '+%Y-%m-%d %H:%M')"
    echo "* *Device:* $(hailortcli fw-control identify 2>/dev/null | head -3 || echo 'N/A')"

} | tee "$RESULTS_FILE"

echo ""
echo "Results saved to: $RESULTS_FILE"
echo "Copy the content above directly into Confluence (Wiki Markup mode)."