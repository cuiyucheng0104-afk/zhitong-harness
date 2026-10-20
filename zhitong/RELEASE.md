# 发布流程

改完代码 → 合进 `master` → 在 Mac 上跑一条命令：Windows 包由 GitHub Actions 打，Mac 包在本机打，两个包登记进门户清单并部署到 https://ztsgai.com 的下载位置。脚本是 [scripts/release.sh](scripts/release.sh)，`--help` 看全部选项。首次上线门户（停旧系统、装 nginx）不在这里，见 [portal/deploy/runbook.md](portal/deploy/runbook.md) 第 3 节。

## 版本号

- 对外版本 `v1.0.x`：tag、GitHub Release、安装包文件名 `ztsgai-1.0.x-mac-arm64.dmg` / `ztsgai-1.0.x-win-x64-setup.exe`、网站显示的版本。每次发布用一个新号，**用过的号不再用**：安装包有 30 天缓存，`release-manifest.mjs stage` 拒绝用不同内容覆盖同名文件。可以带预发布后缀（`1.0.2-rc.1`），Release 会标成 prerelease。
- 应用内版本保持 `0.2.1-rc.2`（`apps/desktop/package.json`，与上游同步），清单里记为 `base`，「关于」里显示的是它。合并上游改了这个版本时它随之变化，不用手动处理。

## 分支模型

| 分支 | 用途 |
|---|---|
| `master` | 产品分支。只通过 PR 合入；发布只从它发；唯一的直推是 `release.sh` 提交的 `release(zhitong): v<版本>`（只改 `releases.json`） |
| `feat/<主题>`、`fix/<主题>` | 从 `origin/master` 建，改完开 PR 到 `master` |
| `sync/upstream-<日期>` | 合并上游 DeepSeek Harness，见下文 |

## 日常发布（一条命令）

```sh
git switch master && git pull --ff-only
bash zhitong/scripts/release.sh 1.0.1 --notes-file ~/notes-1.0.1.txt
```

`--notes-file` 是网站上显示的更新说明，每行一条；不给就沿用上一版的说明（脚本会警告）。整条约 60–90 分钟，Windows 与 Mac 并行：

| 步骤 | 做什么 | 耗时 |
|---|---|---|
| 预检 | 版本号格式且不比清单旧；在 `master`、工作树干净、与 `origin/master` 一致；`gh auth status`；tag 不存在；本机是 Apple Silicon 且有 dwg2dxf；`ssh -o BatchMode=yes zt-prod true` | 几秒 |
| trigger | `git tag -a v1.0.1` 并推送，workflow「zhitong · Windows installer」开始打包；记下运行 id | 1 分钟 |
| mac | `pnpm install --frozen-lockfile` → `package:desktop:mac:arm64:unsigned --check` → 打包 → 取日志末行 `DMG:` → `release-manifest.mjs stage mac-arm64`（清单版本先改成 1.0.1） | 20–40 分钟 |
| win | 等运行结束（每 5 分钟一行进度，上限 2 小时）→ 下载产物 `ztsgai-1.0.1-win-x64-setup` → 核对 `.sha256` → `stage win-x64` | Actions 共 40–60 分钟 |
| stage | `release-manifest.mjs verify` → 提交 `release(zhitong): v1.0.1` → `git push origin master` | 几秒 |
| deploy | `bash zhitong/portal/deploy/deploy.sh zt-prod`：构建门户、上传安装包、替换站点、curl 校验 | 几分钟 |

结束时打印版本、两个文件名与 sha256、网站下载地址和 Release 地址。Release 由 workflow 建，只附 Windows 安装包；网站上两个都有。

**失败即停**，最后一行给出续跑命令（`--from mac|win|stage|deploy`）。续跑时已 stage 的安装包不重复打包或下载；运行 id 记在 `zhitong/portal/downloads/.release/v<版本>/`。`--dry-run` 只打印将执行的命令。其它选项：`--skip-mac` / `--skip-win`（该平台在新版本下显示「即将发布」）、`--skip-deploy`、`--ssh <别名>`、`--no-tag`（不推 tag，用 `gh workflow run` 在 `master` 上触发）、`--win-exe <路径>`（不用 Actions，登记在 Windows 机器上按 [INSTALL.md](INSTALL.md) 第三部分打好的 exe）。

## 只改网站，不发包

门户文字、样式在 `zhitong/portal/site/`，照常走 PR 合进 `master`，然后：

```sh
git switch master && git pull --ff-only
bash zhitong/portal/deploy/deploy.sh zt-prod
```

不要手改 `releases.json` 的 `version`、`file`、`sha256`、`size`：清单与安装包不一致时 deploy.sh 在上传前失败。

## 热修

从 `origin/master` 建 `fix/<主题>` → PR → 合入 → `release.sh 1.0.<下一个号>`。只有一个平台有问题也两个都发：新版本下没发的平台会显示「即将发布」，旧版本的文件不在页面上。

