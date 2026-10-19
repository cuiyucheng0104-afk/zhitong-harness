# @zhitong/config-import

`config_import` 工具：校验客户配置包（`zhitong.config.json`，或含它的 `.zip`），把 TOS 访问密钥写入 `ctx.credentials`，把桶的 endpoint/region/bucket/公司前缀与凭据引用名写入当前 profile 里 `zhitong-tool-tos` 行的配置（经 `ctx.configEditor`，保存后 TOS 工具重新加载）。格式说明见 [zhitong/CONFIG-PACKAGE.md](../../CONFIG-PACKAGE.md)。

- 结果与错误不含密钥；校验错误只列字段路径，JSON 语法错误只给位置。
- `dry_run: true` 只校验。
- `ssh`、`volc` 段只校验、不应用（列在 `deferredSections`），由 zt-volc 工单接入。
- 写入顺序：先存两个密钥，再改 profile 配置；后者失败时错误信息明确说明密钥已存入、设置未写入。

## 配置

| 字段 | 默认 | 说明 |
|---|---|---|
| `tosEntryId` | `zhitong-tool-tos` | 要写入连接设置的 Loader 行 id |
| `accessKeyIdRef` / `secretAccessKeyRef` | `ZT_TOS_ACCESS_KEY_ID` / `ZT_TOS_SECRET_ACCESS_KEY` | 存密钥用的凭据引用名，同时写进 TOS 行配置 |
| `maxPackageBytes` | 1 MiB | 配置包文件与解压后文档的大小上限 |

需要 profile 里有 `credentials` 与 `config-editor` 服务（dsh-base 默认提供）；缺少时工具报错，不做部分写入。

## 测试

```sh
pnpm vitest run
pnpm run typecheck
```
