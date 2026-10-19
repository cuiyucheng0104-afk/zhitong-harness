# ve / tosutil / OpenAPI 备忘

核对日期 2026-10-19。volcengine.com 在编写环境里访问不到，下面的依据是官方 GitHub 仓库的文档与 SDK 源码；与控制台文档不一致时以 `ve <服务> <动作> --help` 为准。

## 依据

| 内容 | 来源 |
|---|---|
| `ve <service> <Action> --Param value`、`--profile/--region/--output/--query`、数组 `--Name.1`、`--yes`、安全策略 | github.com/volcengine/volcengine-cli `docs/4-Usage-zh.md`、`docs/3-Configuration-zh.md` |
| 认证方式与优先级、环境变量 | 同仓库 `docs/2-Authentication-zh.md` |
| `ve tosutil ...` 透传（首次调用自动安装 tosutil；不受 `ve` 安全策略拦截） | 同仓库 `docs/7-ProxyCLI-zh.md` |
| ECS：`DescribeInstances`（`InstanceIds.N`、`Status`、`InstanceName`、`MaxResults`、`NextToken`）、`StartInstance`/`StopInstance`/`RebootInstance`（必填 `InstanceId`；Stop/Reboot 可选 `ForceStop`） | github.com/volcengine/volcengine-go-sdk `service/ecs` |
| VPC：`DescribeSecurityGroupAttributes`、`AuthorizeSecurityGroupIngress`、`RevokeSecurityGroupIngress`（必填 `SecurityGroupId`、`Protocol`、`PortStart`、`PortEnd`；可选 `CidrIp`、`Description`、`Policy`、`Priority`） | 同 SDK `service/vpc` |

## 脚本里的假设（未核实，出问题先查这里）

1. `Policy` 取值 `accept` / `drop`，`Direction` 取值 `ingress` / `egress`，实例状态 `RUNNING` / `STOPPED`（大小写不敏感比较）：来自常见用法，SDK 源码没有枚举。
2. `icmp` / `all` 协议的端口写 `-1`：沿用多数云厂商的约定，未在火山文档里确认。
3. 撤销规则时除 `CidrIp`、协议、端口外还带上现有规则的 `Policy` 和 `Priority`：这两个是 Revoke 的可选字段，是否参与匹配未核实。
4. 响应业务错误在 `ResponseMetadata.Error.{Code,Message}`，且 `ve` 对业务错误可能返回非零退出码：脚本两种都处理。`ve` 的退出码与错误 JSON 官方文档没写。
5. `tosutil ls` 的桶列表行格式未知，脚本只认其中的 `tos://<桶名>`；认不出时报 `tosutil_output_unrecognized`，不当作「没有桶」。
6. `tosutil lifecycle -method get` 与 `tosutil versioning -method get` 的命令名和写法未核实：脚本先用 `tosutil help` 确认命令存在，结果里带 `tosutil_syntax_unverified` 提示。需要时让用户在 TOS 控制台确认。
7. 测试夹具是按上述字段手写的合成输出，不是真实录制；拿到真实输出后同名替换（见 `tests/volc/fixtures/README.md`）。

## 对应旧工具

| 旧工具 | 本 skill |
|---|---|
| `vec …` = `ve --profile <profile> …` | 所有 `ve` 调用自动带 `--profile`，名称来自配置 |
| `ssh-access-sync.sh` | `sg-sync-ip`：描述标记 + 先加后撤；探测公网 IP 的方式在原脚本里不可见，这里改为 `--ip` / `--ip-url` |
| `pssh <别名>` | `ssh-exec --host <别名>`，只用 OpenSSH 配置里的别名，`BatchMode=yes` |
