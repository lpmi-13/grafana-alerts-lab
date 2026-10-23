#!/usr/bin/env bash
# Publish / refresh the lab: render the manifest, then update the custom
# playground (labctl playground update).
#
# render_manifest.py embeds everything the lab needs in manifest.yaml: the app,
# the Grafana provisioning files, and the landing page (the manifest's markdown).
# So one playground update ships every change, and there is no rootfs image or
# separate content to push. Render to a temporary file and record it in
# manifest.yaml only after the playground update succeeds. Running sessions keep
# the old definition; start a new session to see the change.
#
#   PLAYGROUND_NAME  default: grafana-alerts-lab-2292969d
#   VMS              default: 2 (2 to 5)
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
manifest="${repo_root}/playground/iximiuz/manifest.yaml"
playground_name="${PLAYGROUND_NAME:-grafana-alerts-lab-2292969d}"
vm_count="${VMS:-2}"

die() { echo "$*" >&2; exit 1; }

# Prepare the next manifest before publishing, but keep the current version on
# disk if rendering or the playground update fails.
next_manifest="$(mktemp --suffix=.yaml "${manifest}.next.XXXXXX")"
trap 'rm -f "$next_manifest"' EXIT
python3 "${repo_root}/playground/iximiuz/render_manifest.py" \
  --name "${playground_name}" --vms "${vm_count}" --output "${next_manifest}" >/dev/null
chmod --reference="$manifest" "$next_manifest"

command -v labctl >/dev/null || die "labctl is required"
labctl auth whoami >/dev/null 2>&1 || die "run: labctl auth login"

echo "== update custom playground ${playground_name} (${vm_count} VMs) =="
labctl playground update "${playground_name}" -f "$next_manifest"
mv "$next_manifest" "$manifest"

echo "Done:"
echo "  playground: https://labs.iximiuz.com/playgrounds/${playground_name}"
echo "  try it in a new session: labctl playground start ${playground_name}"
