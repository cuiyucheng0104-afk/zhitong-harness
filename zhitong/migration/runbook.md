# 第一个客户资料整理与上传：ECS 运行手册（W8）

本手册把 spec §6「NAS → TOS」落成在 ECS 上逐条执行的命令。以 root 在旧系统所在的 Ubuntu 22.04 ECS 上运行。手册里不出现任何凭据的值：数据库口令只在容器里以 `$MYSQL_ROOT_PASSWORD` 展开，TOS 的 AK/SK 由运行人在第 6 步现场输入到环境变量。

## 0. 安全边界与回滚

- 源目录只读：`relayout.py` 与 `verify.py` 对 `/opt/zhitong/data/nas-data` 只做读取与 `stat`，从不写、改名或删除；整理结果写到单独的工作目录（下文 `$OUT`），它与源目录互相包含时脚本拒绝运行（`unsafe_out_dir`）。
- 数据库只读：导出只用最近的 mysqldump 备份，或只含 `SELECT` 的 `export-rows.sql`。
- 回滚：镜像与源目录分开，放弃整理只需删除 `$OUT`；源目录与数据库原样未动。上传之后要撤回，桶开着版本控制，可以按对象恢复旧版本；整个前缀撤回要另行确认后用 `rclone purge`，本手册不执行。
- 硬链接（`--link hard`）的镜像文件与源文件是同一个 inode：镜像里不要原地编辑文件，编辑会改到源文件。脚本自己只新建、替换、删除镜像里的目录项，不原地写。
- 删除只发生在镜像里：「删除」指不放进镜像，源文件仍在 NAS 上。

## 1. 准备代码与运行环境

在有本仓库的机器上把 `zhitong/` 里用到的部分传到 ECS（`<ECS>` 换成你的 SSH 主机别名）：

```bash
rsync -a --delete --exclude '__pycache__' --exclude '.venv' \
  zhitong/python zhitong/migration zhitong/knowledge-seed zhitong/skills \
  <ECS>:/opt/zhitong/w8/zhitong/
```

以下命令都在 ECS 上执行。先定义几个变量（每开一个新 shell 都要重新执行一次）：

```bash
export Z=/opt/zhitong/w8/zhitong                # 代码
export WORK=/opt/zhitong/migration-work         # 导出结果、dry-run 计划、上传日志
export NAS=/opt/zhitong/data/nas-data           # 旧 NAS（compose 里挂成容器的 /work）
export OUT=/opt/zhitong/migration-out           # 镜像工作目录；第 2 步可能改到 NAS 所在文件系统
mkdir -p "$WORK"
```

Python：脚本需要 Python ≥ 3.11 与 `openpyxl pypdf PyYAML python-docx pydantic`；Ubuntu 22.04 自带的 3.10 不够。用 uv（会按 `zhitong/python/uv.lock` 装好解释器与依赖）：

```bash
curl -LsSf https://astral.sh/uv/install.sh -o /tmp/uv-install.sh && less /tmp/uv-install.sh && sh /tmp/uv-install.sh
export PATH="$HOME/.local/bin:$PATH"
uv sync --project "$Z/python" --no-dev
export PY="uv run --project $Z/python --no-dev python"
$PY -c 'import sys, zt.migration; print(sys.version)'
```

ECS 不能联网下载解释器时，改用系统包：`apt-get install -y python3.11 python3.11-venv`，`python3.11 -m venv /opt/zhitong/w8/venv && /opt/zhitong/w8/venv/bin/pip install openpyxl pypdf PyYAML python-docx pydantic`，然后 `export PY=/opt/zhitong/w8/venv/bin/python`。

rclone（Ubuntu 22.04 的 apt 版本较旧，用官方 deb）：

```bash
curl -fLO https://downloads.rclone.org/rclone-current-linux-amd64.deb && dpkg -i rclone-current-linux-amd64.deb && rclone version
```

建议整个过程在 `tmux` 里跑，第 5 步第一次运行要把所有源文件读一遍算 sha256。

## 2. 摸底：数据量、磁盘与文件系统

```bash
ls "$NAS/project" | head; ls "$NAS/project" | wc -l           # 应是以 project.id 命名的目录
ls "$NAS/knowledge"; ls "$NAS/knowledge/1" 2>/dev/null | head  # 知识库：租户子目录 1/ 与可能残留的平铺分类目录
du -sb "$NAS/project" "$NAS/knowledge"                          # 源数据字节数（--link copy 时镜像要占同样多）
find "$NAS/project" -name '*.ocr.txt' | wc -l                   # 项目里的 OCR 旁车数（勘察时约 2882）
df -h /opt/zhitong "$NAS"
stat -c '%d %m %n' "$NAS/project" /opt/zhitong                  # 设备号与挂载点：不同就不能硬链接
mount | grep nas-data
```

