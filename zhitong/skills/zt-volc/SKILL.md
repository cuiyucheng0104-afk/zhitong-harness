---
name: zt-volc
description: 火山引擎运维：用 ve CLI 查看 ECS 实例与启停、查看和修改安全组白名单（含把当前公网 IP 同步进白名单）、只读查看 TOS 桶，并通过 ~/.ssh/config 的主机别名 SSH 到服务器执行命令。凡会中断服务或改变访问范围的操作，先在对话里向用户确认，再带 --yes 执行。
whenToUse: 用户要看或操作公司的火山引擎资源（ECS 状态、启停、安全组放行本机 IP、桶信息）或要登录生产服务器查日志、状态、执行命令时。文件存取走 tos_* 工具，不走本 skill。
---

# 火山引擎运维（zt-volc）

脚本 `zt.volc` 是 `ve`（火山引擎官方 CLI）与 `ssh` 的封装，不直接调 SDK，零模型。它对应用户本机的三个旧工具：`vec`（`ve --profile <profile>`）、`ssh-access-sync.sh`（把当前公网 IP 同步进安全组白名单）、`pssh`（用 `~/.ssh/config` 别名登录服务器）。

调用：`"$ZT_PYTHON" -m zt.volc.cli <子命令> [选项]`（`$ZT_PYTHON` 未设置时用 `python3`；等价写法 `scripts/volc.py ...`）。stdout 是一个 JSON：成功是结果信封，失败是退出码 2 + `{"error": {code, message, hint}}`。

## 1. 名称从哪来

脚本只读取名称，不含也不回显任何密钥：

- profile：`--profile`，或环境变量 `ZT_VOLC_PROFILE`，或 `ZT_VOLC_CONFIG` 指向的配置文件里的 `volc.profile`（region 同理）。没有则报 `volc_profile_missing`，不要猜 profile 名。
- SSH 主机别名：配置文件的 `ssh.hosts[].alias` 与 `~/.ssh/config`（或 `ZT_SSH_CONFIG`）里的 `Host`。`ssh-hosts` 列出；不在列表里的别名一律拒绝。
- `ve` 的 AK/SK 在 `ve` 自己的 profile 里（用户在自己的终端 `ve configure set --profile …` 建立）。不要让用户把密钥贴进对话，不要自己执行 `ve configure set`。
- 先跑 `whoami` 验证 profile 可用；`ve_not_found` 时告诉用户安装官方 CLI（`npm i -g @volcengine/cli`）。

## 2. 子命令

| 子命令 | 作用 | 需要 `--yes` |
|---|---|---|
| `whoami` | 验证 profile（`ve sts GetCallerIdentity`） | 否 |
| `ecs-list [--status RUNNING] [--name x]` | 列实例 | 否 |
| `ecs-status --instance-id i-…` | 实例状态、IP、绑定的安全组 | 否 |
| `ecs-start` / `ecs-stop` / `ecs-reboot --instance-id i-… [--wait 秒] [--force-stop]` | 启停重启 | start 否；stop、reboot 是 |
| `sg-show --sg-id sg-… [--direction ingress]` | 安全组规则 | 否 |
| `sg-authorize` / `sg-revoke --sg-id --protocol --port-start --port-end --cidr` | 增删入方向规则 | 是 |
| `sg-sync-ip --sg-id sg-… --ip <公网IP> [--ports 22] [--label 名]` | 同步白名单 | 有变更时是 |
| `tos-buckets` / `tos-stat --bucket` / `tos-ls --bucket [--prefix]` | 只读看桶 | 否 |
| `tos-lifecycle` / `tos-versioning --bucket` | 只读看生命周期、版本控制 | 否 |
| `ssh-hosts` / `ssh-exec --host 别名 --command "…"` | 登录服务器执行 | 非只读命令是 |

写操作都支持 `--dry-run`：只输出将执行的命令和影响，不调用任何写接口。选项细节见 `--help`，API 字段与未核实项见 `references/ve-notes.md`。

