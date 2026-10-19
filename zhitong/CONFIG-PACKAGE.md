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
| `ssh.hosts[]` | 否 | `alias`（字母、数字、`_`、`-`，不重复）、`host`、`user` 必填；`port` 默认 22；`privateKey` 可选，原样保存 |
| `volc.profile` | `volc` 出现时必填 | `ve` CLI 的 profile 名；`volc.region` 可选 |

出现上表以外的字段会被拒收，避免拼错字段名后静默失效。

## 导入后写到哪里

| 内容 | 去处 |
|---|---|
| `tos.accessKeyId`、`tos.secretAccessKey` | 本机凭据存储（`~/.dsh/.credentials.yaml`，仅当前用户可读），引用名 `ZT_TOS_ACCESS_KEY_ID`、`ZT_TOS_SECRET_ACCESS_KEY` |
| `tos.endpoint/region/bucket/prefix` 与两个引用名 | 当前 profile 的 `cordis.patch.yml` 里 `zhitong-tool-tos` 行的 `config`；保存后 TOS 工具立即按新设置重新加载 |
| `company.name` | 只在导入结果里显示 |
| `ssh`、`volc` | 本版本只校验，不应用（结果里列为 `deferredSections`）；由 zt-volc 工单接入 |

导入结果、错误信息与 profile 文件里都不出现密钥值；校验错误只给字段路径。`dry_run: true` 只校验不写入，可在发放前自检。

## 轮换与撤销

- 轮换密钥：发一份新配置包重新导入即可，下一次 `tos_*` 调用即用新密钥。
- 撤销本机密钥：删除凭据存储里的两个引用（设置页的凭据管理，或编辑 `~/.dsh/.credentials.yaml`）。
- 配置包本身含明文密钥：导入后从下载目录删除，不要转发。
