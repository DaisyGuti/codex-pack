#!/usr/bin/env bash
# Validate every skill with Codex's own validator, and prove the pack stands alone.
#
#   scripts/validate_skills.sh
#
# Six checks, all must pass:
#   1. For each skills/<name>/, run Codex's quick_validate.py (shipped with Codex's built-in
#      skill-creator under ${CODEX_HOME:-~/.codex}/skills/.system/). A missing validator is a
#      failure, never a silent pass: a gate that cannot run proves nothing.
#   2. skills/, agents/, references/ and AGENTS.md must not mention the Claude Code config
#      directory or a home directory of one particular machine. The pack is cloned onto other
#      accounts, so those strings are broken references there.
#   3. Tracker adapters agree. Every file in references/trackers/*.md defines the same set of
#      `## ` headings (one per tracker operation), and every hyphenated bold operation name
#      like **set-lane** in skills/*/SKILL.md and skills/*/references/*.md (and the shared
#      top-level references/*.md those skills symlink to) is one of those headings, bar the
#      small allow-list below of bold terms that are not operations. Single-word bold tokens
#      (**comment**, **assign**) are not checked: they cannot be told apart from emphasis.
#   4. No personal details. The pack is shared by a team, so the strings listed in the
#      untracked file .personal-strings (one fixed string per line; blank lines and # comments
#      ignored; matched case-insensitively) must appear in no tracked file and no untracked,
#      non-ignored file, bar LICENSE*.txt and THIRD_PARTY_NOTICES.md. The file is per-machine
#      and ignored by git; without it the check prints a skip line and passes. Only the
#      number of hits per file is printed, never the strings or the lines that matched.
#   5. scripts/check_skills.py: the Agent Skills spec's MUST rules and Codex's agents/openai.yaml
#      rules fail the gate; recommendations print as warnings. See its docstring for the rules.
#   6. scripts/check_pack.py: the agent files keep their shape (no pinned model, the reviewer and
#      forward tester read-only), every skills/ path the instructions name resolves inside the
#      pack, and no tracked or unignored file holds an invisible character or a secret.
set -euo pipefail

PACK="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd -P)"
CODEX_HOME="${CODEX_HOME:-$HOME/.codex}"
VALIDATOR="$CODEX_HOME/skills/.system/skill-creator/scripts/quick_validate.py"
FAILED=0

shopt -s nullglob

if [ ! -f "$VALIDATOR" ]; then
  echo "FAIL: Codex's skill validator is not at $VALIDATOR" >&2
  echo "  It ships with Codex's built-in skill-creator; start Codex once so it installs its" >&2
  echo "  system skills, or point CODEX_HOME at a Codex home that has them." >&2
  FAILED=1
