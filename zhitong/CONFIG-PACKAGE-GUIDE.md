# 智通数工AI 客户配置单制作指南

一个客户 = 桶里一个前缀 + 一把只能访问这个前缀的访问密钥 + 一个 zip 配置包。客户把 zip 拖进智通数工AI 的对话窗口，agent 导入后就能读写 `桶/前缀/` 下的项目。

本文分五部分。A 是你自己在火山引擎控制台做的事（建策略、建子用户、拿密钥）；B 是把 A 交给本机 Claude Code 代办的提示词；C 是做 zip 的脚本；D 是发给客户时的话术与纪律；E 是每次发放前的检查清单。格式细节见 [CONFIG-PACKAGE.md](CONFIG-PACKAGE.md)。

本机目录约定：`~/Desktop/智数通工客户配置单/`（你建的文件夹名，照用），每个客户一个子目录，根目录放一份 `发放记录.md`。

## A. 火山引擎控制台（手工，每个客户一次）

### A0 准备

- 用主账号登录 <https://console.volcengine.com>。
- 记下三样东西：桶名、区域（如 `cn-beijing`）、外网 endpoint（TOS 控制台 → 桶 → 概览，形如 `tos-cn-beijing.volces.com`）。
- 确认桶已开版本控制（TOS 控制台 → 桶 → 基础设置 → 版本控制）。多人共用不加锁，靠版本回退恢复覆盖。
- 决定客户前缀：公司简称，不含空格、斜杠和 `.`，例如 `智通数工`、`某某咨询`。第一个客户就是你自己的 NAS 资料，前缀用 `智通数工`。
- 命名约定：IAM 用户名 `zt-<客户简称拼音>`，策略名 `ZT-TOS-<客户简称拼音>`。全小写拼音，例如 `zt-zhitongshugong` / `ZT-TOS-zhitongshugong`。

相关文档（文档中心编号，打不开就在 <https://www.volcengine.com/docs> 搜标题）：IAM 快速入门「新建用户并授权」`docs/6257/94013`；IAM 基础概念 `docs/6257/64963`；TOS「授权 IAM 用户」`docs/6349/173832`；TOS「常见 IAM 策略」`docs/6349/1189130`。

### A1 新建自定义策略

访问控制 IAM → 策略管理 → 新建策略 → JSON 编辑，粘贴下面的策略，把 `__BUCKET__` 换成桶名、`__PREFIX__` 换成前缀（三处）。模板文件在仓库 `zhitong/scripts/tos-prefix-policy.template.json`。

```json
{
  "Statement": [
    {
      "Effect": "Allow",
      "Action": ["tos:ListBucket", "tos:GetBucketLocation", "tos:GetBucketVersioning"],
      "Resource": ["trn:tos:::__BUCKET__"],
      "Condition": { "StringLike": { "tos:prefix": ["__PREFIX__/*", "__PREFIX__/", "__PREFIX__"] } }
    },
    {
      "Effect": "Allow",
      "Action": ["tos:GetObject", "tos:GetObjectVersion", "tos:PutObject", "tos:DeleteObject",
                 "tos:AbortMultipartUpload", "tos:ListMultipartUploadParts"],
      "Resource": ["trn:tos:::__BUCKET__/__PREFIX__/*"]
    }
  ]
}
```

第一段只允许在这个前缀下列目录，第二段只允许读写这个前缀下的对象。控制台保存时会做语法校验；报错就按它提示的字段改。这份策略按火山 TOS 官方示例的写法整理，`tos:prefix` 条件与 `trn:tos:::桶/前缀/*` 资源格式来自官方文档，但本仓库编写环境访问不到 volcengine.com，没有逐字核对过，所以 C 部分的脚本会用真实密钥做一次探测，策略没限住会直接报错。

### A2 新建子用户并附加策略

访问控制 IAM → 用户管理 → 新建用户：

1. 用户名 `zt-<客户简称拼音>`，显示名写公司全名。
2. 访问方式只勾「编程访问」（OpenAPI 访问密钥）。不要开控制台登录。
3. 权限：选「直接授权」，勾上 A1 的策略，不要勾任何系统预设的 TOS 全量策略。
4. 创建完成页会显示 AccessKey ID 和 SecretAccessKey。**SecretAccessKey 只显示这一次**，当场交给 C 部分的脚本，或下载 CSV 后做完包立刻删掉。

