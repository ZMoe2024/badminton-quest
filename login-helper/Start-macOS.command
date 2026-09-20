#!/bin/zsh
set -euo pipefail
quest_root="$(cd "$(dirname "$0")" && pwd)"
quest_node="$(command -v node || true)"
if [[ -z "$quest_node" ]] || ! "$quest_node" -e "process.exit(Number(process.versions.node.split('.')[0]) >= 22 ? 0 : 1)"; then
  case "$(uname -m)" in
    arm64) quest_arch=arm64; quest_expected=61130f394c1630d211dd50aecc4353d379480f36d3ac913cd85dbba1aed585c6 ;;
    x86_64) quest_arch=x64; quest_expected=58e99022c2ff89395576cc7fd4d98cea24bb68081475d5f88b801ee8729fb026 ;;
    *) echo 'Unsupported Mac architecture'; exit 1 ;;
  esac
  quest_version=v22.23.2
  quest_name="node-$quest_version-darwin-$quest_arch"
  quest_cache="$HOME/Library/Caches/BadmintonQuestLogin/runtime"
  quest_node="$quest_cache/$quest_name/bin/node"
  if [[ ! -x "$quest_node" ]]; then
    echo '首次启动：正在从 nodejs.org 准备运行环境…'
    mkdir -p "$quest_cache"
    quest_archive="$quest_cache/$quest_name.tar.gz"
    curl --fail --location --proto '=https' --tlsv1.2 --retry 2 "https://nodejs.org/dist/$quest_version/$quest_name.tar.gz" -o "$quest_archive"
    quest_actual="$(shasum -a 256 "$quest_archive" | awk '{print $1}')"
    if [[ "$quest_actual" != "$quest_expected" ]]; then
      echo '运行环境校验失败，已停止；未执行下载内容。'; exit 1
    fi
    tar -xzf "$quest_archive" -C "$quest_cache"
    rm -f "$quest_archive"
  fi
fi
exec "$quest_node" "$quest_root/session-helper.mjs" "$@"