## 回滚

- **网站内容**（ECS）：`cd /opt/ztsgai && mv site site.bad && mv site.prev site && rm -rf site.bad`。只保留上一版。
- **网站回到上一版安装包**（Mac）：`git revert <release(zhitong): v1.0.1 的提交>`，推到 `master`；确认上一版的安装包与 `.sha256` 在本机 `zhitong/portal/downloads/`（没有就 `rsync zt-prod:/opt/ztsgai/downloads/ztsgai-1.0.0-\* zhitong/portal/downloads/`），再 `bash zhitong/portal/deploy/deploy.sh zt-prod`。服务器上的旧文件从不删除，旧链接一直可用。
- **GitHub Release**：`gh release edit v1.0.1 --draft`（隐藏）或 `gh release delete v1.0.1 --yes`（保留 tag）。v1.0.1 这个号作废，修好后发 v1.0.2。

## 合并上游

```sh
git remote add upstream https://github.com/deepseek-ai/deepseek-harness.git   # 只做一次
git fetch upstream
git switch -c sync/upstream-20261101 origin/master
git merge upstream/master
```

冲突与核对：[STATUS.md](STATUS.md) 的「W9 上游改动」「W11 上游改动」「集成提交」列出我们改过的每个上游文件，代码里都有 `zhitong increment` 注释（`git grep -n 'zhitong increment'`）。逐项确认上游改动后我们的改动还在、还对；上游动了这些文件就更新那几张表。`.github/workflows/` 里上游的 CI 在这个 fork 里只手动触发（STATUS「W13」），合并后确认没有被改回自动触发，否则会消耗 Actions 额度。验证至少跑 `node --test zhitong/scripts/tests/*.test.mjs`、各插件的 `pnpm vitest run` 与 `pnpm run package:desktop:mac:arm64:unsigned --check`，然后开 PR 到 `master`，合入后照常发布。

## 一次性设置（Mac）

1. 打包环境：按 [INSTALL.md](INSTALL.md) 第二部分装 Xcode 命令行工具、Node 24、`corepack enable`，克隆后 `git switch master`。
2. dwg2dxf：`sh zhitong/plugins/tool-cad/scripts/build-dwg2dxf.sh "$HOME/.cache/zhitong/dwg2dxf-build"`（git 忽略，新克隆要重做）。
3. GitHub CLI：`brew install gh` → `gh auth login -s workflow`（GitHub.com、HTTPS、浏览器登录）→ `gh auth setup-git`（git push 用同一个登录）→ `gh auth status`。`workflow` 权限用于推送改了 `.github/workflows/` 的提交（合并上游时会有）。
4. ssh 别名：`~/.ssh/config` 里加

   ```text
   Host zt-prod
     HostName <ECS 公网 IP>
     User root
     IdentityFile ~/.ssh/<私钥文件>
   ```

   `ssh -o BatchMode=yes zt-prod true` 不提示密码即可。
5. rsync：macOS 15 起自带的是 openrsync，deploy.sh 报选项不认识时 `brew install rsync` 并重开终端。
6. GitHub 仓库的 Actions 可用：私有仓 Windows 分钟按 2 倍计费，一次发布约占 80–120 分钟额度。额度用完时在 Windows 机器上打包，拷到 Mac 后 `release.sh <版本> --win-exe <exe 路径>`。
7. 先 `bash zhitong/scripts/release.sh <版本> --dry-run` 看一遍。

## 常见失败

| 现象 | 处理 |
|---|---|
| 工作树不干净 / 与 `origin/master` 不一致 | 改动走 PR；`git pull --ff-only`。发布只发已合入 `master` 的提交 |
| 远端已有 tag `v<版本>` | 上次中断：按提示 `--from mac` 续跑；否则换版本号 |
| 找不到 Windows 运行 | 到仓库 Actions 页看是否启动（Actions 是否启用、额度）；找到后 `--from mac --run-id <id>` |
| Windows 运行失败 | `gh run view <id> --log-failed`；偶发问题 `gh run rerun <id> --failed` 后 `--from win --run-id <id>`；代码问题修好合入后发新版本 |
| 等待超时 | 运行仍在 Actions 上跑，结束后 `--from win` |
| 运行产物过期（7 天） | 脚本自动改从 Release `v<版本>` 下载 |
| Mac 打包失败 | 看 `zhitong/portal/downloads/.release/v<版本>/mac-build.log` 与 `DESKTOP_PACKAGING_RECORD` 目录，INSTALL.md 第二部分第 4 节；修好后 `--from mac` |
| `stage` 报 already exists with different contents | 这个版本号已经放过别的文件，换版本号 |
| `git push origin master` 被拒（期间有人合入） | `git pull --rebase origin master` 后 `--from stage` |
| deploy.sh 失败 | 见 runbook.md；修好后 `--from deploy` |