### A3 轮换与撤销

- 客户工程师离职或密钥疑似泄露：IAM → 用户 → 该用户 → 密钥 → 禁用（或删除），再新建一把密钥，按 C 重做一个 zip 发给客户，客户重新拖入即可覆盖。
- 客户终止服务：禁用密钥，再删用户；桶里的前缀目录按合同约定导出或删除。
- 每次动作在 `发放记录.md` 追加一行。

## B. 让本机 Claude Code 代办（提示词）

前提：你的 Mac 上有 `vec`（即 `ve --profile zt-ak`，主账号或有 IAM 管理权限的密钥），仓库在 `~/Desktop/zhitong-harness`，`pnpm install` 已做过。在仓库目录里开一个 Claude Code 会话，把下面整段贴进去，三个尖括号的位置先改好。

密钥会经过 agent 的对话上下文一次，这是自动化无法避免的；会话结束后不要把这段对话分享出去。不想让它经手，就按 A 手工建用户，只把 C 的脚本交给它跑。

```text
请为智通数工AI 的一个客户制作配置包。严格按下面步骤做，每一步先把将执行的命令打出来，等我确认再执行；任何一步失败就停下来报告，不要自行改参数重试。

客户信息：
- 公司名：<公司全名>
- 客户简称拼音：<例如 zhitongshugong>
- 桶名：<桶名>
- 前缀：<例如 智通数工>
- 区域：cn-beijing
- endpoint：tos-cn-beijing.volces.com
- 输出目录：~/Desktop/智数通工客户配置单/<公司全名>

规则：
- 只用 `vec`（它等于 `ve --profile zt-ak`）调火山引擎 OpenAPI，不要用 `ve configure`，不要改 profile。参数名以 `vec iam <Action> --help` 为准；下面写的参数名来自官方 Go SDK（CreateUser：UserName/DisplayName/Description；CreatePolicy：PolicyName/PolicyDocument/Description；AttachUserPolicy：UserName/PolicyName/PolicyType；CreateAccessKey：UserName），不一致时以 --help 为准，并告诉我差异。
- 密钥只能出现在命令的环境变量里和脚本生成的配置文件里。不要把 SecretAccessKey 写进任何其他文件、不要 echo、不要放进提交。
- 不要删除、禁用任何已有的用户、策略、密钥。

步骤：
1. `vec sts GetCallerIdentity` 确认身份；输出里的账号 ID 告诉我。
2. 用 `vec iam ListPolicies` 和 `vec iam ListUsers` 查有没有同名策略 `ZT-TOS-<简称拼音>` 和同名用户 `zt-<简称拼音>`。已存在就复用并告诉我，不要重建。
3. 读取仓库里的 zhitong/scripts/tos-prefix-policy.template.json，把 __BUCKET__ 替换成桶名、__PREFIX__ 替换成前缀（三处），得到策略 JSON。把替换后的 JSON 完整打给我看。
4. `vec iam CreatePolicy --PolicyName ZT-TOS-<简称拼音> --Description "智通数工AI 客户 <公司全名>：只读写 tos://<桶名>/<前缀>/" --PolicyDocument '<上一步的 JSON，单行>'`。
5. `vec iam CreateUser --UserName zt-<简称拼音> --DisplayName "<公司全名>" --Description "智通数工AI 配置包专用，只有编程访问"`。
6. `vec iam AttachUserPolicy --UserName zt-<简称拼音> --PolicyName ZT-TOS-<简称拼音> --PolicyType Custom`（PolicyType 的取值用 --help 核对）。
7. `vec iam CreateAccessKey --UserName zt-<简称拼音>`。把返回的 AccessKeyId 末四位告诉我，SecretAccessKey 不要在回复里出现。
8. 在仓库目录执行（把两个值放在环境变量里，一条命令完成）：
   ZT_PKG_ACCESS_KEY_ID=<AccessKeyId> ZT_PKG_SECRET_ACCESS_KEY=<SecretAccessKey> pnpm exec tsx zhitong/scripts/make-config-package.ts --company "<公司全名>" --bucket <桶名> --prefix <前缀> --endpoint tos-cn-beijing.volces.com --region cn-beijing --comment "<今天日期> 首次发放" --out "~/Desktop/智数通工客户配置单/<公司全名>" --expect-prefix-only
   这个脚本会用这把密钥真连一次桶：列前缀、写一个探测对象再删掉、并确认列桶根目录被拒绝；三项有一项不过就不会生成包，把它的报错原样给我。新建的策略和用户可能要等一两分钟才生效，探测报 403 时等 60 秒再重跑这一条，最多三次。
9. 成功后在 ~/Desktop/智数通工客户配置单/发放记录.md 追加一行（没有就新建，表头：日期 | 公司 | IAM 用户 | AK 末四位 | 前缀 | zip 文件名 | 经手人），然后把 zip 的路径和 sha256 告诉我。
10. 最后列出我接下来要手工做的事：把 zip 发给客户、发完删除同目录下的明文 zhitong.config.json、CSV 之类的副本。
```

