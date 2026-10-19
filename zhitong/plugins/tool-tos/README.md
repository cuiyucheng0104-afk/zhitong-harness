# @zhitong/tool-tos

智通数工AI 的文件通道：公司火山引擎 TOS 桶（公司前缀以下）与本机镜像缓存。

## 工具

| 工具 | 作用 |
|---|---|
| `tos_ls` | 列目录（一层或递归），分页；标出本机已有一致副本的文件 |
| `tos_stat` | 单个文件的桶内元数据与本机副本状态（`current` / `stale` / `modified` / `untracked` / `absent`） |
| `tos_pull` | 拉文件或整个目录到本机镜像，返回本机路径；一致副本不重下；本机改过未推送的文件不覆盖（`conflict`），`overwrite` 才覆盖；目录拉取默认跳过 `noAutoPullExtensions`（图纸、压缩包） |
| `tos_push` | 上传本机文件并回读校验（大小 + SHA-256 元数据 + 单段上传的 MD5 ETag）；报告被覆盖的旧版本与「拉取后别人改过」 |

模型看到的路径一律相对公司前缀，如 `项目/2026-007-某工程/资料/合同.pdf`；以 `/` 结尾表示目录。也接受指向已配置桶与前缀的 `tos://<bucket>/<prefix>/…`。

## 本机镜像

- 根目录 `cacheRoot`，默认 `~/zhitong`（Windows `%USERPROFILE%\zhitong`），与桶内公司前缀以下同构。
- `<cacheRoot>/.zhitong-cache/index.json` 记录每个文件的远端 ETag、本机大小、修改时间与 SHA-256；更新索引持跨进程文件锁，传输在锁外进行。
- 去重：对象带 SHA-256 元数据（`tos_push` 写入）且镜像里已有同内容的未修改文件时，本机复制，不再下载。
- 上限 `cacheMaxBytes`（默认 20 GiB）。`eviction: lru` 时按最近访问淘汰未修改的文件；本机改过的文件从不淘汰；`none` 时放不下的文件跳过（`cache-full`）。
- Windows 上不能保存的文件名（`<>:"|?*`、保留名、末尾点或空格）直接报错，不改名。

## 配置

| 字段 | 默认 | 说明 |
|---|---|---|
| `backend` | `tos` | `local` 用本机目录充当桶（离线开发与测试） |
| `endpoint` / `region` / `bucket` / `prefix` | — | 由 `config_import` 写入；缺任一项时工具报错并提示导入配置包 |
| `localRoot` | — | `backend: local` 时必填 |
| `accessKeyIdRef` / `secretAccessKeyRef` | `ZT_TOS_ACCESS_KEY_ID` / `ZT_TOS_SECRET_ACCESS_KEY` | 凭据引用名；每次调用从 `ctx.credentials` 解析 |
| `cacheRoot` | `~/zhitong` | 本机镜像根 |
| `cacheMaxBytes` | 20 GiB | 镜像跟踪文件的总字节上限 |
| `eviction` | `lru` | `lru` 或 `none` |
| `noAutoPullExtensions` | `.dwg .dxf .rvt .skp .3dm .ifc .nwd .zip .rar .7z` | 目录拉取默认跳过的扩展名 |
| `maxListEntries` | 200 | `tos_ls` 每页上限 |
| `maxPullFiles` | 200 | 单次 `tos_pull` 的文件数上限 |
| `maxPushBytes` | 5 GiB | 单次上传上限（TOS 单次 PUT 上限） |

## 已知限制

- 上传用单次 PUT（`putObjectFromFile`），不做分片；大于 5 GiB 的文件拒收。
- SDK 调用不接收取消信号；取消只在两次请求之间生效。
- 腾出缓存空间与写入索引不在同一把锁里，多个进程同时拉取时可能短暂超出上限。
- 官方 SDK `@volcengine/tos-sdk@2.9.1` 依赖 `axios@0.21.4`；它只在 `backend: tos` 首次调用时加载。

## 测试

```sh
pnpm vitest run        # 本机目录后端覆盖四个工具；真桶测试需 ZT_TOS_TEST_* 环境变量
pnpm run typecheck
```
