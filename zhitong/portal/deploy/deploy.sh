#!/usr/bin/env bash
# 发布智通数工AI 门户 ztsgai.com：本机构建 → 上传安装包 → 替换站点 → 上传清单 → 装 nginx 配置 → 校验。
#
# 在用户自己的 Mac 上执行（bash 3.2 可用），只用标准 ssh / rsync / curl / node / npm，不含任何凭据：
#   bash zhitong/portal/deploy/deploy.sh [选项] [ssh 别名]          ssh 别名默认 zt-prod（~/.ssh/config 里的 Host）
#
# 选项：
#   --mode container|host   nginx 跑在 zt-nginx 容器里（默认，推荐）还是宿主机 nginx；见 runbook.md「选 nginx」
#   --skip-build            不重新构建，直接用现有 dist/
#   --skip-nginx            不上传、不重载 nginx 配置（只更新站点与安装包）
#   --skip-verify           不做最后的 curl 校验（首次上线时先传文件、旧系统仍在服务，见 runbook.md 3.1）
#   --downloads DIR         安装包所在目录，默认 zhitong/portal/downloads（release-manifest.mjs stage 的输出）
#   --base-url URL          校验用的站点地址，默认 https://ztsgai.com
#   --resolve IP            校验时把域名钉到这个 IP（DNS 尚未生效或要绕过本机 DNS 缓存时用）
#
# 服务器布局（runbook.md）：/opt/ztsgai/{site,site.prev,downloads,nginx/conf.d,logs/nginx,docker-compose.yml}。
# 远端账号是 root 或有免密 sudo；其它情况脚本在第一次远端调用时报错退出。
set -euo pipefail

DEPLOY_DIR="$(cd "$(dirname "$0")" && pwd)"
PORTAL="$(cd "$DEPLOY_DIR/.." && pwd)"
SITE="$PORTAL/site"
MANIFEST="$SITE/public/downloads/releases.json"
REMOTE_ROOT=/opt/ztsgai

MODE=container
SKIP_BUILD=0
SKIP_NGINX=0
SKIP_VERIFY=0
DOWNLOADS="$PORTAL/downloads"
BASE_URL=https://ztsgai.com
RESOLVE_IP=
HOST=zt-prod

die() { printf '✗ %s\n' "$*" >&2; exit 1; }
step() { printf '\n▶ %s\n' "$*"; }

while [ $# -gt 0 ]; do
  case "$1" in
    --mode) MODE="${2:?--mode 需要 container 或 host}"; shift 2 ;;
    --skip-build) SKIP_BUILD=1; shift ;;
    --skip-nginx) SKIP_NGINX=1; shift ;;
    --skip-verify) SKIP_VERIFY=1; shift ;;
    --downloads) DOWNLOADS="${2:?--downloads 需要目录}"; shift 2 ;;
    --base-url) BASE_URL="${2:?--base-url 需要地址}"; shift 2 ;;
    --resolve) RESOLVE_IP="${2:?--resolve 需要 IP}"; shift 2 ;;
    -h|--help) sed -n '2,16p' "$0"; exit 0 ;;
    -*) die "未知选项 $1（--help 查看用法）" ;;
    *) HOST="$1"; shift ;;
  esac
done
case "$MODE" in container|host) ;; *) die "--mode 只能是 container 或 host，收到 $MODE" ;; esac
BASE_URL="${BASE_URL%/}"

for tool in node npm rsync ssh curl; do
  command -v "$tool" >/dev/null 2>&1 || die "本机缺少 $tool"
done

# ── 1. 安装包与清单一致 ────────────────────────────────────────────────
step "核对安装包与 releases.json（$DOWNLOADS）"
node "$DEPLOY_DIR/release-manifest.mjs" verify --downloads "$DOWNLOADS" \
  || die "安装包与清单不一致；用 release-manifest.mjs stage 重新放置安装包（见 runbook.md「上传安装包」）"
# 清单列出的安装包，每行「文件名<TAB>字节数」。
# shellcheck disable=SC2016 # JavaScript 模板字符串，不是 shell 展开
RELEASED="$(node --input-type=module -e '
  import { readFileSync } from "node:fs";
  const m = JSON.parse(readFileSync(process.argv[1], "utf8"));
  for (const p of Object.values(m.platforms)) if (p.file) console.log(`${p.file}\t${p.size}`);
' "$MANIFEST")"
# 要上传的文件：每个安装包与它的 .sha256。
INSTALLER_FILES="$(printf '%s\n' "$RELEASED" | awk -F '\t' 'NF { print $1; print $1 ".sha256" }')"

# ── 2. 构建 ────────────────────────────────────────────────────────────
if [ "$SKIP_BUILD" = 0 ]; then
  step "构建门户（npm run build）"
  (
    cd "$SITE"
    [ -d node_modules ] || npm ci
    npm run build
  )
fi
[ -f "$SITE/dist/index.html" ] || die "没有 $SITE/dist/index.html；去掉 --skip-build 重新构建"
cmp -s "$SITE/dist/downloads/releases.json" "$MANIFEST" \
  || die "dist 里的 releases.json 与 $MANIFEST 不同：清单改过之后没有重新构建"

