#!/usr/bin/env bash
# benchmark_llm.sh — Benchmark LLM inference speed.
#
# Usage:
#   ./benchmark_llm.sh m1
#   ./benchmark_llm.sh station

set -euo pipefail

MACHINE="${1:?usage: $0 {m1|station}}"

if [[ "$MACHINE" == "m1" ]]; then
  echo "==> Benchmarking Ollama on M1"
  echo "    Model: unsloth/gemma-4-e2b-it-GGUF:Q4_K_XL"

  PAYLOAD='{"model":"hermes-edge","prompt":"Write a 200-word essay about local-first AI.","stream":false,"options":{"num_predict":200}}'
  START=$(date +%s.%N)
  RESPONSE=$(curl -s http://127.0.0.1:11434/api/generate -d "$PAYLOAD")
  END=$(date +%s.%N)

  ELAPSED=$(echo "$END - $START" | bc)
  TOKENS=$(echo "$RESPONSE" | jq -r '.eval_count // 0')
  TPS=$(echo "scale=2; $TOKENS / $ELAPSED" | bc)

  echo "    Elapsed: ${ELAPSED}s"
  echo "    Tokens:  ${TOKENS}"
  echo "    TPS:     ${TPS}"

elif [[ "$MACHINE" == "station" ]]; then
  echo "==> Benchmarking llama-server on workstation"
  echo "    Model: Qwen3.6-27B-PRISM-PRO-DQ.Q4_K_M"

  PAYLOAD='{"model":"Qwen3.6-27B-PRISM-PRO-DQ","messages":[{"role":"user","content":"Write a 500-word essay about local-first AI."}],"stream":false,"max_tokens":500}'
  START=$(date +%s.%N)
  RESPONSE=$(curl -s http://127.0.0.1:8080/v1/chat/completions -H "Content-Type: application/json" -d "$PAYLOAD")
  END=$(date +%s.%N)

  ELAPSED=$(echo "$END - $START" | bc)
  TOKENS=$(echo "$RESPONSE" | jq -r '.usage.completion_tokens // 0')
  TPS=$(echo "scale=2; $TOKENS / $ELAPSED" | bc)

  echo "    Elapsed: ${ELAPSED}s"
  echo "    Tokens:  ${TOKENS}"
  echo "    TPS:     ${TPS}"

else
  echo "Unknown machine: $MACHINE" >&2
  exit 1
fi
