# 门户 ztsgai.com 上线与安装包发布 runbook

在旧生产 ECS（`zhitong-prod-web`，ssh 别名 `zt-prod`）上把旧系统的入口换成门户网站，并发布 v1.0.0 安装包。命令分两类：标「Mac」的在你本机仓库根目录执行，标「ECS」的在服务器上以 root 执行（`ssh zt-prod` 或 `pssh`）。

本目录的文件：

| 文件 | 作用 |
|---|---|
| `nginx/ztsgai.conf` | 站点配置：80 跳 443（证书续期路径除外）、www 跳裸域、`/` 静态站、`/downloads/` 安装包 |
| `docker-compose.yml` | 容器模式的 nginx（容器名沿用 `zt-nginx`，项目名 `ztsgai`） |
| `deploy.sh` | Mac 上一键发布：构建 → 上传安装包 → 替换站点 → 上传清单 → 装配置并 `nginx -t` → 重载 → curl 校验 |
| `release-manifest.mjs` | 把打好的安装包改名放进 `zhitong/portal/downloads/`，写 `.sha256`，更新 `site/public/downloads/releases.json`；`verify` 子命令核对三者一致 |

服务器布局：

```text
/opt/ztsgai/site/            门户 dist（deploy.sh 整目录替换）
/opt/ztsgai/site.prev/       上一版站点（回滚用）
/opt/ztsgai/downloads/       ztsgai-<版本>-mac-arm64.dmg、ztsgai-<版本>-win-x64-setup.exe、各自的 .sha256、releases.json
/opt/ztsgai/nginx/conf.d/    容器模式下 zt-nginx 的 conf.d（只有 ztsgai.conf）
/opt/ztsgai/logs/nginx/      容器模式下的访问与错误日志
/opt/ztsgai/docker-compose.yml
/opt/zhitong/nginx/ssl/      旧部署的证书目录，沿用：ztsgai.com.fullchain.cer、ztsgai.com.key
/opt/zhitong/nginx/html/     旧前端静态根；保留，acme.sh 续期把挑战文件写在它的 .well-known/ 下
```

证书文件名取自旧仓 `deploy/deploy.sh` render 的默认值（`TG_SSL_CERT=/etc/nginx/ssl/ztsgai.com.fullchain.cer`、`TG_SSL_KEY=/etc/nginx/ssl/ztsgai.com.key`，容器内 `/etc/nginx/ssl` 挂的就是宿主 `/opt/zhitong/nginx/ssl`）。这是代码里的默认值，不是服务器实查结果，第 1 步要核对。

## 0. 假设与前置检查

假设 DNS 已经把 `ztsgai.com` 与 `www.ztsgai.com` 指向这台 ECS 的公网 IP，域名 ICP 备案已通过（大陆 ECS 上未备案域名的 80/443 会被拦截）。

Mac：

```sh
dig +short ztsgai.com
dig +short www.ztsgai.com
```

两条都应输出 ECS 的公网 IP（旧部署脚本里写的是 `14.103.214.28`，以火山控制台为准）。不一致就先改 DNS，等生效后再继续；DNS 生效前可以给 deploy.sh 加 `--resolve <公网IP>` 校验。

Mac 本机工具：

```sh
node --version     # >= 22.12
rsync --version | head -1
ssh -o BatchMode=yes zt-prod true && echo ssh-ok
```

macOS 15 起 `/usr/bin/rsync` 是 openrsync，若 deploy.sh 报 rsync 选项不认识，`brew install rsync` 后重开终端再跑。`zt-prod` 必须是 `~/.ssh/config` 里的 Host 别名并能免交互登录；`pssh` 只是你本机的封装，deploy.sh 不用它。

## 1. 只读检查旧服务器（ECS）

```sh
docker ps --format '{{.Names}}\t{{.Image}}\t{{.Status}}'
docker compose ls
ls -l /opt/zhitong/nginx/ssl/
openssl x509 -noout -subject -enddate -ext subjectAltName -in /opt/zhitong/nginx/ssl/ztsgai.com.fullchain.cer
crontab -l | grep -i acme
grep -i reloadcmd ~/.acme.sh/ztsgai.com*/ztsgai.com.conf
systemctl list-timers | grep -E 'zt-|acme'
ls /opt/zhitong/app/deploy/nginx/conf.d/
```

要确认的事：

