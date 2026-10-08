#!/usr/bin/env bash
# Install the Codex pack into $CODEX_HOME (default ~/.codex).
#
# Skills and AGENTS.md are symlinks into this checkout: one copy of the machinery, so a
# `git pull` here updates every Codex session. Custom agents are COPIES, because Codex
# refuses a symlinked agent file (measured 2026-10-07: spawn_agent answered "agent type is
# currently not available" for a symlink and succeeded for a byte-identical regular file).
# Each copy's first line is a marker naming its source, so the installer can tell its own
# copy from someone's own agent.
#
#   ./install.sh                         link skills and AGENTS.md; copy agents; create
#                                        registry.md from registry.example.md if it is missing
#   ./install.sh --check                 change nothing; report agent drift, missing installs
#                                        and link state; exit 1 if anything is missing or has
#                                        drifted
#   ./install.sh --uninstall             remove this pack's symlinks and marker-bearing agent
#                                        copies
#   ./install.sh --replace-other-pack    also take over skills, AGENTS.md and agents that are
#                                        symlinked into a DIFFERENT pack checkout (by default
#                                        those are reported and refused, so two checkouts never
#                                        fight over one Codex home)
#
# Edit the repo copy of an agent, then rerun this script: a copy that no longer matches the
# repo is overwritten. Safe to re-run. A real file or directory that this pack did not put
# there is never overwritten: it is reported as refused, the rest still installs, and the
# exit status is 1 at the end.
set -euo pipefail

PACK="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)"
CODEX_HOME="${CODEX_HOME:-$HOME/.codex}"
export CODEX_HOME # resolve_model.py reads the same catalog the installer was pointed at
REPLACE_OTHER=no # --replace-other-pack
REFUSED=0
PROBLEMS=0 # --check findings that make it exit 1
INSTALLED_AGENTS=()

MARKER_PREFIX="# Installed by codex-pack/install.sh"

marker_for() { # marker_for SRC
  echo "$MARKER_PREFIX from agents/$(basename "$1"). Edit the repo copy, then rerun install.sh."
}

render_agent() { # render_agent SRC : the exact bytes an installed copy holds
  marker_for "$1"
  cat "$1"
}

has_marker() { # has_marker FILE : a regular file whose first line is our marker
  [ -f "$1" ] && [ ! -L "$1" ] && case "$(head -n 1 "$1" 2>/dev/null)" in
    "$MARKER_PREFIX"*) true ;;
    *) false ;;
  esac
}

