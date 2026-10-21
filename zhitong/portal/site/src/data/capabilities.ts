/**
 * 产品能力（04 章 §5.2–§5.5）：12 项能力的唯一文案出处、术语说明卡正文、默认选中项与小动画用到的示例数字。
 *
 * 类型按 04 章 §5.2 定义在本文件（`types/portal.ts` 归底座，迁移由主控决定）；
 * 06 章路由表标题、03 章任务入口的能力 id 都以这里为准（00 章 §14 第 10 条）。
 */
import type { SceneId } from '../types/portal';

export type GroupId = 'project' | 'calculate' | 'output' | 'knowledge';
export type FeatureId =
  | 'project'
  | 'qa'
  | 'cad'
  | 'check'
  | 'metrics'
  | 'control'
  | 'estimate'
  | 'report'
  | 'bills'
  | 'archive'
  | 'knowledge'
  | 'cloud';
export type GlossaryKey = '公司存储桶' | '项目说明' | '案例索引' | '待确认清单' | '配置包';
export type IconName =
  | 'folder'
  | 'chat'
  | 'cad'
  | 'sheet'
  | 'calc'
  | 'shield'
  | 'file'
  | 'archive'
  | 'team'
  | 'cloud';

export interface FeatureOutput {
  /** 项目内相对路径（知识库、案例索引除外），/ 分隔。 */
  path: string;
  /** 括号内备注。 */
  note?: string;
}

export interface Feature {
  id: FeatureId;
  /** 眉题里显示的 skill 名。 */
  skill: `zt-${string}`;
  /** 列表与文档标题。 */
  name: string;
  badge?: '管理员';
  icon: IconName;
  /** `${组名} · ${skill}` */
  kicker: string;
  /** h3 */
  title: string;
  description: string;
  /** 需要什么 */
  input: string;
  /** 得到什么 */
  output: string;
  /** 您可以这样说（用户原话） */
  say: readonly [string, string];
  outputs: readonly FeatureOutput[];
  caution: string;
  cautionLevel: 'info' | 'warn';
  /** 有值才显示“查看工作示例”。 */
  scene?: SceneId;
  docs: `/docs/features/${FeatureId}/`;
  terms: readonly GlossaryKey[];
  /** false 时不在首页出现，计数与尺寸线随之变化。 */
  home: boolean;
  /** loop：循环总时长（秒），04 章 §7 各节的值。 */
  art: { caption: string; loop: number };
}

export interface FeatureGroup {
  id: GroupId;
  label: string;
  icon: IconName;
  intro: string;
  features: readonly Feature[];
}

const docs = <T extends FeatureId>(id: T) => `/docs/features/${id}/` as const;