- **证书**：文件名若不是 `ztsgai.com.fullchain.cer` / `ztsgai.com.key`，改 `nginx/ztsgai.conf` 里的 4 行 `ssl_certificate*` 再部署。`subjectAltName` 里没有 `www.ztsgai.com` 时，`https://www.ztsgai.com` 会在跳转前报证书错误：用 `~/.acme.sh/acme.sh --issue -d ztsgai.com -d www.ztsgai.com -w /opt/zhitong/nginx/html` 重签（旧 nginx 还在跑时执行，HTTP-01 挑战由它提供），或者接受 www 不可用。
- **续期重载命令**（`Le_ReloadCmd`）：若是 `docker exec zt-nginx nginx -s reload` 或 `docker restart zt-nginx`，容器模式下原样可用（新容器同名）。宿主模式要改成 `systemctl reload nginx`（第 6 节）。
- **在跑的容器**：旧 compose 项目名是 `zhitong`（`/opt/zhitong/app/deploy/docker-compose.prod.yml`）。有 `app-t<码>` 租户容器、`oo5-prod`（OnlyOffice）时记下来，第 3 步一并处理。
- **conf.d 的真实位置**：旧 `zt-nginx` 挂的是 `/opt/zhitong/app/deploy/nginx/conf.d`（compose 里的 `./nginx/conf.d`），不是 `/opt/zhitong/nginx/conf.d`。门户不改这个目录，回滚时原样可用。

## 2. 选 nginx：容器（推荐）还是宿主

**推荐：容器模式。** 用本目录的 `docker-compose.yml` 新起一个同名 `zt-nginx`（镜像同为 `nginx:1.25-alpine`，项目名 `ztsgai`），配置放 `/opt/ztsgai/nginx/conf.d/`。

不直接沿用旧 compose 里的 `zt-nginx` 并把 conf 塞进它的 conf.d，原因：

1. 旧 conf.d 的 `10-site.conf` 反代 `app:9600`、`engine:8900`。app/engine 停掉后这些主机名解析不到，`nginx -t` 报 `host not found in upstream`，nginx 整个起不来；要沿用就得同时删掉 `10-site.conf`、`00-http-tuning.conf`（它的 `gzip on` 与门户配置重复）。
2. 旧 compose 的 nginx `depends_on: [app]`，挂载里没有 `/opt/ztsgai`。要沿用就得改服务器上的旧 compose 文件。
3. 新容器同名 `zt-nginx`，acme.sh 的重载命令与运维习惯不受影响；旧 compose 与旧 conf.d 一字不动，回滚就是把旧服务重新 `up`。

宿主 nginx 是备选：`apt install nginx`，配置放 `/etc/nginx/conf.d/ztsgai.conf`，`deploy.sh --mode host`。它少一个容器，但要删 Ubuntu 自带的 `sites-enabled/default`（它也声明 80 端口的 `default_server`，`nginx -t` 会报 duplicate default server），并改 acme.sh 的重载命令。

## 3. 上线顺序（首次）

### 3.1 先上传，不停旧服务（Mac）

```sh
bash zhitong/portal/deploy/deploy.sh --skip-nginx --skip-verify zt-prod
```

这一步构建门户，把安装包（若已放置，见第 4 节）与站点传到 `/opt/ztsgai/`，旧 nginx 照常服务。

### 3.2 备份（ECS）

```sh
ts=$(date +%Y%m%d-%H%M%S)
mkdir -p /opt/zhitong/backup/portal-switch-$ts
cd /opt/zhitong/backup/portal-switch-$ts
tar czf nginx-conf.tgz -C /opt/zhitong/app/deploy nginx docker-compose.prod.yml
docker inspect zt-nginx > zt-nginx.inspect.json
crontab -l > crontab.txt
cp -p ~/.acme.sh/ztsgai.com*/ztsgai.com.conf . 2>/dev/null || true
```

数据库：app 停掉后不再写库。停之前按旧 `deploy/README.md`「备份」一节手动跑一次 `zt-mysql-backup.service` 并用 `./deploy.sh backup-status` 确认成功，留一份停机时刻的 dump。

### 3.3 停旧的 app / engine / ocr / nginx（ECS）

**不动** `/opt/zhitong/data`（MySQL 数据目录与 NAS 目录 `nas-data`）。`zt-mysql` 保持运行：迁移脚本（W8）要读旧 `project` 表，每日备份定时器也要连它。