选放置方式（两者必选其一，`relayout.py` 默认 `--link hard`）：

- 设备号相同：`$OUT` 用 `/opt/zhitong/migration-out`，`--link hard`，镜像不额外占盘。
- `nas-data` 是单独挂载的 NAS（NFS），与系统盘设备号不同：要么把 `$OUT` 放到同一挂载下但在源目录之外（例如 `export OUT=$NAS/_migration-out`，与 `project/`、`knowledge/` 平级），继续 `--link hard`；要么留在系统盘用 `--link copy`，先确认 `df` 的可用空间大于上面 `du -sb` 的合计。硬链接跨文件系统时 relayout 报 `cross_device_link` 退出，不会悄悄改成复制。`--knowledge-seed` 的文件在代码目录里，总是复制（几 MB），不受 `--link` 影响。

## 3. 导出项目与文件记录

旧系统只导项目基本信息与文件清单（spec 决策 2），业务记录不导。两种来源二选一；生产库名是 `tian_gong_intelligence`（`deploy/docker-compose.prod.yml` 的 `DATABASE_NAME` 缺省值），第一个客户的 `sys_company_code` 是 `1`。

方式 A，用每晚的备份（推荐，不碰在线库）：

```bash
ls -lt /opt/zhitong/backup/tian_gong_intelligence-*.sql.gz | head -3
$PY "$Z/migration/export-projects.py" --mysql-dump /opt/zhitong/backup/tian_gong_intelligence-<YYYY-MM-DD>.sql.gz \
  --company-code 1 --out "$WORK/export"
```

方式 B，从在线库导 JSON Lines。先确认 MySQL 容器名（生产 compose 是 `zt-mysql`；旧仓开发环境叫 `tg-mysql`）与库名：

```bash
docker ps --format '{{.Names}}' | grep -i mysql
export MYSQL_CONTAINER=zt-mysql
docker exec "$MYSQL_CONTAINER" sh -c 'MYSQL_PWD="$MYSQL_ROOT_PASSWORD" exec mysql -uroot -N -e "SHOW DATABASES"'
```

单引号里的 `$MYSQL_ROOT_PASSWORD` 在容器里展开，不经过宿主机 shell，也不出现在命令行历史与进程列表里。然后：

```bash
docker exec -i "$MYSQL_CONTAINER" sh -c 'MYSQL_PWD="$MYSQL_ROOT_PASSWORD" exec mysql -uroot --default-character-set=utf8mb4 -N -B -r tian_gong_intelligence' \
  < "$Z/migration/export-rows.sql" > "$WORK/rows.jsonl"
docker exec -i "$MYSQL_CONTAINER" sh -c 'MYSQL_PWD="$MYSQL_ROOT_PASSWORD" exec mysql -uroot --default-character-set=utf8mb4 -N -B -r tian_gong_intelligence' \
  < "$Z/migration/export-knowledge-rows.sql" >> "$WORK/rows.jsonl"   # 没有 knowledge_file 表时报错，可跳过
wc -l "$WORK/rows.jsonl"
$PY "$Z/migration/export-projects.py" --json "$WORK/rows.jsonl" --company-code 1 --out "$WORK/export"
```

看 stdout 的 `counts`：`project_rows`（有效项目）、`project_deleted`、`file_rows`、`file_deleted`（已删记录跳过但计数）、`file_of_unknown_project`。再核对 NAS 目录名与项目 id 对得上：

```bash
$PY -c 'import json,sys; d=json.load(open(sys.argv[1])); print(len(d["projects"])); [print(p["id"], p["create_time"][:10], p["alias"], p["name"]) for p in d["projects"][:20]]' "$WORK/export/projects.json"
```

`alias` 列是 `project.report_code`（报告书编号）：它本身是 `YYYY-NNN` 时直接用作项目编号，否则记进项目说明的「别名」，编号按建项目年份流水分配（spec §5）。如果客户的编号记在别的字段，先停下来确认。

## 4. 核对知识库映射

```bash
ls "$NAS/knowledge/1"
less "$Z/migration/data/knowledge_map.yaml"
```

