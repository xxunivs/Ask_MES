FROM vllm/vllm-openai:latest

ENV VLLM_USE_FLASHINFER_SAMPLER=0
ENV MODEL_ID=Qwen/Qwen3.5-9B
ENV SERVED_MODEL_NAME=qwen35-9b
ENV MAX_MODEL_LEN=4096
ENV GPU_MEMORY_UTILIZATION=0.7
ENV PORT=8008

CMD ["sh", "-c", "vllm serve ${MODEL_ID} --host 0.0.0.0 --port ${PORT} --served-model-name ${SERVED_MODEL_NAME} --max-model-len ${MAX_MODEL_LEN} --gpu-memory-utilization ${GPU_MEMORY_UTILIZATION} --enforce-eager --trust-remote-code"]
