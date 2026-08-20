#!/bin/sh

set -u
umask 077

if [ "$#" -lt 2 ]; then
  echo "usage: bootstrap.sh ATTEMPT_ID RESULT_PATH [WRAPPER_OPTIONS...]" >&2
  exit 64
fi

attempt_id=$1
result_path=$2
shift 2

case "$attempt_id" in
  ''|*[!A-Za-z0-9._-]*)
    echo "invalid attempt identity" >&2
    exit 64
    ;;
esac

script_dir=$(CDPATH= cd "$(dirname "$0")" && pwd)
wrapper_path=${CI_SOAK_WRAPPER_PATH:-"$script_dir/wrapper.py"}

emit_terminal() {
  record=$1
  result_dir=$(dirname "$result_path")
  temporary_path="${result_path}.tmp.$$"
  if mkdir -p "$result_dir" &&
    printf '%s\n' "$record" >"$temporary_path" &&
    mv -f "$temporary_path" "$result_path"; then
    :
  else
    rm -f "$temporary_path"
  fi
  printf '%s\n' "WRAPPER_RESULT=$record"
}

candidate_list=${CI_SOAK_PYTHON_CANDIDATES:-"/usr/local/bin/python3
python3"}
selected_python=
saved_ifs=$IFS
IFS='
'
for candidate in $candidate_list; do
  [ -n "$candidate" ] || continue
  if command -v "$candidate" >/dev/null 2>&1 &&
    "$candidate" -c 'import sys; raise SystemExit(0 if sys.version_info >= (3, 11) else 1)' \
      >/dev/null 2>&1; then
    selected_python=$candidate
    break
  fi
done
IFS=$saved_ifs

if [ -z "$selected_python" ]; then
  terminal_record=$(printf '%s' \
    "{\"attempt_id\":\"$attempt_id\",\"controller_invocation\":\"NOT_INVOKED\",\"failure_class\":\"WRAPPER_FAILURE\",\"first_boundary\":\"bootstrap\",\"primary_rc\":null,\"primary_result\":\"NOT_INVOKED\",\"reason\":\"supported_python_not_found\",\"restore_rc\":null,\"restore_result\":\"NOT_INVOKED\",\"result\":\"FAIL\",\"schema_version\":1}")
  emit_terminal "$terminal_record"
  exit 78
fi

wrapper_rc=0
"$selected_python" "$wrapper_path" "$@" \
  --attempt-id "$attempt_id" \
  --result-path "$result_path" || wrapper_rc=$?

if [ -f "$result_path" ] || [ "$wrapper_rc" -eq 74 ]; then
  exit "$wrapper_rc"
fi

terminal_record=$(printf '%s' \
  "{\"attempt_id\":\"$attempt_id\",\"controller_invocation\":\"NOT_INVOKED\",\"failure_class\":\"ORCHESTRATION_STOP\",\"first_boundary\":\"wrapper_launch\",\"primary_rc\":null,\"primary_result\":\"NOT_INVOKED\",\"reason\":\"wrapper_terminal_missing\",\"restore_rc\":null,\"restore_result\":\"NOT_INVOKED\",\"result\":\"FAIL\",\"schema_version\":1}")
emit_terminal "$terminal_record"
exit 79