export const featureGroups = [
  {
    id: 'project',
    label: '项目资料',
    icon: 'folder',
    intro: '开工之前：弄清项目、找到资料、读懂图纸。',
    features: [
      {
        id: 'project',
        skill: 'zt-project',
        name: '开项目与资料盘点',
        icon: 'folder',
        kicker: '项目资料 · zt-project',
        title: '先看清项目，再开始工作。',
        description:
          '打开项目先读项目说明；新项目按年份分配 YYYY-NNN 编号并登记进案例索引。资料盘点只看文件名和目录，按咨询类型与阶段对照资料清单，列出已备、待确认和缺失的资料。',
        input: '公司存储桶里的项目目录；咨询类型与阶段（项目说明里没有时会问您）',
        output: '项目说明（编号、关键文件指引、已出成果）与资料盘点结论',
        say: ['2026-007 的资料齐不齐？缺什么？', '打开 2026-007，告诉我关键文件都在哪。'],
        outputs: [
          { path: '项目说明.md' },
          { path: '工作/2026-10-19-盘点/文件清单.txt' },
          { path: '工作/2026-10-19-盘点/result.json' },
        ],
        caution: '只看文件名，不读内容、不给文件贴标签；资料清单与分类规则目前待签核。',
        cautionLevel: 'warn',
        docs: docs('project'),
        terms: ['公司存储桶', '项目说明', '案例索引'],
        home: true,
        art: {
          loop: 7.6,
          caption:
            '示意动画（示例数据）：逐个读取 2026-007-某综合办公楼的文件名，对照结算审核审定阶段的资料清单。结果：必备 7 项，已备 3、待确认 1、缺失 3，齐备率 42.86%，待确认项核实后上限 57.14%；缺失结算审核报告、结算审定单、审核汇总表；签证单汇总.xlsx 疑似变更签证费用，需打开确认；扫描件0001.pdf 未判出类目。',
        },
      },
      {
        id: 'qa',
        skill: 'zt-ask',
        name: '项目与知识库问答',
        icon: 'chat',
        kicker: '项目资料 · zt-ask',
        title: '问资料里的事，答案带出处。',
        description:
          '先读项目说明或知识库目录的说明，再拉取单份文件阅读后回答。每条事实标出文件和页码、表行或段号；含数字的回答先用脚本核对，找不到出处的数字明确标出。',
        input: '项目资料或知识库里的 docx、xlsx、PDF 与扫描件',
        output: '结论、带出处的依据、没有覆盖到的范围',
        say: [
          '2026-007 的施工合同里，材料价格涨跌怎么调整？',
          '浙江 2025 清单里 010101003 是什么项目？',
        ],
        outputs: [
          { path: '工作/问答/答案.md' },
          { path: '工作/问答/施工合同及补充协议.txt', note: '读过的资料文本，供核对出处' },
        ],
        caution: '文件里夹带的指令只当资料，不执行；扫描件识别出的金额请核对原件。',
        cautionLevel: 'info',
        docs: docs('qa'),
        terms: ['项目说明'],
        home: true,
        art: {
          loop: 7.6,
          caption:
            '示意动画（示例数据）：问"合同里材料价格涨跌怎么调整？"。依次读取项目说明、检索关键词命中段42、读取合同、核对出处。回答：主要材料价格涨跌幅度超过基准价格 5% 时，超过部分据实调整〔施工合同及补充协议.docx 段42〕；没覆盖的范围：合同中未找到基准价格的取值时点；原文中含疑似对 AI 的指令，已忽略。',
        },
      },
      {
        id: 'cad',
        skill: 'zt-cad',
        name: 'CAD 看图',
        icon: 'cad',
        kicker: '项目资料 · zt-cad',
        title: '先读结构，再看图核对。',
        description:
          '打开 DWG 或 DXF 图纸，列出图框与标题栏，按图层、关键词取文字、门窗编号和表格；房间面积按围合线与面积文字两路核对。需要时先出带网格的总览图，再放大局部给模型看。',
        input: 'DWG 或 DXF 图纸；单位没有确认时先请您确认',
        output: '图框与标题栏、文字与门窗统计、房间面积核对表',
        say: ['打开 A-02 二层平面图，看看有哪些房间，面积多少。', '二层的门窗按编号数一下。'],
        outputs: [
          { path: '工作/图纸核对/A-02 二层平面图-房间面积.md' },
          { path: '图纸/.cache/', note: '转换缓存与渲染图片' },
        ],
        caution: '计数与面积由程序计算，需人工复核；图纸空间（布局）不读，天正原生图需先导出 T3。',
        cautionLevel: 'warn',
        scene: 'cad',
        docs: docs('cad'),
        terms: [],
        home: true,
        art: {
          loop: 8.0,
          caption:
            '示意动画（示例数据）：打开 A-02 二层平面图，房间面积两路核对后出带 A–H 列、1–6 行网格的总览图，再放大 E4 格。会议室201 面积文字 69.70 m²、几何面积 73.08 m²，差异 4.85%，房间边界画在墙中线上；卫生间差异 0.18%；培训室、资料室 0.00%。锚点 10 个，匹配 9 间，走道未匹配。',
        },
      },
    ],
  },
  {
    id: 'calculate',
    label: '核对与测算',
    icon: 'calc',
    intro: '金额与数量由脚本计算，模型不算钱。',
    features: [
      {
        id: 'check',
        skill: 'zt-reconcile',
        name: '送审审定核对',
        icon: 'sheet',
        kicker: '核对与测算 · zt-reconcile',
        title: '核增核减，逐行对得上。',
        description:
          '定位送审与审定两张计价表，预检后逐行核对：编码优先，名称、特征、单位兜底。按章汇总核减额与核减率，拆出量差与价差；每一行都能回到原表的工作表和行号。',
        input: '送审与审定计价表（.xlsx；.xls 请另存为 .xlsx，广联达工程文件请先导出 Excel）',
        output: '核对结果.xlsx（汇总、逐行核对、按章汇总）与待确认清单',
        say: [
          '核对一下送审和审定计价表。',
          '混凝土这章为什么核减这么多？把核减最大的 10 行列出来。',
        ],
        outputs: [
          { path: '工作/2026-10-19-核对/核对结果.xlsx' },
          { path: '工作/2026-10-19-核对/result.json' },
          { path: '工作/2026-10-19-核对/待确认清单.md' },
        ],
        caution: '金额由脚本取数计算，需人工复核，不是审定结论。',
        cautionLevel: 'warn',
        scene: 'check',
        docs: docs('check'),
        terms: ['待确认清单'],
        home: true,
        art: {
          loop: 7.75,
          caption:
            '示意动画（示例数据）：送审计价表与审定计价表按编码逐行配对：现浇构件钢筋核减 303,556.71 元，综合脚手架第 46 行仅送审 125,120.00 元，有梁板核减 56,688.78 元，金属（塑钢、断桥）窗核增 26,408.05 元，散水、坡道一行审定合价为空，待核实。汇总：送审合计 30,530,406.80 元，审定合计 29,623,713.84 元，核减额 906,692.96 元，核减率 2.97%；逐行 1,284 行：一致 1,031、调整 214、仅送审 23、仅审定 9、待核实 7。',
        },
      },
      {
        id: 'metrics',
        skill: 'zt-indicator',
        name: '造价指标',
        icon: 'calc',
        kicker: '核对与测算 · zt-indicator',
        title: '单方、占比、对标，口径写在旁边。',
        description:
          '由计价表算总造价或清单明细合计、单方造价、各章占比与单方、造价驱动项；建筑面积只用项目说明或资料里写明的数。可从案例索引抄出同业态项目，与同类均值比较偏差。',
        input: '计价表、写明出处的建筑面积；对标时用案例索引里的同类项目',
        output: '指标结果.xlsx（汇总、指标、按章、造价驱动项、未计入文件）',
        say: [
          '用审定计价表算指标，面积按项目说明里的 18,600 平方米。',
          '找两个公司做过的办公楼，和本项目的单方对标一下。',
        ],
        outputs: [
          { path: '工作/2026-10-20-指标/指标结果.xlsx' },
          { path: '工作/2026-10-20-指标/对标.json' },
          { path: '工作/2026-10-20-指标/待确认清单.md' },
        ],
        caution: '每个数都带口径标签，清单明细合计不是总造价；结果需人工复核。',
        cautionLevel: 'info',
        docs: docs('metrics'),
        terms: ['案例索引', '项目说明'],
        home: true,
        art: {
          loop: 8.0,
          caption:
            '示意动画（示例数据）：清单明细合计 29,623,713.84 元 ÷ 建筑面积 18,600.00 m²（来源：项目说明）＝ 单方 1,592.67 元/m²，清单明细合计口径，不是总造价。占比最高三章：混凝土及钢筋混凝土工程 61.49%、措施项目 13.47%、门窗工程 9.95%。对标案例索引中 2 个办公项目：某科创中心一期 1,688.40、某政务服务中心 1,571.20，同类均值 1,629.80 元/m²，本项目偏差 −2.28%。',
        },
      },
      {
        id: 'control',
        skill: 'zt-tk',
        name: '投控异常检测与复核',
        icon: 'shield',
        kicker: '核对与测算 · zt-tk',
        title: '疑似逐条看，结论由您定。',
        description:
          '对送审计价表检测重复计取、暂估价、量价不自洽和大额项；提供合同或中标清单时，再查单价超合同、工程量超合同、漏报与合同外新增。疑似项在对话里逐条复核，每个决定连同理由追加记录。',
        input: '送审计价表；可选合同或中标清单',
        output: '投控异常.xlsx 与复核记录（每条决定带理由，可记复核人）',
        say: ['对 2026-007 的送审计价表做一下投控检测。', '从置信高的开始，一次给我看 5 条。'],
        outputs: [
          { path: '工作/2026-10-19-投控/投控异常.xlsx' },
          { path: '工作/2026-10-19-投控/复核.jsonl' },
          { path: '工作/2026-10-19-投控/待确认清单.md' },
        ],
        caution:
          '检测只给疑似，终判由造价师作出；规则阈值为草案（tk_detect.yaml v1-20260711），未经客户确认。',
        cautionLevel: 'warn',
        scene: 'review',
        docs: docs('control'),
        terms: [],
        home: true,
        art: {
          loop: 7.2,
          caption:
            '示意动画（示例数据）：对送审计价表做投控检测，未提供合同清单，单价超合同、工程量超合同、漏报、合同外新增 4 条规则未运行。共 290 条疑似：重复计取 2、整项存疑-暂估价 1、整项存疑-自洽 1、整项存疑-大额 286。按金额先看第一条：综合脚手架第 46 行与第 28 行编码、名称、特征、工程量相同，送审金额各 125,120.00 元，疑似重复计取；您选"确认异常"，决定连同理由追加到复核.jsonl，已确认 1、待复核 289。',
        },
      },
      {
        id: 'estimate',
        skill: 'zt-estimate',
        name: '概算编制辅助',
        icon: 'calc',
        kicker: '核对与测算 · zt-estimate',
        title: '数先确认，再进公式。',
        description:
          '从设计说明、可研或经济技术指标表抽取 11 个规模量输入位的候选值，每个附原文引文并回查。只有您确认过的数才进入计算；按 gsyz_v1 模板写出带真实公式的估算或概算表，改输入格或预备费率即可复算。',
        input: '设计说明、可研或经济技术指标表；您确认或补充的输入',
        output: '概算.xlsx：499 条真实公式，预备费率在"估概算总表!J46"单独一格',
        say: ['按设计说明做一版概算，先把规模量找出来给我确认。', '预备费率改成 3%。'],
        outputs: [
          { path: '工作/2026-10-20-概算/概算.xlsx' },
          { path: '工作/2026-10-20-概算/待确认清单.md' },
          { path: '成果/概算.xlsx', note: '您确认后推送' },
        ],
        caution:
          '抽取阶段不出金额；费率规则为仓主默认放行、非造价员签署，随包指标基准只作单样本参考。',
        cautionLevel: 'warn',
        docs: docs('estimate'),
        terms: [],
        home: true,
        art: {
          loop: 8.0,
          caption:
            '示意动画（示例数据）：从竣工图总说明的经济技术指标抽出 6 个规模量候选并标出原文：用地面积 6,850、A区地下室 3,400、1#楼 15,200、A区地块占地 2,740（m²），地面停车 24、地下停车 86（辆）；槽位合计与原文总建筑面积 18,600 m² 相符。您确认后，其余 5 个输入位填 0；概算表写真实公式，例如 估概算总表!C46 =(C5+C45)*J46，预备费率 J46 为 5%。',
        },
      },
    ],
  },
  {
    id: 'output',
    label: '成果与归档',
    icon: 'file',
    intro: '过程留在"工作"，交付进"成果"，归档后下一个项目查得到。',
    features: [
      {
        id: 'report',
        skill: 'zt-report',
        name: '报告撰写',
        icon: 'file',
        kicker: '成果与归档 · zt-report',
        title: '逐章写初稿，句句标资料。',
        description:
          '内置 24 套模板、172 章写作要求。选定模板后按章取材，每句标注 [资料n]；金额只写占位符，由程序换成单元格原值并注明来源。未经您确认的程序性陈述标【待核】，资料里没有的写【待补】。可导出 Word，也可套公司正式模板。',
        input: '项目资料、审定单或审核汇总表、您确认过的程序性事项',
        output: 'Word 初稿（页眉标注 AI 初稿），附来源文件、各章质量与待核清单',
        say: ['给 2026-007 写一份结算审核报告。', '只重写第五章审核结果。'],
        outputs: [
          { path: '成果/某综合办公楼结算审核报告-初稿.docx' },
          { path: '工作/2026-10-20-报告/章节/' },
        ],
        caution: '初稿须由持证造价工程师审校；金额未经人工核对，不得直接出具。',
        cautionLevel: 'warn',
        docs: docs('report'),
        terms: [],
        home: true,
        art: {
          loop: 8.0,
          caption:
            '示意动画（示例数据）：结算审核报告（房建）共 9 章，正在写"五、审核结果"。草稿只写金额占位符〔F1〕至〔F5〕；定稿时程序换成单元格原值：送审金额 30,530,406.80 元、审定金额 29,623,713.84 元、核减金额 939,305.70 元、核增额 32,612.74 元、净核减金额 906,692.96 元，来源审核汇总表!C10 至 G10。安装工程资料没有，标【待补：安装工程送审与审定金额】。',
        },
      },
      {
        id: 'bills',
        skill: 'zt-quantity',
        name: 'GB50854 清单框架',
        icon: 'sheet',
        kicker: '成果与归档 · zt-quantity',
        title: '从做法表，搭起清单框架。',
        description:
          '适用房屋建筑与装饰工程（分部 0101–0118）。脚本把设计说明和做法表切成做法片段，逐片段判断单独列项、并入主项特征或作为基层；编码只能取自 490 条受控码表，语义不一致的降为待核，不自动改码。',
        input: '建筑设计说明或工程做法表（xlsx、docx、文字层 PDF）',
        output: '清单框架.xlsx 四张表：分部分项工程量清单、待核与未匹配、覆盖核算、说明',
        say: ['按竣工图总说明里的做法表出一份清单框架。', '楼 1 地砖楼面该套哪条编码？'],
        outputs: [
          { path: '工作/2026-10-20-清单/清单框架.xlsx' },
          { path: '工作/2026-10-20-清单/待确认清单.md' },
          { path: '成果/清单框架.xlsx', note: '您确认后推送' },
        ],
        caution: '工程量列留空，需人工计算；码表为浙江 2025 草稿口径，未经造价员签字。',
        cautionLevel: 'warn',
        docs: docs('bills'),
        terms: [],
        home: true,
        art: {
          loop: 7.7,
          caption:
            '示意动画（示例数据）：楼1 地砖楼面的 4 层做法逐层判断：防滑地砖面层单独列项，结合层与素水泥浆并入特征，钢筋混凝土楼板作为基层。得到清单项 011102003001 块料楼地面（m²），特征摘录结合层厚度 20厚、面层材料厚度 10厚，找平层厚度待补；工程量留空。屋面 40厚C20细石混凝土保护层被给了 011101002，与部位不一致，降为待核。覆盖核算：片段 148 = 去向 148。',
        },
      },
      {
        id: 'archive',
        skill: 'zt-archive',
        name: '归档与案例索引',
        icon: 'archive',
        kicker: '成果与归档 · zt-archive',
        title: '这次的成果，下次找得到。',
        description:
          '归档前核对"成果"与"工作"目录：项目说明是否完整、成果是否登记、待确认清单是否处理完。经您确认后推回公司存储桶并回读校验，更新项目说明，在案例索引里只改本项目这一行。',
        input: '本机的项目副本与最新的案例索引',
        output: '推送并回读一致的文件、更新后的项目说明与案例索引行',
        say: ['2026-007 做完了，归档。', '归档前先帮我检查一下 2026-007 的成果和工作目录齐不齐。'],
        outputs: [{ path: '项目说明.md' }, { path: '案例索引.md', note: '公司存储桶根目录' }],
        caution: '关键指标只写已算好的数并注明口径；归档不删除任何文件。',
        cautionLevel: 'info',
        docs: docs('archive'),
        terms: ['公司存储桶', '待确认清单', '案例索引'],
        home: true,
        art: {
          loop: 7.6,
          caption:
            '示意动画（示例数据）：归档核对 2026-007：成果 3 个文件、工作目录 5 个，无阻断项；2 个待确认清单还有未勾选事项，写进工作记录。您确认后推送并回读一致。案例索引新增本项目一行：编号 2026-007，工程名某综合办公楼，业态办公，规模 18,600.00 m²，咨询类型结算审核，关键指标审定单方 1,592.67 元/m²（清单明细合计口径）、核减率 2.97%，成果链接 项目/2026-007-某综合办公楼/成果/，状态已归档。',
        },
      },
    ],
  },
  {
    id: 'knowledge',
    label: '知识与协作',
    icon: 'team',
    intro: '知识库所有项目可读；运维面向公司管理员。',
    features: [
      {
        id: 'knowledge',
        skill: 'zt-knowledge',
        name: '企业知识库',
        icon: 'file',
        kicker: '知识与协作 · zt-knowledge',
        title: '每条经验，都有来源和日期。',
        description:
          '知识库按规范、定额、费率、模板、公司经验分目录存放，所有项目都能读。工作中发现的口径经您确认后写入"公司经验"，每条记下来源、日期、适用范围与核验状态；搜不到的内容写明搜不到。',
        input: '项目资料或网页原文中的依据；您确认的写入内容',
        output: '带来源与日期的知识条目，校验通过后推回公司存储桶',
        say: [
          '把合同里材料涨跌超过 5% 据实调整这条，写进公司经验。',
          '检查一下知识库，有没有缺来源、缺日期的条目。',
        ],
        outputs: [
          { path: '知识库/公司经验/结算审核-材料调差风险幅度口径.md' },
          { path: '知识库/公司经验/README.md' },
        ],
        caution: '只凭网页摘要整理的条目标"待核"；不建向量索引，按目录按需读取。',
        cautionLevel: 'info',
        docs: docs('knowledge'),
        terms: ['公司存储桶'],
        home: true,
        art: {
          loop: 7.65,
          caption:
            '示意动画（示例数据）：依据为施工合同及补充协议.docx 专用合同条款 11.1"主要材料价格涨跌幅度超过基准价格 5% 时，超过部分据实调整"。您确认写入后，知识库/公司经验/ 新增 结算审核-材料调差风险幅度口径.md，记下来源、日期 2026-10-19、获取方式工作回写、适用范围结算审核本公司、核验状态已核。校验 8 个目录、17 个条目、0 处违规。',
        },
      },
      {
        id: 'cloud',
        skill: 'zt-volc',
        name: '火山引擎运维',
        badge: '管理员',
        icon: 'cloud',
        kicker: '知识与协作 · zt-volc',
        title: '先演练，经您确认，再执行。',
        description:
          '供公司 IT 管理员使用：查看云服务器状态与启停，查看和修改安全组白名单（包括把本机公网 IP 同步进去），只读查看存储桶，用主机别名登录服务器执行命令。停机、重启、改白名单和非只读命令先演练，您在对话里确认后才执行。',
        input: '配置包中的运维项（主机别名与密钥）；本机已配置的火山引擎命令行 ve',
        output: '操作结果，以及是否真的有改动（changed）',
        say: ['把我现在的 IP 加进 zt-prod 的 SSH 白名单。', '登录 zt-prod，看一下磁盘还剩多少。'],
        outputs: [{ path: '知识库/公司经验/运维记录-2026-10-20.md', note: '仅在您要求留痕时' }],
        caution: '不提供删除存储桶或对象、创建或删除实例；密钥与私钥不进入对话。',
        cautionLevel: 'warn',
        docs: docs('cloud'),
        terms: ['配置包'],
        home: true,
        art: {
          loop: 7.75,
          caption:
            '示意动画（示例数据）：管理员要把当前 IP 加进 zt-prod 的 SSH 白名单。先验证身份，再预演：放行新 IP 的 22 端口、撤销 alice 标记下的旧 IP，预演不调用写接口。确认卡写明对象、动作、影响和命令；您选"执行"后带 --yes 重跑，先放行新 IP，再撤销旧 IP。',
        },
      },
    ],
  },
] as const satisfies readonly FeatureGroup[];

