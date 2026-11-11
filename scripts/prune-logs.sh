#!/bin/bash
# Limita a quantidade de registros de execução persistidos em logs/executions
# para evitar crescimento ilimitado como ocorria anteriormente na pasta audit.

LOG_EXEC_DIR="${HOP_PROJECT_FOLDER:-/files/jade-extrator}/logs/executions"
MAX_EXECUTIONS="${HOP_MAX_LOG_EXECUTIONS:-200}"
PRUNE_INTERVAL_SECONDS="${HOP_LOG_PRUNE_INTERVAL:-300}"

mkdir -p "${LOG_EXEC_DIR}" || true

prune_old_executions() {
  if [ -d "${LOG_EXEC_DIR}" ]; then
    # Mantém apenas os MAX_EXECUTIONS diretórios de execução mais recentes
    find "${LOG_EXEC_DIR}" -mindepth 1 -maxdepth 1 -type d -printf '%T@ %p\n' 2>/dev/null \
      | sort -rn \
      | tail -n +"$((MAX_EXECUTIONS + 1))" \
      | cut -d' ' -f2- \
      | while IFS= read -r old_dir; do
          [ -n "${old_dir}" ] && rm -rf "${old_dir}"
        done || true
  fi
}

prune_old_executions

(
  while true; do
    sleep "${PRUNE_INTERVAL_SECONDS}"
    prune_old_executions
  done
) </dev/null >/dev/null 2>&1 &