else
  skills=("$PACK"/skills/*/)
  if [ "${#skills[@]}" -eq 0 ]; then
    echo "FAIL: no skills found under $PACK/skills" >&2
    FAILED=1
  fi
  for dir in "${skills[@]+"${skills[@]}"}"; do
    dir="${dir%/}"
    if out="$(cd "$PACK" && uv run python "$VALIDATOR" "$dir" 2>&1)"; then
      echo "ok: $(basename "$dir"): $out"
    else
      echo "FAIL: $(basename "$dir"): $out" >&2
      FAILED=1
    fi
  done
fi

# Standalone guarantee. `grep -r` does not follow the symlinks inside skills/ (they point back
# into references/ and scripts/), so nothing is scanned twice; references/ is scanned directly.
targets=()
for path in "$PACK/skills" "$PACK/agents" "$PACK/references" "$PACK/AGENTS.md"; do
  [ -e "$path" ] && targets+=("$path")
done
if [ "${#targets[@]}" -gt 0 ]; then
  if hits="$(grep -rnIE '~/\.claude|\$HOME/\.claude|/Users/' "${targets[@]}")"; then
    echo "FAIL: the pack must not depend on ~/.claude or a machine's home:" >&2
    echo "$hits" | sed 's/^/  /' >&2
    FAILED=1
  else
    echo "ok: no reference to ~/.claude or /Users/ in skills, agents, references or AGENTS.md"
  fi
fi

# --- Check 3: tracker adapters agree -------------------------------------------------------

# Bold, lowercase, hyphenated tokens that are not tracker operations.
NON_OPERATION_TERMS=(run-worker run-solo)

SCRATCH="$(mktemp -d)"
trap 'rm -rf "$SCRATCH"' EXIT

# Print the `## ` headings of one adapter, one per line, skipping fenced code blocks (a
# shell comment inside a fence is not a heading) and trimming trailing whitespace.
adapter_headings() {
  awk '/^```/ { fence = !fence; next } !fence && /^## / { sub(/[ \t\r]+$/, ""); print substr($0, 4) }' "$1" | sort -u
}

adapters=("$PACK"/references/trackers/*.md)
if [ "${#adapters[@]}" -eq 0 ]; then
  echo "FAIL: no tracker adapters found under $PACK/references/trackers" >&2
  FAILED=1
else
  : > "$SCRATCH/all-headings"
  for f in "${adapters[@]}"; do
    adapter_headings "$f" > "$SCRATCH/$(basename "$f").headings"
    cat "$SCRATCH/$(basename "$f").headings" >> "$SCRATCH/all-headings"
  done
  sort -u "$SCRATCH/all-headings" -o "$SCRATCH/all-headings"

  adapters_agree=1
  for f in "${adapters[@]}"; do
    missing="$(comm -23 "$SCRATCH/all-headings" "$SCRATCH/$(basename "$f").headings")"
    if [ -n "$missing" ]; then
      adapters_agree=0
      while IFS= read -r heading; do
        echo "FAIL: tracker adapter references/trackers/$(basename "$f") is missing the heading '## $heading' that another adapter has" >&2
      done <<< "$missing"
    fi
  done
  if [ "$adapters_agree" -eq 1 ]; then
    echo "ok: ${#adapters[@]} tracker adapters define the same $(wc -l < "$SCRATCH/all-headings" | tr -d ' ') headings"
  else
    FAILED=1
  fi

  # Real files only: find without -L neither follows the symlinked directories inside skills/
  # nor lists symlinked files, so shared content is scanned once, from references/ itself.
  : > "$SCRATCH/doc-files"
  [ -d "$PACK/skills" ] && find "$PACK/skills" -mindepth 2 -maxdepth 3 -type f \
    \( -path '*/*/SKILL.md' -o -path '*/*/references/*.md' \) >> "$SCRATCH/doc-files"
  find "$PACK/references" -maxdepth 1 -type f -name '*.md' >> "$SCRATCH/doc-files"
  sort -o "$SCRATCH/doc-files" "$SCRATCH/doc-files"

  unknown=0
  checked=0
  while IFS= read -r doc; do
    [ -n "$doc" ] || continue
    checked=$((checked + 1))
    # file:line:token for each **a-b** / **a-b-c** in the file.
    while IFS=: read -r line token; do
      name="${token#\*\*}"; name="${name%\*\*}"
      allowed=0
      for term in "${NON_OPERATION_TERMS[@]}"; do
        [ "$name" = "$term" ] && allowed=1
      done
      [ "$allowed" -eq 1 ] && continue
      grep -qxF -- "$name" "$SCRATCH/all-headings" && continue
      echo "FAIL: ${doc#"$PACK"/}:$line: **$name** is not a tracker operation (no '## $name' heading in references/trackers/)" >&2
      unknown=1
    done < <(grep -noE '\*\*[a-z]+(-[a-z]+)+\*\*' "$doc" || true)
  done < "$SCRATCH/doc-files"
  if [ "$unknown" -eq 0 ]; then
    echo "ok: every bold operation name in $checked skill/reference files is a tracker adapter heading"
  else
    FAILED=1
  fi
fi

# --- Check 4: no personal details ------------------------------------------------------------

PERSONAL="$PACK/.personal-strings"
if [ ! -f "$PERSONAL" ]; then
  echo "skip: no .personal-strings file"
else
  # Fixed strings only: drop blank lines and # comments, and any carriage returns.
  { grep -vE '^[[:space:]]*(#|$)' "$PERSONAL" || true; } | tr -d '\r' > "$SCRATCH/personal-patterns"
  if [ ! -s "$SCRATCH/personal-patterns" ]; then
    echo "skip: .personal-strings holds no strings"
  elif ! files="$(cd "$PACK" && { git ls-files -z && git ls-files -z --others --exclude-standard; } | tr '\0' '\n')"; then
    echo "FAIL: cannot list the pack's files with git, so .personal-strings was not checked" >&2
    FAILED=1
  else
    scanned=0
    personal_hits=0
    while IFS= read -r file; do
      [ -n "$file" ] || continue
      case "$(basename "$file")" in LICENSE*.txt | THIRD_PARTY_NOTICES.md) continue ;; esac
      # A symlink points at a file scanned under its own name; a deleted file has nothing to scan.
      [ -f "$PACK/$file" ] && [ ! -L "$PACK/$file" ] || continue
      scanned=$((scanned + 1))
      count="$(grep -cIiF -f "$SCRATCH/personal-patterns" -- "$PACK/$file" || true)"
      if [ "${count:-0}" -gt 0 ]; then
        echo "FAIL: $file: $count line(s) match .personal-strings" >&2
        personal_hits=1
      fi
    done <<< "$files"
    if [ "$personal_hits" -eq 0 ]; then
      echo "ok: none of the .personal-strings appear in the $scanned tracked or untracked files checked"
    else
      FAILED=1
    fi
  fi
fi

# --- Check 5: skill authoring rules ----------------------------------------------------------

if ! (cd "$PACK" && uv run python scripts/check_skills.py); then
  echo "FAIL: scripts/check_skills.py found a MUST rule broken (see FAIL lines above)" >&2
  FAILED=1
fi

# --- Check 6: the pack's own files ------------------------------------------------------------

if ! (cd "$PACK" && uv run python scripts/check_pack.py); then
  echo "FAIL: scripts/check_pack.py found a problem in the pack's own files (see FAIL lines above)" >&2
  FAILED=1
fi

exit "$FAILED"
