#!/bin/zsh
cd -- "${0:A:h}" || exit 1
export PYTHONUTF8=1

# Test the interpreter instead of assuming Apple's bundled Python is new enough.
python_bin=""
candidates=("${BADMINTON_PYTHON:-}" "$(command -v python3)" "/Library/Frameworks/Python.framework/Versions/Current/bin/python3" "/opt/homebrew/bin/python3" "/usr/local/bin/python3")
for candidate in "${candidates[@]}"; do
  if [[ -n "$candidate" && -x "$candidate" ]] && "$candidate" -c 'import sys; raise SystemExit(sys.version_info < (3,10))' 2>/dev/null; then
    python_bin="$candidate"
    break
  fi
done
if [[ -z "$python_bin" ]]; then
  echo 'Please install Python 3.10+ (macOS universal2) from https://www.python.org/downloads/macos/'
  echo 'Then open Start-macOS.command again.'
  read -r '?Press Return to close...'
  exit 1
fi
# Prevent idle system sleep while running; closing the lid can still suspend Mac.
if [[ -x /usr/bin/caffeinate ]]; then
  /usr/bin/caffeinate -i "$python_bin" -X utf8 launcher.py "$@"
else
  "$python_bin" -X utf8 launcher.py "$@"
fi
result=$?
if (( result != 0 )); then
  echo "Startup stopped (exit $result). See the message above."
  read -r '?Press Return to close...'
fi
exit "$result"
