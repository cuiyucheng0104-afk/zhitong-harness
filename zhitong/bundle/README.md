# @zhitong/bundle

智通数工AI 的 profile 层：在 `dsh-base` + `dsh-web-app` 之上挂 TOS 工具、配置包导入、`zhitong/skills` 目录与默认预设「智通数工AI」（造价人设）。安装与启动见 [zhitong/INSTALL.md](../INSTALL.md)，各行的作用写在 [cordis.patch.yml](cordis.patch.yml) 的注释里。

- `preset-zhitong` 的插件列表照抄上游 `packages/bundle/web-app/presets/standard.patch.yml`，只换人设；合入上游后对照同步。
- skill 目录路径由 profile 解析 `@zhitong/bundle/package.json` 得到，bundle 必须作为 profile 依赖安装（`dsh plugin --profile zhitong add link:…`）。
- TOS 连接设置不在本层，由 `config_import` 写进 profile 自己的 `cordis.patch.yml`。
