#!/usr/bin/env bash
# 一条命令发布智通数工AI：Windows 包（GitHub Actions）+ Mac 包（本机）→ 登记进门户清单 → 部署 ztsgai.com。
#
# 在用户的 Apple Silicon Mac 上、master 分支执行（bash 3.2 可用）。依赖 git、pnpm、node、gh（已登录）、rsync、ssh；
# 不含任何凭据：gh 用本机登录，ssh 用 ~/.ssh/config 里的别名。流程说明见 zhitong/RELEASE.md。
#   bash zhitong/scripts/release.sh <版本> [选项]          版本如 1.0.1（对外 v1.0.1，可带前缀 v）
#
# 选项：
#   --ssh ALIAS        门户服务器的 ssh 别名，默认 zt-prod
#   --skip-mac         不打 Mac 包（清单里 mac-arm64 留空，页面显示「即将发布」）
#   --skip-win         不打 Windows 包（同上，win-x64 留空）
#   --skip-deploy      登记并推送 master 后不部署门户
#   --no-tag           不推 tag，改用 gh workflow run 在 master 上手动触发（workflow 建 Release v<版本>）
#   --win-exe PATH     不用 Actions：直接登记本机已有的 Windows 安装包（Windows 机器上打好拷过来的）
#   --run-id ID        指定 Windows 打包运行（续跑时自动查找不到才需要）
#   --notes-file FILE  新版本的更新说明，每行一条，写进 releases.json 的 notes；不给则沿用上一版并警告
#   --win-timeout MIN  等 Windows 运行的上限分钟数，默认 120
#   --from STEP        从某一步续跑：mac | win | stage | deploy（已 stage 的安装包不重复打包）
#   --dry-run          只打印将执行的命令；只读检查照常执行，未通过时只提示不退出
#
# 步骤：预检 → trigger 推 tag v<版本> 触发 Windows 打包 → mac 本机打 DMG 并 stage → win 等 Actions、下载 exe 并 stage
#       → stage 核对清单、提交 release(zhitong): v<版本> 并推 master → deploy 运行 deploy.sh → 打印文件、sha256 与链接。
# 中间产物与续跑记录在 zhitong/portal/downloads/.release/v<版本>/（git 忽略）。
# 环境变量（一般不用设）：ZT_RELEASE_POLL_SECONDS 轮询间隔（30）、ZT_RELEASE_PROGRESS_SECONDS 进度行间隔（300）、
#   ZT_RELEASE_LOOKUP_TRIES / ZT_RELEASE_LOOKUP_SECONDS 触发后查找运行的次数与间隔（18 × 10 秒）。
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
# shellcheck source-path=SCRIPTDIR source=release-lib.sh
. "$SCRIPT_DIR/release-lib.sh"

WORKFLOW=zhitong-windows-installer.yml
MANIFEST_REL=zhitong/portal/site/public/downloads/releases.json
MANIFEST_TOOL=zhitong/portal/deploy/release-manifest.mjs
STATE_TOOL=zhitong/scripts/release-state.mjs
DEPLOY=zhitong/portal/deploy/deploy.sh
DWG2DXF=zhitong/plugins/tool-cad/bin/darwin-arm64/dwg2dxf
DOWNLOADS=zhitong/portal/downloads
SITE_URL=https://ztsgai.com
POLL_SECONDS="${ZT_RELEASE_POLL_SECONDS:-30}"
PROGRESS_SECONDS="${ZT_RELEASE_PROGRESS_SECONDS:-300}"
LOOKUP_TRIES="${ZT_RELEASE_LOOKUP_TRIES:-18}"
LOOKUP_SECONDS="${ZT_RELEASE_LOOKUP_SECONDS:-10}"

if ! rl_parse_args "$@"; then exit 2; fi
if [ "$REL_HELP" = 1 ]; then awk 'NR > 1 && /^#/ { sub(/^# ?/, ""); print; next } NR > 1 { exit }' "$0"; exit 0; fi
V="$REL_VERSION"
TAG="v$V"
STATE_DIR="$DOWNLOADS/.release/$TAG"
cd "$ROOT"

