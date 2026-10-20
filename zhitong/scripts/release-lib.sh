# shellcheck shell=bash disable=SC2034 # REL_* 由 source 本文件的 release.sh 读取
# release.sh 的纯函数：参数解析、版本校验、步骤选择、DMG 路径解析、续跑命令。只定义函数，source 时没有副作用。
# bash 3.2（macOS 自带）可用：不用关联数组、mapfile、${var,,}。测试：zhitong/scripts/tests/release.test.mjs。

# 步骤顺序；--from 取其中之一。
RL_STEPS="trigger mac win stage deploy"

# rl_normalize_version <版本> —— 去掉一个前导 v 后输出；不是 x.y.z 或 x.y.z-预发布 时返回 1。
# 规则与 .github/workflows/zhitong-windows-installer.yml 的版本校验一致（不允许 +build 元数据与前导 0）。
rl_normalize_version() {
  local v="${1#v}"
  local re='^(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)(-[0-9A-Za-z-]+(\.[0-9A-Za-z-]+)*)?$'
  [[ $v =~ $re ]] || return 1
  printf '%s\n' "$v"
}

# rl_step_index <步骤> —— 输出步骤序号；未知步骤返回 1。
rl_step_index() {
  local i=0 s
  for s in $RL_STEPS; do
    if [ "$s" = "$1" ]; then printf '%s\n' "$i"; return 0; fi
    i=$((i + 1))
  done
  return 1
}

# rl_quote <参数…> —— 以可复制到终端的形式输出一条命令（dry-run 与续跑提示用）。
rl_quote() {
  local out='' a
  for a in "$@"; do
    case "$a" in
      '' | *[!A-Za-z0-9_./:=@%+,-]*) a="'$(printf '%s' "$a" | sed "s/'/'\\\\''/g")'" ;;
    esac
    out="$out${out:+ }$a"
  done
  printf '%s\n' "$out"
}

