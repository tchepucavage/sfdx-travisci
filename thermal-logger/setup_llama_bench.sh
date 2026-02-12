#!/bin/bash
# Setup llama-bench (llama.cpp) for GPU thermal testing.
# Uses Vulkan pre-built binary — no CUDA toolkit required.
# Run on the target Linux server (e.g. chain-weave-dev-server).

set -e

LLAMA_VERSION="b7999"
INSTALL_DIR="${INSTALL_DIR:-$HOME/llama-bench-setup}"
MODEL_DIR="${INSTALL_DIR}/models"

echo "==> Installing to ${INSTALL_DIR}"
mkdir -p "${INSTALL_DIR}" "${MODEL_DIR}"
cd "${INSTALL_DIR}"

# 1. Download and extract llama.cpp Vulkan build (no CUDA needed)
if [[ ! -f "llama-${LLAMA_VERSION}/llama-bench" ]]; then
  echo "==> Downloading llama.cpp Vulkan build..."
  wget -q --show-progress \
    "https://github.com/ggml-org/llama.cpp/releases/download/${LLAMA_VERSION}/llama-${LLAMA_VERSION}-bin-ubuntu-vulkan-x64.tar.gz" \
    -O llama-vulkan.tar.gz
  tar -xzf llama-vulkan.tar.gz
  rm llama-vulkan.tar.gz
  echo "    Done."
else
  echo "==> llama-bench already present, skipping download."
fi

# 2. Standard workload: TinyLlama 1.1B (~670 MB) — sustained inference load
STANDARD_MODEL="tinyllama-1.1b-chat-v1.0.Q4_K_M.gguf"
if [[ ! -f "${MODEL_DIR}/${STANDARD_MODEL}" ]]; then
  echo "==> Downloading standard model: TinyLlama 1.1B Q4_K_M (~670 MB)..."
  wget -q --show-progress \
    "https://huggingface.co/TheBloke/TinyLlama-1.1B-Chat-v1.0-GGUF/resolve/main/${STANDARD_MODEL}" \
    -O "${MODEL_DIR}/${STANDARD_MODEL}"
  echo "    Done."
else
  echo "==> Standard model already present, skipping."
fi

# 3. Heavy workload: Qwen2.5-3B (~2.1 GB) — longer runs, higher GPU stress
HEAVY_MODEL="qwen2.5-3b-instruct-q4_k_m.gguf"
if [[ ! -f "${MODEL_DIR}/${HEAVY_MODEL}" ]]; then
  echo "==> Downloading heavy model: Qwen2.5-3B Q4_K_M (~2.1 GB)..."
  wget -q --show-progress \
    "https://huggingface.co/Qwen/Qwen2.5-3B-Instruct-GGUF/resolve/main/${HEAVY_MODEL}" \
    -O "${MODEL_DIR}/${HEAVY_MODEL}"
  echo "    Done."
else
  echo "==> Heavy model already present, skipping."
fi

echo ""
echo "==> Setup complete."
echo ""
echo "Standard workload (1.1B, ~30–60 sec per run):"
echo "  ./run_llama_bench_thermal.sh 15 standard"
echo ""
echo "Heavy workload (3B, ~2–4 min per run, more sustained):"
echo "  ./run_llama_bench_thermal.sh 15 heavy"
echo ""
echo "Start thermal logger first: ./thermal_logger.py -i 1 -o thermal_log.csv"
