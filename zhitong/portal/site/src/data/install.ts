/**
 * 安装与交付（05 章 §3.2）。版本、日期、文件名、大小、SHA256 不写在这里，全部来自 `downloads.ts` 的 `release`。
 * 平台卡内部文案（名称、适用说明、下载按钮、校验、首次打开）与 01 章 §7.2 相同，由 `PlatformCard` 与 `downloads.ts` 提供。
 */
export const INSTALL_COPY = {
  eyebrow: '安装与交付',
  title: '装好、导入、开始用',
  lead: 'Mac 与 Windows 两个安装包，配置包由服务方交付。',
  packageTitle: '安装包',
  packageBody:
    '提供 Mac（.dmg，Apple 芯片）和 Windows（.exe，x64）安装包。安装包内含 Python 运行时、脚本依赖库和 DWG 转换组件，无需另行安装 Python。',
  releaseDate: (date: string | null) => (date ? `${date} 发布` : '发布日期待定'),
  base: (base: string) => `安装后，“关于”中显示的程序版本为 ${base}。`,
  listLabel: (version: string) => `v${version} 安装包`,
  helpLink: { text: '安装遇到问题？看安装说明', href: '/docs/install/' },
  mobileNote:
    '您正在使用手机或平板。安装包需要在 Mac 或 Windows 电脑上安装，可以把本页链接发到电脑上打开。',
  copyPage: '复制页面链接',
  copiedPage: '已复制页面链接',
  configTitle: '配置包',
  /** 反引号片段等宽显示。 */
  configBody:
    '配置包是服务方按贵司环境整理的一个压缩文件（内含 `zhitong.config.json`），不随安装包分发，也不在本站提供下载。',
  configItems: [
    '公司名称',
    '对象存储的地址、区域、桶名与目录前缀',
    '访问密钥（导入后存入本机凭据存储）',
    '可选：SSH 主机别名、地址与私钥',
    '可选：火山引擎 ve 的 profile 名（ve 自己的密钥由您在终端里单独设置，不放进配置包）',
  ],
  configWarning:
    '配置包含明文密钥：导入后请从下载目录删除，不要转发。更换密钥时，服务方发来新配置包，重新导入即可。',
  firstTitle: '首次使用',
  firstBody:
    '首次启动先在欢迎页填写模型 API Key（向贵司管理员或服务方获取，默认连接 DeepSeek 官方接口），再把配置包拖进对话，系统校验并写入本机配置，随后即可列出公司桶里的项目。本机只缓存用到的文件，目录与桶同构，缓存上限可配置，默认 20 GiB。',
  contactTitle: '联系服务方',
  contactLead: '安装包与配置包向服务方获取。',
  docLink: { text: '读文档：导入配置包', href: '/docs/config-package/' },
} as const;
