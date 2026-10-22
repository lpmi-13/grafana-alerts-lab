#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "${repo_root}"

usage() {
  echo "Usage: bash scripts/deploy.sh create [2-5]" >&2
  echo "       bash scripts/deploy.sh update <existing-playground-slug> [2-5]" >&2
}

action="${1:-}"
if [[ "${action}" == create ]]; then
  playground_name="grafana-alerts-lab"
  vm_count="${2:-2}"
  [[ $# -le 2 ]] || { usage; exit 2; }
elif [[ "${action}" == update && $# -ge 2 && $# -le 3 ]]; then
  playground_name="$2"
  vm_count="${3:-2}"
else
  usage
  exit 2
fi

command -v labctl >/dev/null || { echo "labctl is required" >&2; exit 1; }
labctl auth whoami >/dev/null || { echo "Run labctl auth login first" >&2; exit 1; }
python3 playground/iximiuz/render_manifest.py --name "${playground_name}" --vms "${vm_count}"

if [[ "${action}" == create ]]; then
  labctl playground create "${playground_name}" --base flexbox -f playground/iximiuz/manifest.yaml
else
  labctl playground update "${playground_name}" -f playground/iximiuz/manifest.yaml
fi