export const glossary: Record<GlossaryKey, string> = {
  公司存储桶:
    '公司的火山引擎对象存储（TOS）。项目资料、成果和知识库都放在这里，由贵司持有，开启版本控制。',
  项目说明:
    '每个项目根目录下的 项目说明.md：编号、咨询类型、阶段、关键文件指引和已出成果。开项目先读它。',
  案例索引:
    '公司存储桶根目录下的 案例索引.md，每个项目一行：编号、工程名、业态、规模、咨询类型、关键指标、成果链接、状态。',
  待确认清单: '每个工作目录里的 待确认清单.md，列出需要您确认的事项及其出处；归档前逐条处理。',
  配置包:
    '服务方按贵司环境整理交付的压缩文件，内含存储地址、区域、桶名、目录前缀、访问密钥和公司名；需要运维时可含 SSH 主机别名与密钥。不随安装包分发。',
};

/** 默认选中：核对与测算 / 送审审定核对；其余组为各自第一项。cloud 永不作默认项。 */
export const DEFAULT_GROUP = 'calculate' as const;
export const DEFAULT_SELECTION = {
  project: 'project',
  calculate: 'check',
  output: 'report',
  knowledge: 'knowledge',
} as const;

/** 全部能力（含 `home: false`），按组与组内顺序。 */
export const allFeatures: readonly Feature[] = featureGroups.flatMap(
  (g) => g.features as readonly Feature[],
);