```sh
cd /opt/zhitong/app/deploy
docker compose -f docker-compose.prod.yml stop app engine ocr nginx
docker compose -f docker-compose.prod.yml rm -f app engine ocr nginx
# 若第 1 步看到租户容器：
# docker compose -f docker-compose.prod.yml -f docker-compose.tenants.yml rm -sf app-t3
systemctl disable --now zt-upstream-watchdog.timer
```

`zt-upstream-watchdog` 每 5 分钟探 `/ragapi/health` 并在失败时重载 `zt-nginx`；门户没有这条路径，不停它就会对新容器反复告警与重载。`docker compose down` 会连 `zt-mysql` 一起删，这里不用。

`stop` 之后到下一步完成之前，80/443 没有服务（约一分钟）。

### 3.4 装门户 nginx 并校验（Mac）

```sh
bash zhitong/portal/deploy/deploy.sh --skip-build zt-prod
```

deploy.sh 依次：上传 `ztsgai.conf`（旧的留成 `ztsgai.conf.bak-<时间>`）与 `docker-compose.yml` → 用一次性容器按同样挂载跑 `nginx -t`，失败则恢复旧配置退出 → 若 `zt-nginx` 仍属于旧项目 `zhitong` 则拒绝继续 → `docker compose up -d` → `nginx -s reload` → 从 Mac curl 校验首页、favicon、`/downloads/releases.json`、http→https 跳转、每个安装包的状态码、`Content-Type`、`Content-Length`、`Content-Disposition: attachment` 与 `.sha256`。最后一行是 `✓ 发布完成` 才算上线。

### 3.5 验证续期路径与浏览器（ECS + 浏览器）

```sh
echo ok > /opt/zhitong/nginx/html/.well-known/acme-challenge/portal-check
curl -sS http://ztsgai.com/.well-known/acme-challenge/portal-check    # 期望 ok
rm /opt/zhitong/nginx/html/.well-known/acme-challenge/portal-check
```

浏览器打开 <https://ztsgai.com>：点「获取安装与配置包」，确认版本号、日期、下载按钮、SHA256 链接与「首次打开」提示；未放置安装包的平台应显示「即将发布」。

## 4. 打包与上传安装包（v1.0.0）

文件名与版本：门户发布的是 `ztsgai-1.0.0-mac-arm64.dmg` 与 `ztsgai-1.0.0-win-x64-setup.exe`。桌面版产物版本由 `apps/desktop/package.json`（当前 `0.2.1-rc.2`，与 `@deepseek-ai/dsh` 同步）决定，`DSH_DESKTOP_BUILD_VERSION` 只能在它后面追加测试序号，不能改成 1.0.0。所以 electron-builder 产出的是 `deepseek-harness-0.2.1-rc.2-mac-arm64-unsigned.dmg`，`release-manifest.mjs stage` 把它改名成 1.0.0 的发布名，并把 `0.2.1-rc.2` 记进清单的 `base`。安装后「关于」里显示的仍是 `0.2.1-rc.2`。

### Mac（Apple 芯片）安装包（Mac）

按 `zhitong/INSTALL.md` 的 macOS 打包步骤准备好依赖后：

```sh
pnpm run package:desktop:mac:arm64:unsigned --check
pnpm run package:desktop:mac:arm64:unsigned
node zhitong/portal/deploy/release-manifest.mjs stage mac-arm64 \
  apps/desktop/.desktop-build/targets/mac-arm64/unsigned-artifacts/deepseek-harness-0.2.1-rc.2-mac-arm64-unsigned.dmg
```

`stage` 输出 sha256、大小、版本与日期（第一次放置时取当天的上海日期，`--date 2026-10-21` 可指定）。然后把清单改动提交进仓库，再发布：

```sh
git add zhitong/portal/site/public/downloads/releases.json
git commit -m "chore(zhitong/portal): stage v1.0.0 mac-arm64 installer"
bash zhitong/portal/deploy/deploy.sh zt-prod
```

### Windows x64 安装包（必须在 Windows 机器上打）

这个 GitHub 账号的 Actions 额度已耗尽，不能用仓库里的 `windows-package.yml` 在 CI 打包。在一台 Windows 10/11 x64 上按 `zhitong/INSTALL.md` 的 Windows 打包一节准备依赖（含 `dwg2dxf.exe` 与 DLL），然后：