旧知识库一级目录是「分类名__分类id」。按 `knowledge_map.yaml` 的规则归到 `知识库/规范|定额|费率|模板|公司经验/`；规则猜不到的目录会让第 5 步报 `knowledge_unmapped` 并列出目录名，在 `exact` 里逐个写明去向或列入 `exclude` 后重跑。平铺的 `$NAS/knowledge/<分类名__id>/`（旧租户迁移脚本没跑过时）也要迁：再加一个 `--knowledge "$NAS/knowledge"`，并把 `1`、`2` 等租户目录写进 `exclude`。

## 5. 整理：先 dry-run，再正式运行

dry-run 只读，不写任何文件，完整计划写到 `$WORK/plan.json`：

```bash
$PY "$Z/migration/relayout.py" --export-dir "$WORK/export" --nas "$NAS/project" --out "$OUT" --link hard \
  --knowledge "$NAS/knowledge/1" --knowledge-seed "$Z/knowledge-seed" \
  --dry-run --plan-out "$WORK/plan.json" > "$WORK/plan-summary.json"
$PY -m json.tool "$WORK/plan-summary.json" | less
```

看 `summary`：`outputs`/`output_bytes`（迁入镜像）、`drawings`、`deletions_by_reason`、`not_migrated_by_reason`（`missing_source` 库里有盘上没有、`orphan` 盘上有库里没有、`history_version` 历史版本）、`renames`，以及 `warning_items`。删除原因与说明见 `zhitong/python/zt/migration/relayout.py` 的 `REASONS`。旁车的预期：`ocr_placeholder_sidecar` 约 754 份（整份「OCR 连续失败」占位），其余分页旁车随原件进镜像；数字差得多先查清再继续。

确认后正式运行（同样的参数去掉 `--dry-run --plan-out`）：

```bash
$PY "$Z/migration/relayout.py" --export-dir "$WORK/export" --nas "$NAS/project" --out "$OUT" --link hard \
  --knowledge "$NAS/knowledge/1" --knowledge-seed "$Z/knowledge-seed" > "$WORK/relayout-result.json"
echo "exit=$?"
```

产物：`$OUT/mirror/`（上传的就是它）、`$OUT/manifest.json`（每个文件的新路径、旧路径、字节数、sha256，及删除、未迁移、改名清单）、`$OUT/整理报告.md`、`$OUT/.state/`（编号分配与 sha256 缓存，重跑沿用，不要删）。重跑结果相同：已就位的文件不动，镜像里不在本次计划内的文件会被删掉（只删镜像）。

要把库里没有记录的 NAS 文件也迁进去，加 `--include-orphans`，它们进各项目的 `资料/未登记文件/<原磁盘路径>`。

## 6. 校验

```bash
$PY "$Z/migration/verify.py" --export-dir "$WORK/export" --nas "$NAS/project" --out "$OUT" > "$WORK/verify.json"; echo "exit=$?"
$PY -m json.tool "$WORK/verify.json" | less
```

退出码 0 才能上传。退出码 2 时 `$OUT/verify-problems.json` 列出每处不一致（镜像缺文件、内容不符、某条记录既没迁入也没在删除清单里、项目说明缺失或编号不符、案例索引行数不对）。「库里有、NAS 上没有」（`missing_source`）核实确实找不回后，加 `--accept-missing-source` 重跑，它会降为告警。`--quick` 只比字节数、不重算 sha256，只在第二次以后的快速复查时用。

再读一遍 `$OUT/整理报告.md`：删除清单、未迁移清单、改名清单、空目录；抽查几个项目的 `项目说明.md`（关键文件指引是按文件名判断的候选，备注写着「待确认」，留给开项目时核对）与 `$OUT/mirror/案例索引.md`。

知识库按 zt-knowledge 的规则检查一遍（退出码 0 才上传）：

```bash
$PY "$Z/skills/zt-knowledge/scripts/check_knowledge.py" --root "$OUT/mirror/知识库"
```

## 7. 配置 rclone 的 TOS remote

用 TOS 的 S3 兼容接口。endpoint 与 region 在火山引擎控制台桶「概览」页的「S3 兼容 Endpoint」核对；ECS 与桶同地域时用内网域名（`ivolces.com`），例如 `cn-beijing` 是 `tos-s3-cn-beijing.ivolces.com`，公网是 `tos-s3-cn-beijing.volces.com`。配置里不写密钥：