say() { printf '%s\n' "$*"; }
step() { printf '\n▶ %s\n' "$*"; }
die() { printf '✗ %s\n' "$*" >&2; exit 1; }
dry() { [ "$REL_DRY_RUN" = 1 ]; }
# run <命令…> —— 执行；dry-run 时只打印。
run() { if dry; then printf '+ %s\n' "$(rl_quote "$@")"; else "$@"; fi; }
# fail <原因> —— 预检未通过：正常运行时退出，dry-run 时提示后继续，以便看完整条路径。
fail() { if dry; then printf '! 预检未通过（dry-run 继续）：%s\n' "$*"; else die "$*"; fi; }
save_state() { dry || { mkdir -p "$STATE_DIR" && printf '%s\n' "$2" >"$STATE_DIR/$1"; }; }
load_state() { if [ -f "$STATE_DIR/$1" ]; then cat "$STATE_DIR/$1"; fi; }
staged() { node "$STATE_TOOL" staged "$1" --version "$V" >/dev/null 2>&1; }

CURRENT=preflight
HINT=''
on_exit() {
  local code=$?
  if [ "$code" = 0 ] || [ "$CURRENT" = "done" ]; then return 0; fi
  if [ "$CURRENT" = preflight ]; then
    printf '\n处理上面的问题后重跑同一条命令。\n' >&2
  else
    printf '\n在「%s」一步失败。修好后从这一步续跑：\n  %s\n' "$CURRENT" "${HINT:-$(rl_resume_cmd "$CURRENT")}" >&2
  fi
}
trap on_exit EXIT

# 是否还需要在本机打 Mac 包（没 stage、也没有可复用的已放置文件）。
mac_build_needed() {
  rl_should_run mac && ! staged mac-arm64 && [ ! -f "$DOWNLOADS/ztsgai-$V-mac-arm64.dmg" ]
}

# 是否要用 gh（触发、等待或下载 Windows 运行）。
needs_gh() {
  rl_should_run trigger || { rl_should_run win && [ -z "$REL_WIN_EXE" ]; }
}

# ── 预检 ───────────────────────────────────────────────────────────────
preflight() {
  step "预检（v$V）"
  dry && say "（dry-run：只打印命令）"
  local tools='git node' tool
  if needs_gh; then tools="$tools gh"; fi
  if rl_should_run mac; then tools="$tools pnpm"; fi
  if rl_should_run deploy; then tools="$tools rsync ssh curl npm"; fi
  for tool in $tools; do command -v "$tool" >/dev/null 2>&1 || fail "本机缺少 $tool（见 zhitong/RELEASE.md「一次性设置」）"; done

  node "$STATE_TOOL" check-version "$V" || fail "版本号不能比 releases.json 里的旧"
  if [ -n "$REL_NOTES_FILE" ] && [ ! -f "$REL_NOTES_FILE" ]; then fail "--notes-file $REL_NOTES_FILE 不存在"; fi
  if [ -n "$REL_WIN_EXE" ] && [ ! -f "$REL_WIN_EXE" ]; then fail "--win-exe $REL_WIN_EXE 不存在"; fi

  local branch dirty
  branch="$(git symbolic-ref --short -q HEAD || true)"
  [ "$branch" = master ] || fail "当前分支是 ${branch:-（detached HEAD）}，发布只从 master 发：git switch master && git pull --ff-only"
  if [ "$REL_FROM" = trigger ]; then
    dirty="$(git status --porcelain)"
    [ -z "$dirty" ] || fail "工作树不干净（发布的包要与提交一致）：
$dirty"
  else
    dirty="$(git status --porcelain -- . ":(exclude)$MANIFEST_REL")"
    [ -z "$dirty" ] || fail "工作树除 releases.json 外还有改动：
$dirty"
  fi
  run git fetch --quiet origin master
  if [ "$REL_FROM" = trigger ]; then
    [ "$(git rev-parse HEAD)" = "$(git rev-parse origin/master)" ] \
      || fail "本地 master 与 origin/master 不一致：先 git pull --ff-only；本地提交要走 PR 合进 master"
  else
    git merge-base --is-ancestor origin/master HEAD \
      || fail "origin/master 有本地没有的提交：git pull --rebase origin master 后再续跑"
  fi

  if needs_gh; then
    if dry; then run gh auth status; else gh auth status >/dev/null 2>&1 || fail "gh 未登录：gh auth login"; fi
  fi
  if rl_should_run trigger; then
    if [ "$REL_NO_TAG" = 0 ]; then
      local local_tag remote_tag
      local_tag="$(git rev-parse -q --verify "refs/tags/$TAG^{commit}" || true)"
      if [ -n "$local_tag" ] && [ "$local_tag" != "$(git rev-parse HEAD)" ]; then
        fail "本地已有 tag $TAG 且不指向 HEAD：换一个版本号，或删掉本地 tag（git tag -d $TAG）"
      fi
      if dry; then run git ls-remote --tags origin "refs/tags/$TAG"
      else
        remote_tag="$(git ls-remote --tags origin "refs/tags/$TAG")" || die "git ls-remote origin 失败"
        [ -z "$remote_tag" ] || fail "远端已有 tag $TAG：这个版本已经触发过。上次中断的续跑用 $(rl_resume_cmd mac)；要在 master 上重新打 Windows 包用 --no-tag；否则换一个版本号"
      fi
    else
      local assets
      if dry; then run gh release view "$TAG" --json assets --jq '.assets[].name'
      elif assets="$(gh release view "$TAG" --json assets --jq '.assets[].name' 2>/dev/null)"; then
        case "$assets" in *"ztsgai-$V-win-x64-setup.exe"*) fail "Release $TAG 已经有 Windows 安装包；已发布的文件不换内容，换一个版本号" ;; esac
      fi
    fi
  fi
  if mac_build_needed; then
    { [ "$(uname -s)" = Darwin ] && [ "$(uname -m)" = arm64 ]; } || fail "Mac 包只能在 Apple Silicon Mac 上打（当前 $(uname -s) $(uname -m)）；别的机器上用 --skip-mac"
    [ -x "$DWG2DXF" ] || fail "缺少 $DWG2DXF：先运行 sh zhitong/plugins/tool-cad/scripts/build-dwg2dxf.sh \"\$HOME/.cache/zhitong/dwg2dxf-build\""
  fi
  if rl_should_run deploy; then
    run ssh -o BatchMode=yes -o ConnectTimeout=15 "$REL_SSH" true || fail "ssh $REL_SSH 不通（需要 ~/.ssh/config 别名与免密登录）"
  fi
  say "  预检完成"
}

