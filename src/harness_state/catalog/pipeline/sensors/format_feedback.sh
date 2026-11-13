#!/usr/bin/env bash
# format_feedback.sh - transforma falhas de sensores em feedback prescritivo
# e despacha telemetria de execucao/erros para o Elasticsearch central.
#
# Lê automaticamente as configuracoes de:
# 1. Variaveis de ambiente injetadas pelo `harness spec run`
# 2. <modulo>/.harness/config.yaml ou ~/.config/harness/config.yaml
# 3. Arquivo de segredos configurado em secrets.env_file (~/.harness-secrets.env)
#
# Uso: format_feedback.sh <ferramenta> -- <comando> [args...]

set -uo pipefail

TAIL_LINES=20

tool="${1:-}"
shift || true
if [[ "${1:-}" == "--" ]]; then
  shift
fi
if [[ -z "$tool" || $# -eq 0 ]]; then
  echo "usage: format_feedback.sh <tool> -- <command> [args...]" >&2
  exit 2
fi

cmd=("$@")
# O Aider repassa os arquivos modificados como argumentos extras no fim do comando.
# Quando a ferramenta for 'just', mantemos apenas 'just <recipe>' para evitar que o
# just interprete caminhos de arquivos como receitas inexistentes.
if [[ "${1:-}" == "just" && $# -gt 2 ]]; then
  cmd=("$1" "$2")
fi

# Descobre o arquivo de configuracao local (prioridade: env -> projeto -> usuario)
CONFIG_FILE="${HARNESS_CONFIG_FILE:-}"
if [[ -z "$CONFIG_FILE" ]]; then
  if [[ -f ".harness/config.yaml" ]]; then
    CONFIG_FILE=".harness/config.yaml"
  elif [[ -f "$HOME/.config/harness/config.yaml" ]]; then
    CONFIG_FILE="$HOME/.config/harness/config.yaml"
  fi
fi

extract_yaml_value() {
  local key="$1"
  local file="$2"
  if [[ -f "$file" ]]; then
    grep -E "^\s*${key}\s*:" "$file" | head -n 1 | cut -d':' -f2- | sed -E 's/^[[:space:]]*["'\'']?//; s/["'\'']?[[:space:]]*$//'
  fi
}

# Resolve arquivo de segredos a partir da config ou padrao
SECRETS_FILE="${HARNESS_SECRETS_FILE:-}"
if [[ -z "$SECRETS_FILE" && -n "$CONFIG_FILE" ]]; then
  SECRETS_FILE=$(extract_yaml_value "env_file" "$CONFIG_FILE")
fi
SECRETS_FILE="${SECRETS_FILE:-$HOME/.harness-secrets.env}"
SECRETS_FILE="${SECRETS_FILE/#\~/$HOME}"

# Carrega segredos do harness se disponivel
if [[ -z "${ES_TOKEN:-}" && -f "$SECRETS_FILE" ]]; then
  parsed_token=$(grep -E '^\s*(export\s+)?ES_TOKEN=' "$SECRETS_FILE" | head -n 1 | cut -d'=' -f2- | tr -d '"'\'' ')
  if [[ -n "$parsed_token" ]]; then
    export ES_TOKEN="$parsed_token"
  fi
fi

# Resolve endpoints internos, externos e indice a partir do config.yaml
CFG_INTERNAL_ES=""
CFG_EXTERNAL_ES=""
CFG_ES_INDEX=""
if [[ -n "$CONFIG_FILE" ]]; then
  CFG_INTERNAL_ES=$(extract_yaml_value "internal_url" "$CONFIG_FILE")
  CFG_EXTERNAL_ES=$(extract_yaml_value "external_url" "$CONFIG_FILE")
  CFG_ES_INDEX=$(extract_yaml_value "index" "$CONFIG_FILE")
fi

ES_INTERNAL_URL="${ES_INTERNAL_URL:-${CFG_INTERNAL_ES:-}}"
ES_EXTERNAL_URL="${ES_EXTERNAL_URL:-${CFG_EXTERNAL_ES:-}}"
ES_INDEX="${ES_INDEX:-${CFG_ES_INDEX:-harness-sensor-telemetry}}"

# Extrai host e porta do ES_INTERNAL_URL para teste rapido de conectividade TCP
INTERNAL_HOST_PORT=$(echo "$ES_INTERNAL_URL" | sed -E 's|^https?://||; s|/.*$||')
INTERNAL_HOST="${INTERNAL_HOST_PORT%%:*}"
INTERNAL_PORT="${INTERNAL_HOST_PORT##*:}"

if [[ -n "${ES_URL:-}" ]]; then
  ES_ENDPOINT="${ES_URL}"
elif [[ -n "${ES_INTERNAL_URL}" && -n "${INTERNAL_HOST}" && "$INTERNAL_HOST" != "$INTERNAL_PORT" ]] && timeout 0.2 bash -c "echo > /dev/tcp/${INTERNAL_HOST}/${INTERNAL_PORT}" 2>/dev/null; then
  ES_ENDPOINT="${ES_INTERNAL_URL}"
elif [[ -n "${ES_EXTERNAL_URL}" ]]; then
  ES_ENDPOINT="${ES_EXTERNAL_URL}"
else
  ES_ENDPOINT=""
fi

output="$("${cmd[@]}" 2>&1)"
rc=$?

violations=()
broken_rule=""

add_violation() {
  violations+=("$1|$2|$3|$4")
}

re_ruff='^([^:[:space:]]+):([0-9]+):([0-9]+): ([A-Z]+[0-9]+) (.*)$'
re_pyright='^[[:space:]]*(/?[^:[:space:]]+):([0-9]+):([0-9]+) - error: (.*)$'
re_pytest='^FAILED ([^[:space:]]+) - (.*)$'
re_broken='^(.*) BROKEN$'
re_edge='^[[:space:]]*-?[[:space:]]*(.*->.*\(l\.[0-9]+\))$'

fix_lint="Fix the reported rule at the target following .harness/guides/conventions.md."
fix_complexity="Apply the complexipy refactoring suggestion above (guard clauses, continue guards, or module/class-level helper functions — NEVER nested functions) to reduce cognitive complexity below the allowed threshold."
fix_arch="Remove the illegal import and depend on an abstraction allowed by .harness/guides/architecture.md."
fix_test="Fix the code under test (or the test if the spec changed). Never delete or skip tests."
fix_type="Correct the type error at the target. Do not silence it with ignore comments."

while IFS= read -r line; do
  if [[ $line =~ $re_pytest ]]; then
    add_violation "Test Failure" "${BASH_REMATCH[1]}" "${BASH_REMATCH[2]}" "$fix_test"
  elif [[ $line =~ $re_ruff ]]; then
    if [[ "${BASH_REMATCH[5]}" == *"Complexipy suggestion"* || "${BASH_REMATCH[4]}" == CX* ]]; then
      add_violation "Cognitive Complexity" "${BASH_REMATCH[1]}:${BASH_REMATCH[2]}" \
        "${BASH_REMATCH[4]} ${BASH_REMATCH[5]}" "$fix_complexity"
    else
      add_violation "Lint" "${BASH_REMATCH[1]}:${BASH_REMATCH[2]}" \
        "${BASH_REMATCH[4]} ${BASH_REMATCH[5]}" "$fix_lint"
    fi
  elif [[ $line =~ $re_pyright ]]; then
    add_violation "Type Check" "${BASH_REMATCH[1]}:${BASH_REMATCH[2]}" \
      "${BASH_REMATCH[4]}" "$fix_type"
  elif [[ $line =~ $re_broken ]]; then
    broken_rule="${BASH_REMATCH[1]}"
  elif [[ -n "$broken_rule" && $line =~ $re_edge ]]; then
    add_violation "Architectural Boundary" "${BASH_REMATCH[1]}" \
      "$broken_rule (see .harness/guides/architecture.md)" "$fix_arch"
  fi
done <<<"$output"

# Envio assincrono de telemetria para o Elasticsearch (topologia dual)
send_telemetry() {
  local status="$1"
  local primary_type="$2"
  local primary_target="$3"
  local primary_rule="$4"

  if [[ -z "${ES_ENDPOINT:-}" ]]; then
    return 0
  fi

  local is_internal=0
  if [[ -n "${ES_INTERNAL_URL:-}" && "${ES_ENDPOINT}" == "${ES_INTERNAL_URL}" ]]; then
    is_internal=1
  fi

  # Para endpoint externo, o envio requer ES_TOKEN obrigatorio.
  # Para endpoint interno na cloud, permite envio direto mesmo sem token.
  if [[ -n "${ES_TOKEN:-}" || $is_internal -eq 1 ]]; then
    local repo_name
    repo_name=$(basename "$(git rev-parse --show-toplevel 2>/dev/null || pwd)")
    local git_branch
    git_branch=$(git rev-parse --abbrev-ref HEAD 2>/dev/null || echo "unknown")
    local git_commit
    git_commit=$(git rev-parse --short HEAD 2>/dev/null || echo "unknown")
    local timestamp
    timestamp=$(date -u +"%Y-%m-%dT%H:%M:%SZ")

    # Escapa quebras de linha e aspas para JSON valido
    local safe_cmd="${cmd[*]}"
    safe_cmd="${safe_cmd//\\/\\\\}"
    safe_cmd="${safe_cmd//\"/\\\"}"

    local payload
    payload=$(cat <<EOF
{
  "@timestamp": "$timestamp",
  "repository": "$repo_name",
  "branch": "$git_branch",
  "commit": "$git_commit",
  "sensor_tool": "$tool",
  "command": "$safe_cmd",
  "exit_code": $rc,
  "status": "$status",
  "violations_count": ${#violations[@]},
  "primary_violation_type": "$primary_type",
  "primary_target": "$primary_target",
  "primary_rule": "$primary_rule"
}
EOF
)
    local auth_args=()
    if [[ -n "${ES_TOKEN:-}" ]]; then
      auth_args=(-H "Authorization: Bearer ${ES_TOKEN}")
    fi

    # Dispara de forma rapida sem travar o operador
    curl -s -k --max-time 3 -X POST "${ES_ENDPOINT}/${ES_INDEX}/_doc" \
      "${auth_args[@]}" \
      -H "Content-Type: application/json" \
      -d "$payload" >/dev/null 2>&1 &
    telemetry_pid=$!
  fi
}

if ((rc == 0)); then
  send_telemetry "SUCCESS" "None" "None" "None"
  if [[ -n "${telemetry_pid:-}" ]]; then
    wait "$telemetry_pid" 2>/dev/null || true
  fi
  exit 0
fi

if ((${#violations[@]} == 0)); then
  send_telemetry "FAILURE" "Unclassified" "output_tail" "exit_code_$rc"
  echo "[HARNESS SENSOR FEEDBACK]"
  echo "STATUS: REJECTED"
  echo "VIOLATION TYPE: Unclassified"
  echo "TARGET: (see output tail below)"
  echo "RULE: Sensor '$tool' failed with exit code $rc"
  echo "SUGGESTED CORRECTION: Read the output tail and fix the root cause."
  echo "ACTION REQUIRED: Fix the failure before proceeding."
  echo "OUTPUT (last ${TAIL_LINES} lines):"
  tail -n "$TAIL_LINES" <<<"$output"
  if [[ -n "${telemetry_pid:-}" ]]; then
    wait "$telemetry_pid" 2>/dev/null || true
  fi
  exit "$rc"
fi

IFS='|' read -r vtype vtarget vrule vfix <<<"${violations[0]}"
send_telemetry "FAILURE" "$vtype" "$vtarget" "$vrule"

echo "[HARNESS SENSOR FEEDBACK]"
echo "STATUS: REJECTED"
echo "VIOLATION TYPE: $vtype"
echo "TARGET: $vtarget"
echo "RULE: $vrule"
echo "SUGGESTED CORRECTION: $vfix"
echo "ACTION REQUIRED: Fix the violation above before proceeding, then re-run the sensor."
extra=$((${#violations[@]} - 1))
if ((extra > 0)); then
  echo "ADDITIONAL VIOLATIONS: $extra"
fi

if [[ -n "${telemetry_pid:-}" ]]; then
  wait "$telemetry_pid" 2>/dev/null || true
fi
exit "$rc"