# A symlink into this pack, or one pointing nowhere, is an old install with nothing to protect.
is_ours_or_dangling() {
  local target
  [ -L "$1" ] || return 1
  [ -e "$1" ] || return 0
  target="$(readlink "$1")"
  case "$target" in "$PACK"/*) return 0 ;; *) return 1 ;; esac
}

# other_pack_of DEST : prints the root of ANOTHER pack checkout that the symlink DEST points
# into, and returns 0; returns 1 for anything else. A pack checkout is a directory holding
# both install.sh and skills/, found by walking up from the link's target.
other_pack_of() {
  local dest="$1" target dir i
  target="$(readlink "$dest")"
  case "$target" in /*) ;; *) target="$(dirname "$dest")/$target" ;; esac
  dir="$(cd "$(dirname "$target")" 2>/dev/null && pwd -P)" || return 1
  for i in 1 2 3 4; do
    [ "$dir" = "$PACK" ] && return 1
    if [ -f "$dir/install.sh" ] && [ -d "$dir/skills" ]; then
      echo "$dir"
      return 0
    fi
    [ "$dir" = "/" ] && return 1
    dir="$(dirname "$dir")"
  done
  return 1
}

# agent_state SRC DEST
#   -> missing | old-link | other-link | foreign-link | foreign | current | drift
agent_state() {
  local src="$1" dest="$2"
  if [ -L "$dest" ]; then
    if is_ours_or_dangling "$dest"; then
      echo old-link
    elif other_pack_of "$dest" >/dev/null; then
      echo other-link
    else
      echo foreign-link
    fi
  elif [ ! -e "$dest" ]; then
    echo missing
  elif has_marker "$dest"; then
    if cmp -s <(render_agent "$src") "$dest"; then echo current; else echo drift; fi
  else
    echo foreign
  fi
}

# link SRC DEST
# DEST that is already our link is left alone, and so is a dangling one or one into this pack
# (an old install: relinked). A symlink into ANOTHER pack checkout is refused unless
# --replace-other-pack was given, because two checkouts fighting over one Codex home is the
# mistake worth stopping. Any other symlink is someone's own choice and is always refused.
link() {
  local src="$1" dest="$2"
  if [ -L "$dest" ]; then
    local current other
    current="$(readlink "$dest")"
    if [ "$current" = "$src" ]; then
      echo "already linked: $dest"
      return 0
    fi
    if [ ! -e "$dest" ] || is_ours_or_dangling "$dest"; then
      ln -sfn "$src" "$dest"
      echo "relinked: $dest -> $src (was -> $current)"
      return 0
    fi
    if other="$(other_pack_of "$dest")"; then
      if [ "$REPLACE_OTHER" = "yes" ]; then
        ln -sfn "$src" "$dest"
        echo "relinked: $dest -> $src (was -> $current, in another pack checkout: $other)"
        return 0
      fi
      echo "refused: $dest is linked into another pack checkout ($other); rerun with --replace-other-pack to switch it to this one"
    else
      echo "refused: $dest is a symlink to $current, not to this pack (remove it to relink)"
    fi
    REFUSED=$((REFUSED + 1))
    return 1
  fi
  if [ -e "$dest" ]; then
    echo "refused: $dest exists and is not a symlink; leaving it alone"
    REFUSED=$((REFUSED + 1))
    return 1
  fi
  ln -s "$src" "$dest"
  echo "linked: $dest -> $src"
}

install_skills() {
  local sources=("$@")
  if [ "${#sources[@]}" -eq 0 ]; then
    echo "skipped: nothing in $PACK/skills yet"
    return 0
  fi
  mkdir -p "$CODEX_HOME/skills"
  local src
  for src in "${sources[@]}"; do
    src="${src%/}"
    link "$src" "$CODEX_HOME/skills/$(basename "$src")" || true
  done
}

write_agent() { # write_agent SRC DEST : a whole file or nothing, never a half-written agent
  local tmp
  tmp="$(mktemp "$2.XXXXXX")" # no .toml suffix, so Codex never reads a leftover
  render_agent "$1" >"$tmp"
  chmod 644 "$tmp"
  mv "$tmp" "$2"
}

install_agents() {
  local sources=("$@")
  if [ "${#sources[@]}" -eq 0 ]; then
    echo "skipped: nothing in $PACK/agents yet"
    return 0
  fi
  mkdir -p "$CODEX_HOME/agents"
  local src dest
  for src in "${sources[@]}"; do
    dest="$CODEX_HOME/agents/$(basename "$src")"
    case "$(agent_state "$src" "$dest")" in
      missing)
        write_agent "$src" "$dest"
        echo "copied: $dest"
        INSTALLED_AGENTS+=("$dest")
        ;;
      old-link)
        rm "$dest"
        write_agent "$src" "$dest"
        echo "replaced symlink with a copy: $dest (Codex refuses a symlinked agent)"
        INSTALLED_AGENTS+=("$dest")
        ;;
      drift)
        write_agent "$src" "$dest"
        echo "updated: $dest (it no longer matched the repo copy)"
        INSTALLED_AGENTS+=("$dest")
        ;;
      current)
        echo "already current: $dest"
        INSTALLED_AGENTS+=("$dest")
        ;;
      other-link)
        if [ "$REPLACE_OTHER" = "yes" ]; then
          rm "$dest"
          write_agent "$src" "$dest"
          echo "replaced symlink into another pack checkout with a copy: $dest"
          INSTALLED_AGENTS+=("$dest")
        else
          echo "refused: $dest is linked into another pack checkout ($(other_pack_of "$dest")); rerun with --replace-other-pack to take it over"
          REFUSED=$((REFUSED + 1))
        fi
        ;;
      foreign-link)
        echo "refused: $dest is a symlink to $(readlink "$dest"), not to this pack (remove it to install)"
        REFUSED=$((REFUSED + 1))
        ;;
      foreign)
        echo "refused: $dest exists and this pack did not install it (no marker line); leaving it alone"
        REFUSED=$((REFUSED + 1))
        ;;
    esac
  done
}

install_agents_md() {
  local src="$PACK/AGENTS.md" dest="$CODEX_HOME/AGENTS.md"
  if [ ! -f "$src" ]; then
    echo "skipped: no $src yet"
    return 0
  fi
  mkdir -p "$CODEX_HOME"
  if [ -L "$dest" ] || [ ! -e "$dest" ]; then
    link "$src" "$dest" || true
  elif [ ! -s "$dest" ]; then
    # Codex creates an empty AGENTS.md on first run; an empty file holds nothing to lose.
    rm "$dest"
    echo "replacing empty file: $dest"
    link "$src" "$dest" || true
  else
    echo "left alone: $dest has your own content. To adopt this pack's, run:"
    echo "  mv \"$dest\" \"$dest.bak\" && ln -s \"$src\" \"$dest\""
  fi
}

# registry.md is per-machine config (the repos this person's tickets live in), so it is
# gitignored and created from the shipped example the first time. An existing one is theirs.
install_registry() {
  local registry="$PACK/registry.md" example="$PACK/registry.example.md"
  if [ -e "$registry" ]; then
    echo "already present: $registry"
  elif [ -f "$example" ]; then
    cp "$example" "$registry"
    echo "created: $registry from registry.example.md"
    echo "  -> open it and replace the example rows with your own repos before running the ticket skills"
  else
    echo "skipped: no registry.md and no registry.example.md to create it from"
  fi
}

uninstall() {
  local entry target removed=0
  for entry in "$CODEX_HOME"/skills/* "$CODEX_HOME"/agents/* "$CODEX_HOME/AGENTS.md"; do
    if [ -L "$entry" ]; then
      target="$(readlink "$entry")"
      case "$target" in
        "$PACK"/*)
          rm "$entry"
          echo "removed: $entry"
          removed=$((removed + 1))
          ;;
      esac
    elif has_marker "$entry"; then
      rm "$entry"
      echo "removed: $entry (agent copy)"
      removed=$((removed + 1))
    fi
  done
  [ "$removed" -gt 0 ] || echo "nothing to remove: nothing from $PACK under $CODEX_HOME"
}

problem() { # problem MESSAGE : a --check finding that fails the run
  echo "$1"
  PROBLEMS=$((PROBLEMS + 1))
}

check_link() { # check_link SRC DEST
  local src="$1" dest="$2" other
  if [ -L "$dest" ] && [ "$(readlink "$dest")" = "$src" ]; then
    echo "ok: $dest -> $src"
  elif [ -L "$dest" ] && [ -e "$dest" ] && other="$(other_pack_of "$dest")"; then
    problem "other-pack: $dest is linked into another pack checkout ($other); install would refuse it without --replace-other-pack"
  elif [ -L "$dest" ]; then
    problem "drift: $dest points to $(readlink "$dest"), not to this pack"
  elif [ -e "$dest" ]; then
    problem "foreign: $dest exists and is not a link to this pack (install would refuse it)"
  else
    problem "missing: $dest is not linked"
  fi
}

check_all() {
  local src dest
  for src in "$PACK"/skills/*/; do
    src="${src%/}"
    check_link "$src" "$CODEX_HOME/skills/$(basename "$src")"
  done
  for src in "$PACK"/agents/*.toml; do
    dest="$CODEX_HOME/agents/$(basename "$src")"
    case "$(agent_state "$src" "$dest")" in
      current)
        echo "ok: $dest matches the repo copy"
        INSTALLED_AGENTS+=("$dest")
        ;;
      drift)
        problem "drift: $dest differs from $src (rerun install.sh to update it)"
        INSTALLED_AGENTS+=("$dest")
        ;;
      missing) problem "missing: $dest is not installed" ;;
      old-link) problem "drift: $dest is a symlink, which Codex refuses (rerun install.sh to copy it)" ;;
      other-link) problem "other-pack: $dest is linked into another pack checkout ($(other_pack_of "$dest")); install would refuse it without --replace-other-pack" ;;
      foreign-link) problem "foreign: $dest is a symlink to $(readlink "$dest"), not to this pack" ;;
      foreign) problem "foreign: $dest was not installed by this pack (install would refuse it)" ;;
    esac
  done
  if [ -f "$PACK/AGENTS.md" ]; then
    dest="$CODEX_HOME/AGENTS.md"
    if [ -e "$dest" ] && [ ! -L "$dest" ] && [ -s "$dest" ]; then
      echo "left alone: $dest has your own content (install leaves it too)"
    else
      check_link "$PACK/AGENTS.md" "$dest"
    fi
  fi
  if [ -e "$PACK/registry.md" ]; then
    echo "ok: $PACK/registry.md exists"
  elif [ -f "$PACK/registry.example.md" ]; then
    problem "missing: $PACK/registry.md (install creates it from registry.example.md)"
  fi
}

run_model_check() {
  # A stale or invalid agent file is reported, never a reason to fail the install.
  if [ "${#INSTALLED_AGENTS[@]}" -gt 0 ]; then
    echo "checking agent files against the live model catalog:"
    python3 "$PACK/scripts/resolve_model.py" --check "${INSTALLED_AGENTS[@]}" || true
  fi
}

usage() {
  echo "usage: $0 [--check | --uninstall] [--replace-other-pack]" >&2
  exit 2
}

MODE="install"
for arg in "$@"; do
  case "$arg" in
    --uninstall | --check)
      [ "$MODE" = "install" ] || usage
      MODE="${arg#--}"
      ;;
    --replace-other-pack) REPLACE_OTHER=yes ;;
    *) usage ;;
  esac
done

shopt -s nullglob
case "$MODE" in
  uninstall)
    uninstall
    exit 0
    ;;
  check)
    check_all
    run_model_check
    if [ "$PROBLEMS" -gt 0 ]; then
      echo "$PROBLEMS problem(s); rerun ./install.sh to fix" >&2
      exit 1
    fi
    echo "everything is installed and current"
    exit 0
    ;;
esac

install_skills "$PACK"/skills/*/
install_agents "$PACK"/agents/*.toml
install_agents_md
install_registry
run_model_check

if [ "$REFUSED" -gt 0 ]; then
  echo "$REFUSED target(s) refused; see above" >&2
  exit 1
fi