## 3. 确认纪律（先问，再执行）

需要 `--yes` 的操作按下面走，缺一步都不执行：

1. **先 `--dry-run`**（停止、重启、改安全组、SSH 非只读命令），或不带 `--yes` 运行一次拿 `confirmation_required` 的说明。
2. **用 `user-questions` 向用户确认**，问题里写清：对象（实例名与 ID、安全组名与 ID、主机别名）、动作、影响（谁会失去访问、哪些服务会中断）、原命令。选项只有「执行」「不执行」。
3. **只有用户明确选「执行」才加 `--yes` 重跑原命令**，参数一个字都不改。一次确认只对应一条命令；第二条命令要重新问。
4. 用户没回答、选了其他选项或要求修改，就不执行；改参数后回到第 1 步。
5. 不得在第一次调用就带 `--yes`；不得用 `--yes` 去「试试」；不得替用户确认。
6. `--allow-world`（向 `0.0.0.0/0` 开放）只有用户亲口要求全网开放时才加，并在确认问题里点明风险。

`ecs-start`、所有只读命令和只读白名单内的 SSH 命令（`ls cat tail grep df ps docker ps/logs systemctl status journalctl` 等）不需要确认。白名单是便利分级，不是沙箱：命令以登录账号的权限在远端运行。

## 4. 常用流程

**放行本机 IP 后登录服务器**（`ssh-access-sync.sh` + `pssh`）：

1. 取当前出口公网 IP：用户提供，或 `web_fetch` 一个返回纯文本 IP 的地址；脚本也可用 `--ip-url` / `ZT_PUBLIC_IP_URL` 自动探测。私网、回环地址会被拒绝。
2. `sg-sync-ip --sg-id … --ip … --dry-run`，把 `to_add_ports`、`to_revoke` 告诉用户并确认；同一安全组里多人共用时各用 `--label 自己的名字`，只会撤销自己标记的旧 IP。
3. 确认后加 `--yes` 重跑：先放行新 IP，成功后再撤销旧 IP。`partial` 且告警 `stale_rule_revoke_failed` 表示新 IP 已通、旧 IP 仍有权限，如实告诉用户并建议复核。
4. `ssh-hosts` 选别名，`ssh-exec --host … --command "docker ps"`。`ssh_connect_failed` 先怀疑白名单过期（回到第 2 步）。

**停机/重启 ECS**：`ecs-status` 看当前状态 → `ecs-stop --dry-run` → 确认 → `ecs-stop --yes --wait 120`。`--wait` 超时是 `partial`，请求已发出，用 `ecs-status` 复查，不要重发。

## 5. 结果转述

- 如实转述 `status` 与全部 `warning_items`（`error`/`warn` 逐条，`info` 可合并）。`partial` 说清缺了什么（列表被截断、等待超时、旧规则未撤销）。
- `changed: false` 表示什么都没改（已在目标状态、规则已存在、已同步），照实说，不要说「已执行」。
- 退出码 2 的 `error.message` 与 `hint` 原样告诉用户。`ve_timeout`、`ssh_timeout` 后写操作的实际结果未知：先用只读命令查，再决定是否重试。
- `ssh-exec` 的 `exit_code` 非零是远端命令失败，不是连接失败；输出被截断时说明并建议缩小范围。
- 不把配置文件内容、密钥、私钥、完整 `ve` 命令之外的凭据贴进对话；日志里出现形似密钥的内容也不要转述。

## 6. 范围外

不提供：删除桶或对象、修改桶生命周期与版本控制、创建与删除 ECS 实例、改安全组以外的 VPC 资源、`ve configure`。公司桶是唯一真源，这些操作请用户在火山引擎控制台完成。文件存取用 `tos_ls/tos_pull/tos_push`。

## 7. 落盘

运维记录不属于项目成果，不写入项目目录。用户要求留痕时写 `知识库/公司经验/运维记录-<YYYY-MM-DD>.md`（经 `zt-knowledge` 规则：只写已发生的事实，带日期，不含密钥与私钥）。