# ── 3. 远端准备 ────────────────────────────────────────────────────────
step "连接 $HOST"
ssh -o BatchMode=yes "$HOST" true || die "ssh $HOST 不通（BatchMode：需要密钥登录，不能交互输密码）"
SUDO="$(ssh "$HOST" '[ "$(id -u)" = 0 ] || echo "sudo -n"')"
RSYNC_PATH=rsync
[ -z "$SUDO" ] || RSYNC_PATH="sudo -n rsync"
# 参数只有本脚本给的固定路径，在本机展开后作为远端 bash -s 的位置参数。
# shellcheck disable=SC2029
remote() { ssh "$HOST" "$SUDO bash -s -- $*"; }

SITE_EXISTS="$(remote "$REMOTE_ROOT" <<'EOF'
set -euo pipefail
root="$1"
mkdir -p "$root/downloads" "$root/nginx/conf.d" "$root/logs/nginx"
rm -rf "$root/.site-new"
if [ -d "$root/site" ]; then echo yes; fi
EOF
)"

# shellcheck disable=SC2054 # --chmod 的取值本身带逗号
RSYNC=(rsync -a --chmod=D755,F644 --rsync-path="$RSYNC_PATH")

# ── 4. 安装包先到：站点上线时它链接的文件必须已经在 ───────────────────
if [ -n "$INSTALLER_FILES" ]; then
  step "上传安装包到 $REMOTE_ROOT/downloads（大文件可断点续传）"
  # shellcheck disable=SC2086 # 文件名由 release-manifest.mjs 校验过，只含 [A-Za-z0-9._-]
  (cd "$DOWNLOADS" && "${RSYNC[@]}" --partial-dir=.rsync-partial --progress $INSTALLER_FILES "$HOST:$REMOTE_ROOT/downloads/")
else
  step "清单里没有安装包：页面显示「即将发布」，跳过上传"
fi

# ── 5. 站点：传到 .site-new，再改名替换 ────────────────────────────────
step "上传站点到 $REMOTE_ROOT/.site-new 并替换 $REMOTE_ROOT/site（上一版留在 site.prev）"
# 已有站点时，未变的文件做硬链接，不重复传输。
LINK_DEST=()
[ "$SITE_EXISTS" != yes ] || LINK_DEST=(--link-dest="$REMOTE_ROOT/site/")
"${RSYNC[@]}" --delete ${LINK_DEST[@]+"${LINK_DEST[@]}"} "$SITE/dist/" "$HOST:$REMOTE_ROOT/.site-new/"
remote "$REMOTE_ROOT" <<'EOF'
set -euo pipefail
root="$1"
[ -f "$root/.site-new/index.html" ] || { echo "上传的站点缺 index.html" >&2; exit 1; }
# 两次 mv 之间站点目录短暂不存在（毫秒级）；上一版保留为 site.prev，回滚见 runbook.md。
rm -rf "$root/site.prev"
if [ -d "$root/site" ]; then mv "$root/site" "$root/site.prev"; fi
mv "$root/.site-new" "$root/site"
EOF

# ── 6. 清单最后到 ──────────────────────────────────────────────────────
step "上传 releases.json"
"${RSYNC[@]}" "$MANIFEST" "$HOST:$REMOTE_ROOT/downloads/releases.json"

# ── 7. nginx ───────────────────────────────────────────────────────────
if [ "$SKIP_NGINX" = 0 ]; then
  if [ "$MODE" = container ]; then
    step "nginx（容器 zt-nginx）：放置配置 → nginx -t → 启动或重载"
    "${RSYNC[@]}" "$DEPLOY_DIR/nginx/ztsgai.conf" "$HOST:$REMOTE_ROOT/nginx/conf.d/ztsgai.conf.new"
    "${RSYNC[@]}" "$DEPLOY_DIR/docker-compose.yml" "$HOST:$REMOTE_ROOT/docker-compose.yml"
    remote "$REMOTE_ROOT" <<'EOF'
set -euo pipefail
root="$1"
conf="$root/nginx/conf.d/ztsgai.conf"
compose=(docker compose -f "$root/docker-compose.yml")
backup=""
if [ -f "$conf" ]; then backup="$conf.bak-$(date +%Y%m%d%H%M%S)"; cp -p "$conf" "$backup"; fi
mv "$conf.new" "$conf"
restore() {
  if [ -n "$backup" ]; then cp -p "$backup" "$conf"; echo "已恢复上一份配置 $backup" >&2
  else rm -f "$conf"; fi
}
# 用一次性容器按同样的挂载测配置，不碰正在服务的 zt-nginx。
if ! "${compose[@]}" run --rm --no-deps -T nginx nginx -t; then restore; exit 1; fi
owner="$(docker inspect -f '{{ index .Config.Labels "com.docker.compose.project" }}' zt-nginx 2>/dev/null || true)"
if [ -n "$owner" ] && [ "$owner" != ztsgai ]; then
  echo "zt-nginx 仍属于旧 compose 项目「$owner」：先按 runbook.md 第 3 步停掉旧服务，再重跑" >&2
  restore; exit 1
