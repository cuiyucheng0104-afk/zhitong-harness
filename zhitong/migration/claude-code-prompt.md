# 让本机 Claude Code 代跑迁移（提示词）

前提：Mac 上仓库在 `~/Desktop/zhitong-harness` 且为最新 master；`ssh zt-prod` 能免交互登录 ECS；火山引擎 TOS 桶已建、已开版本控制；该桶该前缀的 AK/SK 在手（客户配置包用的那把就够：它有前缀下的列举、读、写、删权限）。

把下面整段贴进在仓库目录打开的 Claude Code 会话。尖括号里的三处先改好。会话里不会出现任何密钥：AK/SK 由你自己 ssh 上去写进一个 root 只读文件，agent 只 source、不读。

```text
请按 zhitong/migration/runbook.md 把第一个客户的 NAS 资料整理并上传到 TOS。你在我的 Mac 上，服务器通过 `ssh zt-prod` 访问（root）。每一条会在服务器上写东西的命令，先把命令打给我看、等我回复「执行」再跑；只读命令（ls、du、df、stat、cat、python 的 --dry-run、verify.py、rclone lsf/check/size）直接跑并把关键输出摘要给我。任何一步失败就停下报告，不要改参数自行重试，也不要跳过步骤。

参数：
- 桶名：<桶名>
- 前缀：<例如 智通数工>
- 区域：cn-beijing（rclone 的 S3 endpoint 按 runbook 第 7 步，内网 tos-s3-cn-beijing.ivolces.com；连不通换公网 tos-s3-cn-beijing.volces.com）

纪律：
- 服务器上的 /opt/zhitong/data（NAS 原件、MySQL 数据目录）只读，不执行任何会修改它的命令；不停、不删任何容器。
- 不读、不打印 /opt/zhitong/app/deploy 下的 .env 文件、tos.env，不把密钥、口令写进对话。MySQL 口令只在容器内用 $MYSQL_ROOT_PASSWORD 展开（runbook 第 3 步的写法）。
- 长时间命令（relayout 正式运行、upload）用 `nohup … > 日志 2>&1 &` 在服务器后台跑，之后每 3 分钟 `tail -n 5 日志` 看进度，直到结束；不要用会话内的 sleep 轮询超过 10 分钟一次。
- 所有服务器命令用 `ssh zt-prod 'bash -lc "…"'` 执行，每条先 `export Z=… WORK=… NAS=… OUT=…`（runbook 第 1 步的四个变量，和 PATH 里加上 $HOME/.local/bin）。

步骤（对应 runbook 的章节号）：
1. 第 1 步：先 `ssh zt-prod 'python3 --version; which uv rclone; df -h /opt/zhitong'` 摸底。把 zhitong/python、migration、knowledge-seed、skills 用 rsync 传到 zt-prod:/opt/zhitong/w8/zhitong/。安装 uv 与 rclone（下载脚本先打出来给我看再执行）。`uv sync` 后跑 `import zt.migration` 验证。
2. 第 2 步：数据量、OCR 旁车数、磁盘、设备号、挂载。根据设备号结果告诉我应该用 `--link hard` 还是 `--link copy`，以及 $OUT 放哪；等我定。
3. 第 3 步：优先方式 A（最近一晚的 mysqldump）。导出后把 counts 和前 20 个项目的 id/日期/别名/名称列给我看。别名列不像 YYYY-NNN 的，说明一下将按年份流水编号。
4. 第 4 步：列出 $NAS/knowledge/1 的目录名，对照 knowledge_map.yaml，把每个目录会归到哪里列成表给我确认；归不到的先问我，不要自己改规则文件以外的东西。
5. 第 5 步：先 dry-run，把 summary 里的 outputs、output_bytes、drawings、deletions_by_reason、not_migrated_by_reason、renames 和全部 warning_items 给我。ocr_placeholder_sidecar 的数量与 754 差很多要指出来。等我确认后再正式运行（后台 + 日志）。
6. 第 6 步：verify.py，退出码不是 0 就把 verify-problems.json 的分类计数和前 10 条给我，停下。然后 `cat $OUT/整理报告.md` 的前 80 行、`案例索引.md` 全文、随机 3 个项目的 项目说明.md 给我看。再跑 check_knowledge.py。
7. 第 7 步：rclone remote 只建配置，不配密钥。然后停下，告诉我：请我自己 `ssh zt-prod`，执行
   `umask 077; mkdir -p /opt/zhitong/migration-work; cat > /opt/zhitong/migration-work/tos.env` 后输入两行
   RCLONE_CONFIG_TOS_ACCESS_KEY_ID=… 和 RCLONE_CONFIG_TOS_SECRET_ACCESS_KEY=…，Ctrl-D 结束。我回复「写好了」后，你用 `set -a; . /opt/zhitong/migration-work/tos.env; set +a; rclone lsf tos:<桶名>/<前缀>/ --max-depth 1` 验证连通，不要 cat 这个文件。
8. 第 8 步：先 `upload.sh` 的 dry-run（它自带），把计数给我；退出码 3（会删桶里对象）就停下。我确认后 `--yes` 正式上传（后台 + 日志），结束后 rclone check 和 size/du 对比给我。
9. 结束时给我一份清单：迁入文件数与字节、删除与未迁移的分类计数、项目数与编号范围、知识库各子目录文件数、上传 check 结果、日志与报告的路径。另外列出 runbook 第 9、10 步里需要我手工决定的事。最后在服务器上 `rm /opt/zhitong/migration-work/tos.env` 并告诉我已删。
```