```bash
rclone config create tos s3 provider=Other env_auth=false region=cn-beijing \
  endpoint=https://tos-s3-cn-beijing.ivolces.com force_path_style=false no_check_bucket=true acl=private
```

每次上传前在当前 shell 输入 AK/SK（`-s` 不回显，不进历史；所用 AK 只需该桶该前缀的读、写、列举、删除权限）：

```bash
read -r -p 'TOS AccessKey ID: ' RCLONE_CONFIG_TOS_ACCESS_KEY_ID; read -r -s -p 'TOS SecretAccessKey: ' RCLONE_CONFIG_TOS_SECRET_ACCESS_KEY; echo
export RCLONE_CONFIG_TOS_ACCESS_KEY_ID RCLONE_CONFIG_TOS_SECRET_ACCESS_KEY
export BUCKET=<桶名> PREFIX=<公司前缀>        # 与客户配置包 zhitong.config.json 的 tos.bucket / tos.prefix 一致
rclone lsf "tos:$BUCKET/$PREFIX/" --max-depth 1  # 能列出（或为空）即连通
```

## 8. 上传：先 dry-run，再正式上传，最后 check

`upload.sh` 每次都先 dry-run 并在日志里计数，再问是否继续（`--yes` 跳过询问），正式上传用 `--checksum`，最后 `rclone check`。日志在 `$OUT/logs/`。

```bash
bash "$Z/migration/upload.sh" --bucket "$BUCKET" --prefix "$PREFIX" --src "$OUT/mirror"
```

- dry-run 发现要删除桶里已有、镜像里没有的对象时，脚本以退出码 3 停下并列出前 20 条；核对后确实要删才加 `--allow-delete`。
- 分夜跑：按项目目录分批，`--subdir 项目/<编号>-<工程名>`；最后一晚不带 `--subdir` 全量 sync 一次（只传剩下的，并把 `案例索引.md` 与 `知识库/` 一起传上）。限速与并发放在 `--` 后面原样传给 rclone，例如 `-- --bwlimit 50M --transfers 8`。
- 中断后原样重跑即可，`--checksum` 会跳过已传完的文件。
- `--from-knowledge-seed "$Z/knowledge-seed"` 只用于单独补传或刷新 knowledge-seed（`rclone copy`，只增不删，不传 `_tools/` 与 seed 根目录的 README.md）。第 5 步带了 `--knowledge-seed` 时镜像里已经有这些内容，不要再用它，否则会用 seed 的 README 覆盖镜像里合并了「旧系统迁入」一节的 README。

上传完再整体复核一次：

```bash
rclone check "$OUT/mirror/" "tos:$BUCKET/$PREFIX/" --exclude '_tools/**' --exclude '**/_tools/**'
rclone size "tos:$BUCKET/$PREFIX/"; du -sb "$OUT/mirror"
```

## 9. 9 本无文本扫描书与 OCR 旁车

- 9 本扫描版定额书（旧 `knowledge/1/`）照原样进 `知识库/<子目录>/`；没有可用旁车的 PDF 列在对应子目录 README 的「旧系统迁入」一节。上线后由 zt-knowledge 用看图逐页补文本，结果写成与原件并列的 `<原件名>.ocr.txt`（分页格式）推回桶。
- 分页旁车：随原件进镜像，统一改成追加式命名 `<原件显示名>.ocr.txt`，与改名后的原件并列；原件被判重复删除时，旁车转给保留的那份（保留件自己有旁车时删掉多余的一份）。
- 「OCR 连续失败」等一页可用的都没有的旁车删除（`ocr_placeholder_sidecar`，删除清单里带每页判定计数）；对应原件之后由 agent 看图读取。
- 旧仓的 OCR 补跑工具把结果写在 `/opt/zhitong/ocr-backfill/`，要由人工核对后拷回 NAS 才算数（旧仓 `docs/运维/runbook-OCR旁车补跑.md`）。补跑过但还没拷回的，先按那份手册拷回，再从第 5 步重跑；不拷回就不会进镜像。

## 10. 收尾

- 上传与 check 都通过后，保留 `$OUT/manifest.json`、`$OUT/整理报告.md`、`$WORK/` 作为迁移记录（不进桶）。
- 在一台装好智通数工AI 的机器上导入客户配置包，打开两三个项目核对项目说明与文件能拉下来，再按 spec §6 第 8 条下线旧系统的 Java、MySQL、前端容器；NAS 上的源文件与最后一份数据库备份另行保留，到期再由客户决定是否删除。