fi
"${compose[@]}" up -d
docker exec zt-nginx nginx -t
docker exec zt-nginx nginx -s reload
EOF
  else
    step "nginx（宿主）：放置配置 → nginx -t → systemctl reload nginx"
    "${RSYNC[@]}" "$DEPLOY_DIR/nginx/ztsgai.conf" "$HOST:/etc/nginx/conf.d/ztsgai.conf.new"
    remote <<'EOF'
set -euo pipefail
conf=/etc/nginx/conf.d/ztsgai.conf
backup=""
if [ -f "$conf" ]; then backup="$conf.bak-$(date +%Y%m%d%H%M%S)"; cp -p "$conf" "$backup"; fi
mv "$conf.new" "$conf"
if ! nginx -t; then
  if [ -n "$backup" ]; then cp -p "$backup" "$conf"; else rm -f "$conf"; fi
  echo "nginx -t 失败，已恢复原配置" >&2; exit 1
fi
systemctl reload nginx
EOF
  fi
fi

# ── 8. 校验 ────────────────────────────────────────────────────────────
if [ "$SKIP_VERIFY" = 1 ]; then
  printf '\n✓ 已上传（未校验）：%s:%s\n' "$HOST" "$REMOTE_ROOT"
  exit 0
fi
step "校验 $BASE_URL"
host_name="${BASE_URL#https://}"; host_name="${host_name%%/*}"
CURL=(curl -sS --max-time 30)
[ -z "$RESOLVE_IP" ] || CURL+=(--resolve "$host_name:443:$RESOLVE_IP" --resolve "$host_name:80:$RESOLVE_IP")
failures=0
# check <url> <期望状态码> <期望 Content-Type 前缀> [期望 Content-Length] [期望 Content-Disposition]
check() {
  local url="$1" want_code="$2" want_type="$3" want_length="${4:-}" want_disposition="${5:-}" headers code type length disposition
  headers="$("${CURL[@]}" -o /dev/null -D - -I "$url" | tr -d '\r')" || { printf '  ✗ %s 请求失败\n' "$url"; failures=$((failures + 1)); return; }
  code="$(printf '%s\n' "$headers" | awk 'toupper($1) ~ /^HTTP/ {c=$2} END {print c}')"
  type="$(printf '%s\n' "$headers" | awk -F': ' 'tolower($1)=="content-type" {print $2}' | tail -1)"
  length="$(printf '%s\n' "$headers" | awk -F': ' 'tolower($1)=="content-length" {print $2}' | tail -1)"
  disposition="$(printf '%s\n' "$headers" | awk -F': ' 'tolower($1)=="content-disposition" {print $2}' | tail -1)"
  if [ "$code" != "$want_code" ] || [ "${type#"$want_type"}" = "$type" ] \
    || { [ -n "$want_length" ] && [ "$length" != "$want_length" ]; } \
    || { [ -n "$want_disposition" ] && [ "$disposition" != "$want_disposition" ]; }; then
    printf '  ✗ %s → %s %s %s %s（期望 %s %s %s %s）\n' "$url" "$code" "$type" "$length" "$disposition" \
      "$want_code" "$want_type" "$want_length" "$want_disposition"
    failures=$((failures + 1))
  else
    printf '  ✓ %s → %s %s %s\n' "$url" "$code" "$type" "$length"
  fi
}
check "$BASE_URL/" 200 text/html
check "$BASE_URL/favicon.ico" 200 image/
check "$BASE_URL/downloads/releases.json" 200 application/json
redirect="$("${CURL[@]}" -o /dev/null -w '%{http_code} %{redirect_url}' "http://$host_name/")" || redirect="请求失败"
if [ "$redirect" = "301 $BASE_URL/" ]; then printf '  ✓ http://%s/ → %s\n' "$host_name" "$redirect"
else printf '  ✗ http://%s/ → %s（期望 301 %s/）\n' "$host_name" "$redirect" "$BASE_URL"; failures=$((failures + 1)); fi
remote_manifest="$("${CURL[@]}" "$BASE_URL/downloads/releases.json")" || remote_manifest=""
if [ "$remote_manifest" = "$(cat "$MANIFEST")" ]; then printf '  ✓ 线上 releases.json 与本地一致\n'
else printf '  ✗ 线上 releases.json 与本地不同\n'; failures=$((failures + 1)); fi
while IFS=$'\t' read -r file size; do
  [ -n "$file" ] || continue
  case "$file" in
    *.dmg) mime=application/x-apple-diskimage ;;
    *.exe) mime=application/vnd.microsoft.portable-executable ;;
    *) die "清单里出现未知类型的文件 $file" ;;
  esac
  check "$BASE_URL/downloads/$file" 200 "$mime" "$size" attachment
  check "$BASE_URL/downloads/$file.sha256" 200 text/plain
done <<EOF
$RELEASED
EOF

if [ "$failures" -gt 0 ]; then die "$failures 项校验失败（站点与安装包已上传；回滚见 runbook.md「回滚」）"; fi
printf '\n✓ 发布完成：%s\n' "$BASE_URL"
