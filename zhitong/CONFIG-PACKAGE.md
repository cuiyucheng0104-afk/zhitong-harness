# 客户配置包格式（zhitong.config.json）

配置包把一家客户公司的桶地址与访问密钥交给工程师的安装。由你在本机整理，不进仓库；工程师把它拖进对话（或给出本机路径），agent 调用 `config_import` 导入。

## 文件形态

- 单个 `zhitong.config.json`（UTF-8，可带 BOM），或
- 一个 `.zip`，里面恰好有一个 `zhitong.config.json`，放在 zip 根目录或往下一层（如 `某某咨询/zhitong.config.json`）；`__MACOSX/` 下的副本忽略，其他文件忽略。
- 文件与解压后的 `zhitong.config.json` 都不超过 1 MiB（`config-import` 的 `maxPackageBytes`）。

## 字段

```json
{
  "format": "zhitong.config/1",
  "comment": "2026-10 首次发放（可选，导入时忽略）",
  "company": { "name": "某某工程造价咨询有限公司" },
  "tos": {
    "endpoint": "tos-cn-beijing.volces.com",
    "region": "cn-beijing",
    "bucket": "zt-company",
    "prefix": "某某咨询",
    "accessKeyId": "AKLT…",
    "secretAccessKey": "…"
  },
  "ssh": {
    "hosts": [
      { "alias": "zt-prod", "host": "10.0.0.8", "port": 22, "user": "root", "privateKey": "-----BEGIN OPENSSH PRIVATE KEY-----\n…\n" }
    ]
  },
  "volc": { "profile": "zt-ak", "region": "cn-beijing" }
}
```

| 字段 | 必填 | 规则 |
|---|---|---|
| `format` | 是 | 固定为 `zhitong.config/1` |
| `comment` | 否 | 任意字符串，导入时忽略 |
| `company.name` | 是 | 非空；导入结果里回显 |
| `tos.endpoint` | 是 | 只写主机名（可带端口），不带 `https://` 与路径 |
| `tos.region` | 是 | 非空，如 `cn-beijing` |
| `tos.bucket` | 是 | 小写字母、数字、`-`，长度 3–63 |
| `tos.prefix` | 否 | 公司前缀（桶内目录），首尾 `/` 会去掉；不能含 `.`、`..` 段、反斜杠与控制字符；空表示桶根 |
| `tos.accessKeyId` / `tos.secretAccessKey` | 是 | 非空；首尾空白会去掉 |
| `ssh.hosts[]` | 否 | `alias`（字母、数字、`_`、`-`，不重复）、`host`（主机名或 IP，只含字母、数字、`.`、`:`、`%`、`_`、`-`）、`user`（字母、数字、`.`、`_`、`-`）必填；`port` 默认 22；`privateKey` 可选（OpenSSH 或 PEM 私钥全文），原样保存 |
| `volc.profile` | `volc` 出现时必填 | `ve` CLI 的 profile 名；`volc.region` 可选。配置包**不带** `ve` 的 AK/SK，见下文「火山引擎 ve profile」 |

出现上表以外的字段会被拒收，避免拼错字段名后静默失效。

## 导入后写到哪里

| 内容 | 去处 |
|---|---|
| `tos.accessKeyId`、`tos.secretAccessKey` | 本机凭据存储（`~/.dsh/.credentials.yaml`，仅当前用户可读），引用名 `ZT_TOS_ACCESS_KEY_ID`、`ZT_TOS_SECRET_ACCESS_KEY` |
| `tos.endpoint/region/bucket/prefix` 与两个引用名 | 当前 profile 的 `cordis.patch.yml` 里 `zhitong-tool-tos` 行的 `config`；保存后 TOS 工具立即按新设置重新加载 |
| `company.name` | 只在导入结果里显示 |
| `volc.profile`、`volc.region`、`ssh.hosts[].alias` | 只有名称的 zt-volc 设置文件 `$DSH_HOME/zhitong/volc.config.json`（默认 `~/.dsh/zhitong/volc.config.json`，仅当前用户可读）。zt-volc 在 `ZT_VOLC_CONFIG` 未设置时读它 |
| `ssh.hosts[]` 的 `host`、`port`、`user` | `~/.ssh/config`（Windows `%USERPROFILE%\.ssh\config`）**开头**的受管块，首尾各有一行 `# >>> zhitong config-import` / `# <<< zhitong config-import <<<` 标记；重新导入时整块替换，块外内容不动。放在开头是因为 OpenSSH 对每个选项取第一次读到的值，后面的 `Host *` 不会盖掉它。`~/.ssh/config` 是符号链接时写到链接目标 |
| `ssh.hosts[].privateKey` | `~/.ssh/zhitong/<alias>`（权限 0600，目录 0700），受管块里写 `IdentityFile` 与 `IdentitiesOnly yes` |

导入结果、错误信息、zt-volc 设置文件与 profile 文件里都不出现密钥值；校验错误只给字段路径。`dry_run: true` 只校验不写入，可在发放前自检。

## 火山引擎 ve profile

zt-volc 通过官方 CLI `ve` 调火山引擎 OpenAPI，`ve` 的 AK/SK 保存在 `ve` 自己的 profile 里，不经过配置包，也不经过对话。每位要用 zt-volc 的工程师在自己的终端里做一次：

```sh
npm i -g @volcengine/cli          # 安装 ve（或按火山引擎文档的其他安装方式）
ve configure set --profile zt-ak --region cn-beijing --access-key <AK> --secret-key <SK>
ve --profile zt-ak sts GetCallerIdentity   # 验证；也可以在对话里让 agent 跑 zt-volc 的 whoami
```

`--profile` 的名字要与配置包里的 `volc.profile` 一致。具体参数名以所装 `ve` 版本的 `ve configure set --help` 为准；AK/SK 用火山引擎控制台为本人创建的子账号密钥，权限只给 ECS 只读/启停、安全组与 TOS 只读需要的策略。不要把 AK/SK 写进配置包、贴进对话或交给 agent 执行 `ve configure set`。

## 轮换与撤销

- 轮换密钥：发一份新配置包重新导入即可，下一次 `tos_*` 调用即用新密钥。
- 撤销本机密钥：删除凭据存储里的两个引用（设置页的凭据管理，或编辑 `~/.dsh/.credentials.yaml`）。
- 配置包本身含明文密钥：导入后从下载目录删除，不要转发。