/**
 * 首页显示的分组：每组只保留 `home: true` 的条目（04 章 D2）。
 * @param groups - 分组数据，默认 `featureGroups`。
 * @returns 过滤后的分组（空组也保留，计数为 0）。
 */
export function homeGroups(groups: readonly FeatureGroup[] = featureGroups): FeatureGroup[] {
  return groups.map((g) => ({ ...g, features: g.features.filter((f) => f.home) }));
}

/**
 * 尺寸线标注（04 章 §3.1）：`总数 = 各组条数之和`，按组顺序。
 * @param groups - 首页分组（已按 home 过滤）。
 * @returns 如 `12 = 3 + 4 + 3 + 2`。
 */
export function dimLabel(groups: readonly FeatureGroup[]): string {
  const counts = groups.map((g) => g.features.length);
  return `${counts.reduce((a, b) => a + b, 0)} = ${counts.join(' + ')}`;
}

/**
 * 能力所属分组。
 * @param id - 能力 id。
 * @param groups - 分组数据。
 * @returns 分组；找不到时为 undefined。
 */
export function groupOf(
  id: string,
  groups: readonly FeatureGroup[] = featureGroups,
): FeatureGroup | undefined {
  return groups.find((g) => g.features.some((f) => f.id === id));
}

/** 深链接 `#feature-<id>`（04 章 §6.6）。 */
export const FEATURE_HASH_RE =
  /^#feature-(project|qa|cad|check|metrics|control|estimate|report|bills|archive|knowledge|cloud)$/;