# rl_parse_args <参数…> —— 设置 REL_* 全局变量；出错时向 stderr 写原因并返回 2。
#   REL_VERSION REL_SSH REL_SKIP_MAC REL_SKIP_WIN REL_SKIP_DEPLOY REL_NO_TAG REL_DRY_RUN REL_FROM REL_RUN_ID
#   REL_NOTES_FILE REL_WIN_EXE REL_WIN_TIMEOUT REL_HELP
#   REL_KEEP_ARGS：续跑时要原样带上的选项（不含 --from、--run-id、--dry-run），已转义。
rl_parse_args() {
  REL_VERSION='' REL_SSH=zt-prod REL_SKIP_MAC=0 REL_SKIP_WIN=0 REL_SKIP_DEPLOY=0 REL_NO_TAG=0 REL_DRY_RUN=0
  REL_FROM=trigger REL_RUN_ID='' REL_NOTES_FILE='' REL_WIN_EXE='' REL_WIN_TIMEOUT=120 REL_HELP=0 REL_KEEP_ARGS=''
  local raw=''
  while [ $# -gt 0 ]; do
    case "$1" in
      -h | --help) REL_HELP=1; return 0 ;;
      --skip-mac) REL_SKIP_MAC=1; REL_KEEP_ARGS="$REL_KEEP_ARGS $1" ;;
      --skip-win) REL_SKIP_WIN=1; REL_KEEP_ARGS="$REL_KEEP_ARGS $1" ;;
      --skip-deploy) REL_SKIP_DEPLOY=1; REL_KEEP_ARGS="$REL_KEEP_ARGS $1" ;;
      --no-tag) REL_NO_TAG=1; REL_KEEP_ARGS="$REL_KEEP_ARGS $1" ;;
      --dry-run) REL_DRY_RUN=1 ;;
      --ssh | --from | --run-id | --notes-file | --win-exe | --win-timeout)
        if [ $# -lt 2 ] || [ -z "$2" ] || [ "${2#-}" != "$2" ]; then
          printf '%s 需要一个值\n' "$1" >&2; return 2
        fi
        case "$1" in
          --ssh) REL_SSH="$2" ;;
          --from) REL_FROM="$2" ;;
          --run-id) REL_RUN_ID="$2" ;;
          --notes-file) REL_NOTES_FILE="$2" ;;
          --win-exe) REL_WIN_EXE="$2" ;;
          --win-timeout) REL_WIN_TIMEOUT="$2" ;;
        esac
        case "$1" in --from | --run-id) ;; *) REL_KEEP_ARGS="$REL_KEEP_ARGS $(rl_quote "$1" "$2")" ;; esac
        shift
        ;;
      -*) printf '未知选项 %s（--help 查看用法）\n' "$1" >&2; return 2 ;;
      *)
        if [ -n "$raw" ]; then printf '只能给一个版本号，收到 %s 与 %s\n' "$raw" "$1" >&2; return 2; fi
        raw="$1"
        ;;
    esac
    shift
  done
  if [ -z "$raw" ]; then printf '缺少版本号，例如 1.0.1\n' >&2; return 2; fi
  if ! REL_VERSION="$(rl_normalize_version "$raw")"; then
    printf '版本号 %s 不合法：应为 1.0.1 或 1.0.1-rc.1（可带前缀 v）\n' "$raw" >&2; return 2
  fi
  if ! rl_step_index "$REL_FROM" >/dev/null; then
    printf -- '--from 只能是 %s，收到 %s\n' "$RL_STEPS" "$REL_FROM" >&2; return 2
  fi
  case "$REL_RUN_ID" in *[!0-9]*) printf -- '--run-id 应为数字（Actions 运行页 URL 末尾那串），收到 %s\n' "$REL_RUN_ID" >&2; return 2 ;; esac
  case "$REL_WIN_TIMEOUT" in '' | 0 | *[!0-9]*) printf -- '--win-timeout 应为正整数分钟，收到 %s\n' "$REL_WIN_TIMEOUT" >&2; return 2 ;; esac
  if [ "$REL_SKIP_MAC" = 1 ] && [ "$REL_SKIP_WIN" = 1 ]; then
    printf -- '--skip-mac 与 --skip-win 同时给出就没有安装包可发；只更新网站用 bash zhitong/portal/deploy/deploy.sh\n' >&2; return 2
  fi
  if [ "$REL_SKIP_WIN" = 1 ] && { [ -n "$REL_WIN_EXE" ] || [ -n "$REL_RUN_ID" ] || [ "$REL_NO_TAG" = 1 ]; }; then
    printf -- '--skip-win 不能与 --win-exe、--run-id、--no-tag 同时使用\n' >&2; return 2
  fi
  if [ -n "$REL_WIN_EXE" ] && { [ -n "$REL_RUN_ID" ] || [ "$REL_NO_TAG" = 1 ]; }; then
    printf -- '--win-exe 不经过 Actions，不能与 --run-id、--no-tag 同时使用\n' >&2; return 2
  fi
  return 0
}

# rl_should_run <步骤> —— 按 REL_FROM 与 --skip-* 判断这一步是否执行（返回 0 执行）。
rl_should_run() {
  local idx from
  idx="$(rl_step_index "$1")" || return 1
  from="$(rl_step_index "$REL_FROM")"
  [ "$idx" -ge "$from" ] || return 1
  case "$1" in
    trigger) [ "$REL_SKIP_WIN" = 0 ] && [ -z "$REL_WIN_EXE" ] ;;
    mac) [ "$REL_SKIP_MAC" = 0 ] ;;
    win) [ "$REL_SKIP_WIN" = 0 ] ;;
    stage) return 0 ;;
    deploy) [ "$REL_SKIP_DEPLOY" = 0 ] ;;
  esac
}

# rl_dmg_from_log <日志文件> —— 输出打包日志里最后一个「DMG: <路径>.dmg」的路径（容忍 pnpm 行前缀与 CR）；没有则返回 1。
rl_dmg_from_log() {
  local path
  path="$(tr -d '\r' <"$1" | grep -E 'DMG: .*\.dmg[[:space:]]*$' | tail -n 1 | sed -e 's/^.*DMG: //' -e 's/[[:space:]]*$//')"
  [ -n "$path" ] || return 1
  printf '%s\n' "$path"
}

# rl_resume_cmd <步骤> [运行 id] —— 输出从该步续跑的完整命令，带上原来的选项。
rl_resume_cmd() {
  local cmd
  cmd="bash zhitong/scripts/release.sh $REL_VERSION$REL_KEEP_ARGS --from $1"
  if [ -n "${2:-}" ]; then cmd="$cmd --run-id $2"; fi
  printf '%s\n' "$cmd"
}
