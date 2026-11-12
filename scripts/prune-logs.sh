#!/bin/bash
# Limita a quantidade de registros de execução persistidos em logs/executions
# para evitar crescimento ilimitado como ocorria anteriormente na pasta audit.

LOG_EXEC_DIR="${1:-${HOP_PROJECT_FOLDER:-/files/jade-extrator}/logs/executions}"
MAX_EXECUTIONS="${2:-${HOP_MAX_LOG_EXECUTIONS:-10000}}"
PRUNE_INTERVAL_SECONDS="${HOP_LOG_PRUNE_INTERVAL:-300}"
RUN_ONCE="${3:-}"

mkdir -p "${LOG_EXEC_DIR}" || true

prune_old_executions() {
  if [ -d "${LOG_EXEC_DIR}" ]; then
    # Remove dumps binários de linhas de resultado de actions (*-data.json),
    # preservando apenas execution.json, state.json (métricas por transform) e *-log.txt.
    find "${LOG_EXEC_DIR}" -mindepth 2 -maxdepth 2 -type f -name '*-data.json' -delete 2>/dev/null || true

    # Mantém apenas os MAX_EXECUTIONS diretórios de execução mais recentes
    # (usa ls -1t para compatibilidade com BusyBox/Alpine na imagem apache/hop).
    ls -1t "${LOG_EXEC_DIR}" 2>/dev/null \
      | tail -n +"$((MAX_EXECUTIONS + 1))" \
      | while IFS= read -r old_entry; do
          [ -n "${old_entry}" ] && rm -rf "${LOG_EXEC_DIR}/${old_entry}"
        done || true
  fi
}

prune_old_executions

if [ "${RUN_ONCE}" != "--once" ]; then
  (
    while true; do
      sleep "${PRUNE_INTERVAL_SECONDS}"
      prune_old_executions
    done
  ) </dev/null >/dev/null 2>&1 &
fi