```powershell
pnpm run package:desktop:win:x64:unsigned --check
pnpm run package:desktop:win:x64:unsigned
```

产物在 `apps\desktop\.desktop-build\targets\win-x64\unsigned-artifacts\deepseek-harness-0.2.1-rc.2-win-x64-unsigned.exe`。把它拷到 Mac（U 盘或网盘，不要改文件名），在 Mac 上：

```sh
node zhitong/portal/deploy/release-manifest.mjs stage win-x64 ~/Downloads/deepseek-harness-0.2.1-rc.2-win-x64-unsigned.exe
git add zhitong/portal/site/public/downloads/releases.json && git commit -m "chore(zhitong/portal): stage v1.0.0 win-x64 installer"
bash zhitong/portal/deploy/deploy.sh zt-prod
```

在 Windows 上也能直接跑 `node zhitong\portal\deploy\release-manifest.mjs stage win-x64 <exe>`，但之后要把 `zhitong/portal/downloads/` 下的 exe 与 `.sha256` 一起拷到 Mac 的同一目录，deploy.sh 发布前会核对。

### 规则

- 已上传的文件不换内容。安装包有 30 天缓存，`stage` 拒绝用不同内容覆盖同名文件。重新打包要发新版本：把清单的 `version` 改成 `1.0.1`，把各平台 `file`/`sha256`/`size` 置回 `null`，再逐个 `stage`。旧版本文件留在服务器上，旧链接继续可用。
- 不要手改清单里的 `sha256` 与 `size`。清单写错时 `npm run build` 失败；清单与文件不一致时 deploy.sh 在上传任何东西之前失败。
- 安装包未签名。门户上的「首次打开」提示：Mac 右键打开，macOS 15 起到「系统设置 → 隐私与安全性」点「仍要打开」；Windows SmartScreen 点「更多信息 → 仍要运行」。

## 5. 回滚

只回滚门户内容（ECS）：

```sh
cd /opt/ztsgai && mv site site.bad && mv site.prev site && rm -rf site.bad
```

容器模式下这一步无需重载（`/opt/ztsgai` 整个挂进容器）。

只回滚 nginx 配置（ECS）：`cp -p /opt/ztsgai/nginx/conf.d/ztsgai.conf.bak-<时间> /opt/ztsgai/nginx/conf.d/ztsgai.conf && docker exec zt-nginx nginx -t && docker exec zt-nginx nginx -s reload`。

整体回到旧系统（ECS）：

```sh
docker compose -f /opt/ztsgai/docker-compose.yml down          # 删掉门户的 zt-nginx
cd /opt/zhitong/app/deploy
docker compose -f docker-compose.prod.yml up -d app engine ocr nginx
systemctl enable --now zt-upstream-watchdog.timer
./deploy.sh verify-routes
```

旧 compose、旧 conf.d 与 `/opt/zhitong/nginx/html` 在切换时没有改动，所以这一步恢复的就是切换前的状态。`/opt/ztsgai` 可以留着，下次切换直接用。

## 6. 宿主 nginx 模式

只在第 2 步选了宿主模式时用。第 3.3 步停掉旧的 `nginx` 之后（ECS）：

```sh
apt-get install -y nginx
rm -f /etc/nginx/sites-enabled/default
mkdir -p /opt/ztsgai
~/.acme.sh/acme.sh --install-cert -d ztsgai.com \
  --key-file /opt/zhitong/nginx/ssl/ztsgai.com.key \
  --fullchain-file /opt/zhitong/nginx/ssl/ztsgai.com.fullchain.cer \
  --reloadcmd "systemctl reload nginx"
```

`--install-cert` 只改续期后的拷贝目标与重载命令；路径要与第 1 步看到的实际文件一致。然后在 Mac 上 `bash zhitong/portal/deploy/deploy.sh --mode host zt-prod`。回滚时先 `systemctl disable --now nginx` 再按第 5 节起旧服务。

Ubuntu 22.04 自带 nginx 1.18，`listen 443 ssl http2` 写法在 1.18 与容器的 1.25 上都能用（1.25 会打一行 deprecated 警告，不影响）。

## 7. 日常更新

- 只改了门户文字或样式：Mac 上 `bash zhitong/portal/deploy/deploy.sh zt-prod`。
- 发新安装包：第 4 节。
- 清单里 `file` 为 `null` 的平台在页面上显示「即将发布」，不会出现坏链接。
