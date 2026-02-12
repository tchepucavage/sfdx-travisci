#!/bin/bash
# Run llama-bench for sustained GPU load (thermal testing).
# Usage: ./run_llama_bench_thermal.sh [duration_minutes] [workload]
#   workload: standard (1.1B, default) | heavy (3B)
# Default: 15 minutes, standard workload

DURATION_MIN="${1:-15}"
WORKLOAD="${2:-standard}"
DURATION_SEC=$((DURATION_MIN * 60))

INSTALL_DIR="${INSTALL_DIR:-$HOME/llama-bench-setup}"
BENCH_DIR="${INSTALL_DIR}/llama-b7999"

case "${WORKLOAD}" in
  standard)
    MODEL_PATH="${INSTALL_DIR}/models/tinyllama-1.1b-chat-v1.0.Q4_K_M.gguf"
    # 1.1B: -p 512 -n 512 -r 3 = ~30–60 sec per invocation
    BENCH_ARGS="-p 512 -n 512 -r 3"
    ;;
  heavy)
    MODEL_PATH="${INSTALL_DIR}/models/qwen2.5-3b-instruct-q4_k_m.gguf"
    # 3B: -p 512 -n 1024 -r 2 = ~2–4 min per invocation, sustained load
    BENCH_ARGS="-p 512 -n 1024 -r 2"
    ;;
  *)
    echo "Error: workload must be 'standard' or 'heavy'" >&2
    echo "  standard = TinyLlama 1.1B, faster iterations" >&2
    echo "  heavy    = Qwen2.5-3B, longer sustained runs per iteration" >&2
    exit 1
    ;;
esac

if [[ ! -f "${MODEL_PATH}" ]]; then
  echo "Error: Model not found. Run setup_llama_bench.sh first." >&2
  exit 1
fi

if [[ ! -x "${BENCH_DIR}/llama-bench" ]]; then
  echo "Error: llama-bench not found. Run setup_llama_bench.sh first." >&2
  exit 1
fi

cd "${BENCH_DIR}"

echo "Workload: ${WORKLOAD}"
echo "Duration: ${DURATION_MIN} minutes"
echo "Model: $(basename ${MODEL_PATH})"
echo ""
echo "Start thermal logger in another terminal: ./thermal_logger.py -i 1 -o thermal_log.csv"
echo ""

end=$((SECONDS + DURATION_SEC))
run=0

while [ $SECONDS -lt $end ]; do
  run=$((run + 1))
  echo "[$(date +%H:%M:%S)] Run ${run}"
  ./llama-bench -m "${MODEL_PATH}" ${BENCH_ARGS} -ngl 99
done

echo ""
echo "Done. ${run} benchmark runs completed."