# ── Windows 运行查找与等待 ─────────────────────────────────────────────
# lookup_run [提交] [触发时间] —— 把匹配的运行 id 写进 RUN_ID；dry-run 时只打印查询命令。
lookup_run() {
  if dry; then
    run gh run list --workflow "$WORKFLOW" --limit 30 --json databaseId,headSha,status,createdAt,displayTitle,event,headBranch
    RUN_ID='<运行id>'
  else
    RUN_ID="$(find_run "$@")"
  fi
}

# find_run [提交] [触发时间] —— 输出匹配的运行 id；查不到时报错退出（在子 shell 里调用）。
find_run() {
  local sha="${1:-}" since="${2:-}" try=1 json id args
  args=(pick-run --version "$V")
  if [ -n "$sha" ]; then args+=(--sha "$sha"); fi
  if [ -n "$since" ]; then args+=(--since "$since"); fi
  while [ "$try" -le "$LOOKUP_TRIES" ]; do
    json="$(gh run list --workflow "$WORKFLOW" --limit 30 --json databaseId,headSha,status,createdAt,displayTitle,event,headBranch)" \
      || die "gh run list 失败"
    if id="$(printf '%s' "$json" | node "$STATE_TOOL" "${args[@]}")"; then printf '%s\n' "$id"; return 0; fi
    try=$((try + 1))
    sleep "$LOOKUP_SECONDS"
  done
  die "在 Actions 里找不到 $TAG 的「zhitong · Windows installer」运行${sha:+（提交 $sha）}；到仓库 Actions 页确认它已启动，再用 --run-id <运行 id> 续跑"
}

