#!/usr/bin/env bash
is_sourced=0
if [[ "${BASH_SOURCE[0]}" != "${0}" ]]; then
  is_sourced=1
  case "$-" in
    *e*) had_errexit=1 ;;
    *) had_errexit=0 ;;
  esac
  case "$-" in
    *u*) had_nounset=1 ;;
    *) had_nounset=0 ;;
  esac
  if set -o | grep -q '^pipefail[[:space:]]*on$'; then
    had_pipefail=1
  else
    had_pipefail=0
  fi
fi

set -euo pipefail

script_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
repo_root="$(cd -- "${script_dir}/.." && pwd)"
cd "${repo_root}"

echo "=== AgentFlow Setup ==="

python_bin=""
for candidate in python3 python; do
  if command -v "${candidate}" >/dev/null 2>&1 && "${candidate}" -c "import sys; raise SystemExit(0 if sys.version_info >= (3, 11) else 1)" >/dev/null 2>&1; then
    python_bin="${candidate}"
    break
  fi
done

if [[ -z "${python_bin}" ]]; then
  echo "Python 3.11+ is required."
  return 1 2>/dev/null || exit 1
fi

"${python_bin}" - <<'PY'
import sys

if sys.version_info < (3, 11):
    raise SystemExit("Need Python 3.11+")

print(f"Using Python {sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}")
PY

"${python_bin}" -m venv .venv
export VIRTUAL_ENV="${repo_root}/.venv"
export PATH="${VIRTUAL_ENV}/bin:${PATH}"

python -m pip install --upgrade pip
python -m pip install -e ".[dev]"
python -m pip install -e sdk/

if [ ! -f .env ]; then
  cp .env.example .env
fi

python -c "from src.serving.api.main import app; print('OK')"

if [[ "${BASH_SOURCE[0]}" == "${0}" ]]; then
  echo "=== Setup complete. Run 'source .venv/bin/activate' before 'make demo'. ==="
else
  echo "=== Setup complete. Run: make demo ==="
fi

if [[ "${is_sourced}" -eq 1 ]]; then
  if [[ "${had_errexit}" -eq 1 ]]; then
    set -e
  else
    set +e
  fi
  if [[ "${had_nounset}" -eq 1 ]]; then
    set -u
  else
    set +u
  fi
  if [[ "${had_pipefail}" -eq 1 ]]; then
    set -o pipefail
  else
    set +o pipefail
  fi
fi
