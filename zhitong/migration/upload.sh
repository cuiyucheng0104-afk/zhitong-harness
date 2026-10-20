#!/usr/bin/env bash
# W8 迁移：把 relayout.py 生成的镜像（或 zhitong/knowledge-seed）用 rclone 上传到火山引擎 TOS 桶（spec §6 第 8 条）。
#
# 运行环境：Ubuntu 22.04 ECS，root。rclone 的 remote 由运行人用 `rclone config` 配好（runbook.md 第 6 步）；
# 本脚本不读、不写、不打印任何凭据，只引用 remote 名。
#
# 用法：
#   upload.sh --bucket <桶> --prefix <公司前缀> [--remote tos] [--src <镜像目录>] [--subdir <镜像内子目录>]
#             [--log-dir <目录>] [--allow-delete] [--yes] [-- <其余 rclone 参数>]
#   upload.sh --from-knowledge-seed <zhitong/knowledge-seed> --bucket <桶> --prefix <公司前缀> [同上]
#
# 两种模式：
#   镜像模式（默认）：rclone sync <src>[/<subdir>] → <remote>:<bucket>/<prefix>/[<subdir>/]。sync 会删掉目标里镜像没有的对象：
#     dry-run 里出现删除时默认中止，确认后加 --allow-delete 重跑。--subdir 用来分夜上传（如 --subdir 项目/2024-001-某工程）。
#   knowledge-seed 模式：rclone copy <seed>/ → <remote>:<bucket>/<prefix>/知识库/，只增不删；不上传 _tools/ 与 seed 根目录的 README.md。
#
# 每次都先 dry-run（计数写进日志），确认后正式上传（--checksum），最后 rclone check 校验。
# 退出码：0 成功；2 参数或环境错误；3 dry-run 发现删除而没有 --allow-delete；4 用户取消；其余为 rclone 的退出码。
set -euo pipefail

REMOTE="tos"
BUCKET=""
PREFIX=""
SRC="/opt/zhitong/migration-out/mirror"
SUBDIR=""
SEED=""
LOG_DIR=""
ALLOW_DELETE=0
YES=0
EXTRA=()

die() { printf '错误：%s\n' "$1" >&2; exit "${2:-2}"; }

while [ $# -gt 0 ]; do
  case "$1" in
    --remote) REMOTE="${2:?}"; shift 2 ;;
    --bucket) BUCKET="${2:?}"; shift 2 ;;
    --prefix) PREFIX="${2:?}"; shift 2 ;;
    --src) SRC="${2:?}"; shift 2 ;;
    --subdir) SUBDIR="${2:?}"; shift 2 ;;
    --from-knowledge-seed) SEED="${2:?}"; shift 2 ;;
    --log-dir) LOG_DIR="${2:?}"; shift 2 ;;
    --allow-delete) ALLOW_DELETE=1; shift ;;
    --yes) YES=1; shift ;;
    --) shift; EXTRA=("$@"); break ;;
    -h|--help) sed -n '2,20p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
    *) die "不认识的参数：$1（--help 看用法）" ;;
  esac
done

[ -n "$BUCKET" ] || die "缺 --bucket"
PREFIX="${PREFIX#/}"; PREFIX="${PREFIX%/}"
SUBDIR="${SUBDIR#/}"; SUBDIR="${SUBDIR%/}"
case "/$PREFIX/$SUBDIR/" in
  */../*|*/./*) die "--prefix / --subdir 不能含 . 或 .. 段" ;;
esac
command -v rclone >/dev/null 2>&1 || die "找不到 rclone（runbook 第 1 步安装）"
rclone listremotes | grep -qx "${REMOTE}:" || die "rclone 里没有名为 ${REMOTE} 的 remote（runbook 第 6 步 rclone config）"

DEST_BASE="${REMOTE}:${BUCKET}"
[ -n "$PREFIX" ] && DEST_BASE="${DEST_BASE}/${PREFIX}"

FILTERS=(--exclude "_tools/**" --exclude "**/_tools/**" --exclude "**/.*.zt-tmp")
if [ -n "$SEED" ]; then
  [ -d "$SEED" ] || die "knowledge-seed 目录不存在：$SEED"
  [ -z "$SUBDIR" ] || die "--from-knowledge-seed 不能与 --subdir 同用"
  MODE="copy"
  FROM="${SEED%/}/"
  TO="${DEST_BASE}/知识库/"
  FILTERS+=(--exclude "/README.md")
  CHECK_ARGS=(--one-way)
  [ -n "$LOG_DIR" ] || LOG_DIR="$(pwd)/upload-logs"
else
  [ -d "$SRC" ] || die "镜像目录不存在：$SRC（先运行 relayout.py）"
  [ -f "$SRC/案例索引.md" ] || die "$SRC 不像 relayout 的镜像（缺 案例索引.md）"
  MODE="sync"
  FROM="${SRC%/}/"
  TO="${DEST_BASE}/"
  if [ -n "$SUBDIR" ]; then
    [ -d "${SRC%/}/$SUBDIR" ] || die "镜像里没有子目录：$SUBDIR"
    FROM="${SRC%/}/${SUBDIR}/"
    TO="${DEST_BASE}/${SUBDIR}/"
  fi
  CHECK_ARGS=()
  [ -n "$LOG_DIR" ] || LOG_DIR="$(dirname "${SRC%/}")/logs"
fi

mkdir -p "$LOG_DIR"
STAMP="$(date +%Y%m%d-%H%M%S)"
LOG="${LOG_DIR}/upload-${STAMP}.log"
COMMON=(--checksum "${FILTERS[@]}" --log-file "$LOG" --log-level INFO "${EXTRA[@]}")

printf '模式：%s\n源：%s\n目标：%s\n日志：%s\n' "$MODE" "$FROM" "$TO" "$LOG"

echo "== 1/3 dry-run =="
rclone "$MODE" "$FROM" "$TO" "${COMMON[@]}" --dry-run
COPIES=$(grep -c 'Skipped copy as --dry-run' "$LOG" || true)
UPDATES=$(grep -c 'Skipped update as --dry-run' "$LOG" || true)
DELETES=$(grep -c 'Skipped delete as --dry-run' "$LOG" || true)
printf 'dry-run：新上传 %s、更新 %s、删除 %s（明细见日志）\n' "$COPIES" "$UPDATES" "$DELETES"
if [ "$DELETES" -gt 0 ] && [ "$ALLOW_DELETE" -ne 1 ]; then
  grep 'Skipped delete as --dry-run' "$LOG" | head -20 >&2 || true
  die "dry-run 要删除目标里的 ${DELETES} 个对象；核对日志后确实要删，加 --allow-delete 重跑" 3
fi

if [ "$YES" -ne 1 ]; then
  if [ ! -t 0 ]; then die "非交互运行需要 --yes" 4; fi
  read -r -p "按 dry-run 结果正式上传？[y/N] " ans
  case "$ans" in y|Y|yes) ;; *) die "已取消" 4 ;; esac
fi

echo "== 2/3 上传 =="
rclone "$MODE" "$FROM" "$TO" "${COMMON[@]}" --stats 1m --stats-log-level NOTICE

echo "== 3/3 rclone check =="
rclone check "$FROM" "$TO" --checksum "${FILTERS[@]}" "${CHECK_ARGS[@]}" --log-file "$LOG" --log-level INFO
echo "完成：上传与校验都通过。日志：$LOG"