agent 做完后，你只剩 D 部分。

## C. 做 zip 的脚本（手工建用户时用）

密钥通过环境变量传入，不走命令行参数，所以不会进 shell 历史：

```bash
cd ~/Desktop/zhitong-harness
ZT_PKG_ACCESS_KEY_ID='AKLT…' ZT_PKG_SECRET_ACCESS_KEY='…' \
pnpm exec tsx zhitong/scripts/make-config-package.ts \
  --company "某某工程造价咨询有限公司" --bucket zt-company --prefix 某某咨询 \
  --endpoint tos-cn-beijing.volces.com --region cn-beijing \
  --comment "2026-10-21 首次发放" \
  --out "$HOME/Desktop/智数通工客户配置单/某某工程造价咨询有限公司" --expect-prefix-only
```

它做四件事：

1. 用 `config_import` 同一套校验规则检查字段，所以生成的包一定能被应用导入。
2. 用这把密钥真连桶：列前缀、在前缀下写一个探测对象再读再删、`--expect-prefix-only` 时再确认列桶根目录返回 403。任何一项失败就退出码 2、不生成文件，报错里不含密钥。
3. 写 `<out>/<公司名>/zhitong.config.json`（权限 0600）和 `<out>/<公司名>-zhitong-config-<日期>.zip`，zip 里只有一层目录加这一个文件，正是 `config_import` 接受的布局。
4. 打印摘要：公司、桶、前缀、AK 末四位。不打印密钥。

同一天重做要先删掉旧 zip，脚本不覆盖已有文件。只想生成不连桶（比如桶还没建好）加 `--skip-probe`，但这样的包不要发给客户。

## D. 发给客户

发什么：只发 zip。不要发明文 json，不要发策略，不要发 IAM 用户名密码（本来就没有）。

怎么发：微信、企业微信或邮件都可以，zip 本身含明文密钥，所以发完让对方确认收到后把聊天记录里的文件撤回或删除；不要放到公开网盘链接。

给客户的话术（可以直接复制）：

```text
您好，这是贵司的智通数工AI 配置包（zip，不用解压）。
使用方法：打开智通数工AI，把这个 zip 文件拖进对话窗口，输入「导入配置包」，agent 校验后会显示公司名和桶里的项目列表。
这个文件里有访问贵司资料桶的密钥，请只在公司内部传给需要使用的工程师，不要转发到外部；导入成功后可以把文件删除。
每位工程师第一次打开应用时，还需要在引导页填写自己的 DeepSeek API Key（在 platform.deepseek.com 申请），这个不在配置包里。
```

发完以后在本机做两件事：删除 `<公司名>/zhitong.config.json` 明文文件（zip 留着备查，放在加密磁盘或密码管理器附件里更好）；`发放记录.md` 补一行。

## E. 发放前检查清单

- [ ] 前缀已定，与桶里实际的目录名一致（迁移脚本整理时用的就是这个前缀）。
- [ ] 策略只覆盖这个前缀：脚本的 `--expect-prefix-only` 探测通过。
- [ ] 子用户只有编程访问，没有控制台登录。
- [ ] 密钥 CSV、明文 json 已删除，只剩 zip。
- [ ] `发放记录.md` 已追加。
- [ ] 客户知道还要自备 DeepSeek API Key。
- [ ] 第一个客户（你自己的 NAS 资料）：先完成 `zhitong/migration/` 的整理与上传，再发配置包，否则 agent 连上桶看到的是空目录。
