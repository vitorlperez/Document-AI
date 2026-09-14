#!/usr/bin/env bash
set -euo pipefail

if [[ $# -ne 2 ]]; then
  echo "Usage: init-work-item.sh <feature-id> <title>" >&2
  exit 2
fi

feature_id="$1"
title="$2"
project_root="$(cd "$(dirname "$0")/../../../.." && pwd)"
output_dir="$project_root/specs/work-items"
output_file="$output_dir/$feature_id.md"

if [[ -e "$output_file" ]]; then
  echo "Refusing to overwrite existing work item: $output_file" >&2
  exit 1
fi

mkdir -p "$output_dir"
cat > "$output_file" <<EOF
# $feature_id - $title

**Status:** draft

## Source and outcome

- Source specification:
- User outcome:
- Non-goals:

## Decisions

| Decision | Owner | Status | ADR / rationale |
| --- | --- | --- | --- |

## Ready checklist

- [ ] Acceptance criteria written in Given/When/Then form.
- [ ] Owning module, API/data impact and failure states identified.
- [ ] Authorization, tenant and workspace-folder impact assessed.
- [ ] Performance and observability impact assessed.
- [ ] Protected decisions approved or marked not applicable.

## Ownership

| Role | Module/files owned | Deliverable |
| --- | --- | --- |
| Specification analyst | Read-only | Ready checklist and test matrix |
| Implementation owner | | Production change |
| Test engineer | | Automated tests |
| Feature validator | Read-only | Independent gate decision |

## Acceptance criteria and test matrix

| Criterion | Test layer | Evidence |
| --- | --- | --- |

## Commands and results

| Command | Result | Run by | Independent rerun |
| --- | --- | --- | --- |

## Validator report

- Blocking:
- Important:
- Suggestions:
- Independent evidence:
- Gate decision:
EOF

echo "$output_file"
