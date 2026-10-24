"""
실행 방법 (backend/ 에서, .env 에 DEEPINFRA_API_KEY 필요):
  EMBED_BACKEND=deepinfra EMBED_MODEL=BAAI/bge-m3 CHROMA_PATH=./vector_index_deploy ./venv/bin/python scripts/build_index.py
결과: 배포 이미지에 넣을 벡터 색인
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.retrieval.retriever import init_chroma  # noqa: E402

init_chroma()