/**
 * 小动画里的示例数字（04 章 §5.5）。其它章已定义的值（00 章 §8.2、02 章）在这里汇总一份，
 * 每个数字一个出处；单测验算各乘积、差额与比率，并检查 SVG 文本中的数字都能在这里找到。
 */
export const ART_FACTS = {
  /** 00 章 §8.2 */
  check: {
    sent: 30_530_406.8,
    approved: 29_623_713.84,
    reduce: 906_692.96,
    rate: 2.97,
    rows: { total: 1284, same: 1031, adjusted: 214, sentOnly: 23, approvedOnly: 9, pending: 7 },
    reduceSum: 939_305.7,
    increaseSum: 32_612.74,
    /** 02 章 §3.4 */
    rebar: {
      code: '010515001002',
      sentQty: 1186.415,
      approvedQty: 1127.226,
      price: 5128.6,
      reduce: 303_556.71,
    },
    scaffold: { code: '011701001001', row: 46, twinRow: 28, amount: 125_120.0 },
    slab: { code: '010505001001', reduce: 56_688.78 },
    /** 本章新增，取自 features-check.md */
    window: {
      code: '010807001001',
      sentQty: 2316.48,
      sentPrice: 685.2,
      approvedQty: 2330.7,
      approvedPrice: 692.35,
      increase: 26_408.05,
    },
    apron: { code: '010507001001' },
    sheets: 3,
  },
  project: { required: 7, ready: 3, pending: 1, missing: 3, rate: 42.86, upper: 57.14 },
  qa: { paragraph: 42, threshold: 5 },
  cad: {
    rooms: [
      { name: '会议室201', text: 69.7, geom: 73.08, diff: 4.85 },
      { name: '卫生间', text: 34.0, geom: 34.06, diff: 0.18 },
      { name: '培训室', text: 69.7, geom: 69.7, diff: 0.0 },
      { name: '资料室', text: 69.7, geom: 69.7, diff: 0.0 },
    ],
    axisRect: { w: 8.4, h: 8.7 },
    innerRect: { w: 8.2, h: 8.5 },
    anchors: 10,
    matched: 9,
    dims: 9,
    scale: 100,
    sheet: { w: 84_100, h: 59_400, drawW: 216, drawH: 153 },
    gridRows: 6,
    zoomCell: 'E4',
  },
  metrics: {
    area: 18_600.0,
    unit: 1592.67,
    shares: { concrete: 61.49, measures: 13.47, windows: 9.95 },
    peers: { a: 1688.4, b: 1571.2 },
    mean: 1629.8,
    deviation: -2.28,
    axis: { min: 1560, max: 1700, ticks: [1600, 1640, 1680] },
    sentArea: 1641.42,
  },
  control: {
    total: 290,
    large: 286,
    duplicate: 2,
    provisional: 1,
    consistency: 1,
    focus: 4,
    confidence: 0.7,
    confirmed: 1,
    remaining: 289,
    skippedRules: 4,
  },
  estimate: {
    site: 6850,
    basement: 3400,
    tower: 15_200,
    footprint: 2740,
    ground: 24,
    underground: 86,
    parking: 110,
    total: 18_600,
    slots: 11,
    found: 6,
    rest: 5,
    reserve: 5,
    floors: 15,
    density: 40,
  },
  report: {
    chapters: 9,
    templates: 24,
    sections: 172,
    values: [30_530_406.8, 29_623_713.84, 939_305.7, 32_612.74, 906_692.96],
  },
  bills: {
    segments: 148,
    parts: [61, 52, 21, 7, 3, 4],
    codes: 490,
    zCodes: 158,
    item: '011102003001',
    base: '011102003',
    serial: '001',
    wrong: '011101002',
  },
  archive: { results: 3, workDirs: 5, openLists: 2 },
  knowledge: { dirs: 8, entries: 17, violations: 0, clause: '11.1', date: '2026-10-19' },
  cloud: { port: 22, cidr: 32 },
} as const;

/**
 * SVG 文本中允许出现、但不是度量值的标识（编码、编号、日期、规格写法、坐标格名）。
 * 单测把动画文本中每个数字串与 ART_FACTS 的格式化值及这里的标识逐一比对。
 */
export const ART_TOKENS = [
  '2026-007',
  '2026-10-19',
  '2026-10-20',
  '0001',
  'A-02',
  '1:100',
  'E4',
  'S1',
  'J46',
  'C46',
  'C5',
  'C45',
  'C10',
  'F1',
  'F2',
  'F3',
  'F4',
  'F5',
  'D4',
  'D7',
  'D10',
  'D15',
  'D19',
  'D20',
  '1#',
  '201',
  '010',
  '020',
  '030',
  '040',
  '050',
  '060',
  '070',
  '080',
  '090',
  '800×800',
  '1:3',
  'C20',
  '40厚',
  '10厚',
  '20厚',
  'p3',
  '1',
  '2',
  '4',
  '7',
  'sg-aaaaaaaa01',
  'zt-prod',
  'zj2025',
  'sha256',
  'v1',
] as const;