# wait_run <运行 id> —— 等运行结束；成功返回，失败或超时退出。每 PROGRESS_SECONDS 秒打印一行进度。
wait_run() {
  local id="$1" start now last=0 info status conclusion current minutes errors=0
  step "等待 Windows 运行 $id（上限 $REL_WIN_TIMEOUT 分钟，每 $((PROGRESS_SECONDS / 60)) 分钟报告一次）"
  if dry; then
    printf '+ %s   （每 %s 秒轮询，直到 status=completed）\n' "$(rl_quote gh run view "$id" --json status,conclusion,jobs)" "$POLL_SECONDS"
    return 0
  fi
  start="$(date +%s)"
  while :; do
    if ! info="$(gh run view "$id" --json status,conclusion,jobs)"; then
      errors=$((errors + 1))
      [ "$errors" -lt 5 ] || die "连续 5 次 gh run view $id 失败"
      sleep "$POLL_SECONDS"; continue
    fi
    errors=0
    IFS=$'\t' read -r status conclusion current <<EOF
$(printf '%s' "$info" | node "$STATE_TOOL" run-status)
EOF
    now="$(date +%s)"
    minutes=$(((now - start) / 60))
    if [ "$status" = completed ]; then
      [ "$conclusion" = success ] || die "Windows 运行 $id 结束：$conclusion。看日志：gh run view $id --log-failed；只重跑失败的 job：gh run rerun $id --failed，跑完后续跑"
      say "  ✓ 运行 $id 成功（本次等待 $minutes 分钟）"
      return 0
    fi
    if [ "$last" = 0 ] || [ $((now - last)) -ge "$PROGRESS_SECONDS" ]; then
      printf '  [%s] 运行 %s：%s，%s（已等 %s 分钟）\n' "$(date +%H:%M)" "$id" "$status" "$current" "$minutes"
      last="$now"
    fi
    [ $((now - start)) -lt $((REL_WIN_TIMEOUT * 60)) ] \
      || die "等了 $REL_WIN_TIMEOUT 分钟运行 $id 仍是 $status；它在 Actions 上继续跑，结束后续跑（可加 --win-timeout）"
    sleep "$POLL_SECONDS"
  done
}

# ── 各步骤 ─────────────────────────────────────────────────────────────
step_trigger() {
  CURRENT=trigger
  local sha since
  sha="$(git rev-parse HEAD)"
  since="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
  if [ "$REL_NO_TAG" = 0 ]; then
    step "触发 Windows 打包：推送 tag $TAG（$sha）"
    git rev-parse -q --verify "refs/tags/$TAG" >/dev/null || run git tag -a "$TAG" -m "智通数工AI $TAG" "$sha"
    run git push origin "refs/tags/$TAG"
  else
    step "触发 Windows 打包：gh workflow run（master，publish=true）"
    run gh workflow run "$WORKFLOW" --ref master -f "version=$V" -f publish=true
  fi
  save_state trigger-sha "$sha"
  save_state trigger-time "$since"
  HINT="$(rl_resume_cmd mac) --run-id <Actions 页上这次运行的 id>"
  lookup_run "$sha" "$since"
  save_state run-id "$RUN_ID"
  say "  Windows 运行 $RUN_ID 已启动（约 40–60 分钟）；同时在本机打 Mac 包"
  HINT=''
}

# stage_file <平台> <安装包> —— 放进 downloads 并登记进 releases.json。
stage_file() {
  run node "$STATE_TOOL" prepare --version "$V" ${REL_NOTES_FILE:+--notes-file "$REL_NOTES_FILE"}
  run node "$MANIFEST_TOOL" stage "$1" "$2"
}

step_mac() {
  CURRENT=mac
  local published="$DOWNLOADS/ztsgai-$V-mac-arm64.dmg" log="$STATE_DIR/mac-build.log" dmg
  step "Mac 安装包"
  if staged mac-arm64; then say "  已 stage：$published，跳过打包"; return 0; fi
  if [ -f "$published" ]; then
    say "  复用已放置的 $published（不重新打包）"
    stage_file mac-arm64 "$published"
    return 0
  fi
  run pnpm install --frozen-lockfile
  run pnpm run package:desktop:mac:arm64:unsigned --check
  step "打包 DMG（首次约 20–40 分钟；日志 $log）"
  if dry; then
    printf '+ %s 2>&1 | tee %s\n' "$(rl_quote pnpm run package:desktop:mac:arm64:unsigned)" "$(rl_quote "$log")"
    dmg='<日志末行 DMG: 的路径>'
  else
    mkdir -p "$STATE_DIR"
    pnpm run package:desktop:mac:arm64:unsigned 2>&1 | tee "$log"
    dmg="$(rl_dmg_from_log "$log")" || die "打包日志里没有「DMG: …」行：$log"
    [ -f "$dmg" ] || die "DMG 不存在：$dmg"
  fi
  stage_file mac-arm64 "$dmg"
}

