#!/usr/bin/env bash
# Sobe o Processamento (:8002) e a Galeria (:8001). Ctrl+C encerra os dois.
set -euo pipefail

cd "$(dirname "$0")/.."

if [ -x .venv/bin/python ]; then
    PY=.venv/bin/python
else
    PY=python3
fi

PIDS=()
encerrar() {
    for pid in ${PIDS[@]+"${PIDS[@]}"}; do
        kill "$pid" 2>/dev/null || true
    done
    wait 2>/dev/null || true
}
trap encerrar EXIT
trap 'exit 130' INT TERM

"$PY" -m uvicorn processing_service.main:app --port 8002 &
PIDS+=($!)

for _ in $(seq 1 50); do
    curl -sf http://localhost:8002/health >/dev/null && break
    sleep 0.2
done

"$PY" -m uvicorn gallery_service.main:app --port 8001 &
PIDS+=($!)

echo "Processamento: http://localhost:8002 | Galeria: http://localhost:8001 (Ctrl+C para parar)"
wait
