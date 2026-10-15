#!/usr/bin/env bash
# Stage everything, commit, push. Run from Git Bash.
# Usage: ./tts_envs/ship.sh "commit message"   (prompts if no message given)
set -e
cd "$(dirname "$0")"
cd "$(git rev-parse --show-toplevel)"

msg="$1"
if [ -z "$msg" ]; then
  read -rp "Commit message: " msg
fi
[ -z "$msg" ] && { echo "Aborted: empty message."; exit 1; }

git add .
git status --short
git commit -m "$msg"
git push