step_win() {
  CURRENT=win
  local published="$DOWNLOADS/ztsgai-$V-win-x64-setup.exe" dir="$STATE_DIR/win" id exe tag_sha
  step "Windows 安装包"
  if staged win-x64; then say "  已 stage：$published，跳过下载"; return 0; fi
  if [ -n "$REL_WIN_EXE" ]; then
    say "  登记本机安装包 $REL_WIN_EXE（不经过 Actions）"
    if [ -f "$REL_WIN_EXE.sha256" ]; then run node "$STATE_TOOL" verify-sidecar "$REL_WIN_EXE"; fi
    stage_file win-x64 "$REL_WIN_EXE"
    return 0
  fi
  if [ -f "$published" ]; then
    say "  复用已放置的 $published（不重新下载）"
    stage_file win-x64 "$published"
    return 0
  fi
  id="${REL_RUN_ID:-$(load_state run-id)}"
  if [ -z "$id" ]; then
    tag_sha="$(git rev-parse -q --verify "refs/tags/$TAG^{commit}" || true)"
    lookup_run "${tag_sha:-$(load_state trigger-sha)}" ""
    id="$RUN_ID"
  fi
  HINT="$(rl_resume_cmd win "$id")"
  wait_run "$id"
  step "下载运行 $id 的产物 ztsgai-$V-win-x64-setup"
  run rm -rf "$dir"
  run mkdir -p "$dir"
  if ! run gh run download "$id" -n "ztsgai-$V-win-x64-setup" -D "$dir"; then
    say "  运行产物取不到（只保留 7 天），改从 Release $TAG 下载"
    run gh release download "$TAG" -p "ztsgai-$V-win-x64-setup.exe*" -D "$dir"
  fi
  exe="$dir/ztsgai-$V-win-x64-setup.exe"
  run node "$STATE_TOOL" verify-sidecar "$exe"
  stage_file win-x64 "$exe"
  run rm -rf "$dir"
  HINT=''
}

step_stage() {
  CURRENT=stage
  local platform others
  step "登记：核对清单并提交 $MANIFEST_REL"
  run node "$MANIFEST_TOOL" verify
  for platform in mac-arm64 win-x64; do
    case "$platform" in mac-arm64) [ "$REL_SKIP_MAC" = 0 ] || continue ;; win-x64) [ "$REL_SKIP_WIN" = 0 ] || continue ;; esac
    if ! dry && ! staged "$platform"; then
      node "$STATE_TOOL" staged "$platform" --version "$V" || true
      HINT="$(rl_resume_cmd "$([ "$platform" = mac-arm64 ] && echo mac || echo win)")"
      die "$platform 还没有 stage 成 $TAG"
    fi
  done
  others="$(git status --porcelain --untracked-files=no -- . ":(exclude)$MANIFEST_REL")"
  [ -z "$others" ] || say "  注意：打包改动了这些跟踪文件，不随发布提交（检查后自行处理）：
$others"
  if dry || ! git diff --quiet HEAD -- "$MANIFEST_REL"; then
    run git add -- "$MANIFEST_REL"
    run git commit -m "release(zhitong): $TAG" -- "$MANIFEST_REL"
  else
    say "  releases.json 已在提交里"
  fi
  if dry || [ "$(git rev-parse HEAD)" != "$(git rev-parse origin/master)" ]; then
    run git push origin master
  fi
}

step_deploy() {
  CURRENT=deploy
  step "部署门户：deploy.sh $REL_SSH"
  run bash "$DEPLOY" "$REL_SSH"
}

finish() {
  CURRENT="done"
  local url
  step "发布 $TAG"
  if dry; then say "（dry-run：没有执行任何改动）"; return 0; fi
  node "$STATE_TOOL" summary --version "$V" --site-url "$SITE_URL"
  if url="$(gh release view "$TAG" --json url --jq .url 2>/dev/null)"; then say "Release：$url"
  else say "Release：取不到（gh release view $TAG）"; fi
  if ! rl_should_run deploy; then say "门户未部署；部署：bash $DEPLOY $REL_SSH"; fi
}

preflight
if rl_should_run trigger; then step_trigger; fi
if rl_should_run mac; then step_mac; fi
if rl_should_run win; then step_win; fi
if rl_should_run stage; then step_stage; fi
if rl_should_run deploy; then step_deploy; fi
finish
