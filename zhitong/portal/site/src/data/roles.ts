/**
 * 适用岗位与任务入口（03 章 §1.2、§1.4）。文案逐字取自 spec 三张表；
 * 依据各能力的 SKILL.md（zt-project、zt-reconcile、zt-estimate、zt-report、zt-tk、zt-indicator、zt-quantity、
 * zt-cad、zt-archive、zt-knowledge、zt-ask、zt-volc），限定一列对应 STATUS.md「数据签核与口径」。
 */
import type { SceneId } from '../types/portal';

export type CapabilityId =
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
export type RoleId = 'engineer' | 'reviewer' | 'manager';
export type MicroKind =
  | 'inventory'
  | 'reconcile'
  | 'extract'
  | 'draft'
  | 'review'
  | 'benchmark'
  | 'codes'
  | 'plan'
  | 'archive'
  | 'entry'
  | 'answer'
  | 'ops';

export interface RoleTask {
  id: `${RoleId}-${CapabilityId}`;
  capability: CapabilityId;
  no: '01' | '02' | '03' | '04';
  /** 入口文字，≤ 8 字。 */
  label: string;
  /** 说明卡眉题（06 章分组 / 能力名）。 */
  eyebrow: string;
  /** 一句话。 */
  summary: string;
  /** 需要什么。 */
  needs: string;
  /** 得到什么。 */
  yields: string;
  /** 限定；无限定时为 null。 */
  note: string | null;
  micro: MicroKind;
  primary: { kind: 'scene'; scene: SceneId } | { kind: 'feature' };
  docs: `/docs/features/${CapabilityId}/`;
}

export interface RoleEntry {
  id: RoleId;
  name: '造价工程师' | '审核负责人' | '公司管理者';
  icon: 'user' | 'shield' | 'team';
  title: string;
  description: string;
  tasks: readonly [RoleTask, RoleTask, RoleTask, RoleTask];
}

/** 小动画与说明卡里用到的示例数字（00 章 §8.2 原值，单测引用同一常量）。 */
export const ROLE_FIGURES = {
  /** 核减额（元）。 */
  reduction: 906692.96,
  /** 核减率。 */
  reductionRate: 0.0297,
  /** 送审合计（元）。 */
  submittedTotal: 30530406.8,
  /** 审定合计（元）。 */
  approvedTotal: 29623713.84,
  /** 建筑面积（m²）。 */
  floorArea: 18600,
  /** 审定单方（土建，元/m²）。 */
  approvedUnit: 1592.67,
  /** 地上建筑面积（m²）。 */
  aboveGround: 15200,
} as const;

type TaskInput = Omit<RoleTask, 'id' | 'docs' | 'primary'> & { scene?: SceneId };

function task(role: RoleId, input: TaskInput): RoleTask {
  const { scene, ...rest } = input;
  return {
    ...rest,
    id: `${role}-${input.capability}`,
    primary: scene ? { kind: 'scene', scene } : { kind: 'feature' },
    docs: `/docs/features/${input.capability}/`,
  };
}

const engineer: RoleEntry['tasks'] = [
  task('engineer', {
    capability: 'project',
    no: '01',
    label: '资料盘点',
    eyebrow: '项目与资料 / 开项目与资料盘点',
    summary: '按咨询类型和阶段对照资料清单，只看文件名和目录，直接说出缺什么，不给文件贴标签。',
    needs: '公司桶里的项目目录；项目说明里写明的咨询类型与阶段（没写时先问您，不猜）。',
    yields:
      '必备资料的已备、待确认、缺失结论，写进项目说明的“资料盘点”小节；“待确认”要打开文件核实后才算已备。',
    note: '资料清单与分类规则目前为待签核版本。',
    micro: 'inventory',
  }),
  task('engineer', {
    capability: 'check',
    no: '02',
    label: '送审审定核对',
    eyebrow: '核对与测算 / 送审审定核对',
    summary:
      '定位送审与审定两张计价表，预检后逐行核对：编码优先，名称、特征、单位兜底，按章节汇总核增与核减。',
    needs: '送审与审定计价表（.xlsx；.xls 请先另存为 .xlsx，广联达工程文件请先导出 Excel）。',
    yields:
      '“工作/<日期>-核对/”下的核对结果.xlsx、result.json 与待确认清单.md；核减额与核减率由脚本计算，标注需人工确认。',
    note: null,
    micro: 'reconcile',
    scene: 'check',
  }),
  task('engineer', {
    capability: 'estimate',
    no: '03',
    label: '概算编制',
    eyebrow: '核对与测算 / 概算编制辅助',
    summary:
      '从设计说明中抽取规模量，每个值附原文引文并回查原文；您确认后才进入计算，金额由公式算出，模型不参与算钱。',
    needs: '设计说明、可研报告或经济技术指标表；缺的输入由您在对话中补充。',
    yields: '带真实 Excel 公式的概算.xlsx，可直接改单元格复算；所有金额为待复核初稿。',
    note: '随附费率规则尚未经造价员逐值核对；费率建议需您确认后采用。',
    micro: 'extract',
  }),
  task('engineer', {
    capability: 'report',
    no: '04',
    label: '报告撰写',
    eyebrow: '成果与归档 / 报告撰写',
    summary: '先选模板，再按章选材、逐章撰写，每句标注资料来源；金额只引用脚本取出的事实编号。',
    needs: '项目资料与计算结果；内置 24 套模板、172 章的逐章写作要求。',
    yields:
      '“成果/”下的 Word 初稿，页眉写明“AI 初稿，金额未经人工核对，不得直接出具”；文末附待补与待核清单。',
    note: '每个数字必须在送入的资料中逐字找到；未核实的程序性陈述标注“待核”。',
    micro: 'draft',
  }),
];

const reviewer: RoleEntry['tasks'] = [
  task('reviewer', {
    capability: 'control',
    no: '01',
    label: '投控异常复核',
    eyebrow: '核对与测算 / 投控异常检测与复核', // 00 §14 第 10 条：能力名以 04 章 featureGroups 为准（03 章表格仍是旧名）
    summary:
      '检测重复计取、暂估价、量价不自洽和大额项；带合同清单时再查单价超合同、工程量超合同、漏报和合同外新增。每条都是疑似，由您逐条判定。',
    needs: '送审计价表；合同或中标清单可选，没有时只跑前四类规则。',
    yields: '投控异常.xlsx 与复核.jsonl：每次判定“确认”或“误报”都追加一条记录并写明理由，可追溯。',
    note: '检测阈值为草案，未经客户核定。',
    micro: 'review',
    scene: 'review',
  }),
  task('reviewer', {
    capability: 'metrics',
    no: '02',
    label: '指标偏差复核',
    eyebrow: '核对与测算 / 造价指标',
    summary: '计算单方造价与各章占比，到公司案例索引里找同类项目对标，给出偏差，供您判断是否合理。',
    needs: '计价表；建筑面积及其出处（找不到会问您，不估算）；公司案例索引。',
    yields: '指标结果.xlsx：单方、占比、造价驱动项、同类均值与偏差，全部标注需人工确认。',
    note: '对标项目只来自公司自己归档的案例。',
    micro: 'benchmark',
  }),
  task('reviewer', {
    capability: 'bills',
    no: '03',
    label: '清单待核项',
    eyebrow: '成果与归档 / GB50854 清单框架',
    summary:
      '按设计说明的做法逐层对照受控码表查码；码表里没有的列为未匹配，与原文不一致的降为“待核”，不自动改码。',
    needs:
      '建筑设计说明或工程做法表（xlsx、docx、文字层 PDF 或 txt；.xls、.doc 请先另存为 .xlsx、.docx）。',
    yields: '清单框架.xlsx 四张表：清单、待核与未匹配、覆盖核算、说明；工程量列留空，由人计算。',
    note: '仅适用房屋建筑与装饰工程；码表为草稿口径，未经造价员签字。',
    micro: 'codes',
  }),
  task('reviewer', {
    capability: 'cad',
    no: '04',
    label: '看图结果核对',
    eyebrow: '项目与资料 / CAD 看图',
    summary:
      '打开 DWG 图纸，列出图框与标题栏，按需抽取文字、门窗编号和房间面积；要看位置时先出总览图，再局部放大核对。',
    needs: 'DWG 或 DXF 图纸；计算面积前需确认图纸单位。',
    yields: '写进“工作/”的表格或清单，注明图纸、图框与文字编号；计数与面积由工具计算，需人工确认。',
    note: '不读图纸空间（布局）；天正原生实体需先导出为 T3 格式。',
    micro: 'plan',
    scene: 'cad',
  }),
];

const manager: RoleEntry['tasks'] = [
  task('manager', {
    capability: 'archive',
    no: '01',
    label: '归档与案例索引',
    eyebrow: '成果与归档 / 归档与案例索引',
    summary:
      '归档前核对“成果”与“工作”目录是否齐全，推送回桶并回读校验，更新项目说明，在案例索引中追加本项目一行。',
    needs: '已完成的项目目录；您对成果清单和关键指标的确认。',
    yields:
      '案例索引里的一行：编号、工程名、业态、规模、咨询类型、关键指标、成果链接；跨项目查询读这份索引即可。',
    note: '关键指标只写成果里已算好的数，不现场计算。',
    micro: 'archive',
  }),
  task('manager', {
    capability: 'knowledge',
    no: '02',
    label: '企业知识库',
    eyebrow: '知识与协作 / 企业知识库',
    summary:
      '初版由定额、规范条文、清单码表和费率整理而成；工作中发现的口径与经验，经您确认后写入“公司经验”目录。',
    needs: '要沉淀的内容及其来源：项目文件位置或网页地址。',
    yields: '“知识库/公司经验/”下的一个条目，带来源、日期、适用范围与核验状态，所有项目可见。',
    note: '只拿到网页摘要的条目标注“待核”；未签核的数据不标已核。',
    micro: 'entry',
  }),
  task('manager', {
    capability: 'qa',
    no: '03',
    label: '接手项目问答',
    eyebrow: '项目与资料 / 项目与知识库问答',
    summary: '先读项目说明，再拉取单份文件阅读后回答；引用只指向实际读过的位置，没有出处的数字会被标出。',
    needs: '桶里的项目目录或知识库目录；不需要建向量索引。',
    yields:
      '带出处的回答，出处精确到文件与页、表行或段落，例如〔资料/1 合同及协议/施工合同及补充协议.docx 段12〕。',
    note: '文件里夹带的指令只当资料内容，不会被执行。',
    micro: 'answer',
  }),
  task('manager', {
    capability: 'cloud',
    no: '04',
    label: '火山引擎运维',
    eyebrow: '知识与协作 / 火山引擎运维',
    summary: '用 ve 命令行和 SSH 查看 ECS 状态、启停实例、维护安全组白名单、登录服务器执行命令。',
    needs: '配置包提供的主机别名与私钥；本人终端里设置好的 ve profile（密钥不经过对话）。',
    yields: '会中断服务或改变访问范围的操作，先给出预演结果，经您在对话里选择“执行”后才执行。',
    note: '不提供删除桶、创建或删除实例等操作，这些请在火山引擎控制台完成。',
    micro: 'ops',
  }),
];

/** 三个岗位（03 章 §1.2）。 */
export const ROLES: readonly RoleEntry[] = [
  {
    id: 'engineer',
    name: '造价工程师',
    icon: 'user',
    title: '把精力，放回专业判断。',
    description:
      '一个项目从收资料到出成果，在一次对话里说明项目和任务即可：盘点缺什么资料，核对送审与审定的核增核减，做概算，逐章写报告。中间产物放在项目的“工作”目录，成果放在“成果”目录。',
    tasks: engineer,
  },
  {
    id: 'reviewer',
    name: '审核负责人',
    icon: 'shield',
    title: '结果看得清，依据找得到。',
    description:
      '需要复核的内容集中在对话里逐条确认：投控异常逐条给出依据，由您判定“确认”或“误报”，决定追加记录、可追溯。金额、数量和看图结果一律标注“需人工确认”。您审的是有出处的结果。',
    tasks: reviewer,
  },
  {
    id: 'manager',
    name: '公司管理者',
    icon: 'team',
    title: '让每个项目，都留下积累。',
    description:
      '资料、成果和知识库都在公司自己的火山引擎对象存储（TOS）桶里，开启版本控制，数据归公司所有。接手项目的同事先读项目说明，就能找到合同、计价表和图纸；公司积累的口径与经验写入知识库，所有项目共用。',
    tasks: manager,
  },
];

/** 全部 12 个任务（按岗位、序号）。 */
export const ROLE_TASKS: readonly RoleTask[] = ROLES.flatMap((r) => [...r.tasks]);

/** 岗位图图号（§1.4 RoleArt 标题栏）。 */
export const ROLE_DRAWING_NO: Record<RoleId, string> = {
  engineer: 'R-01',
  reviewer: 'R-02',
  manager: 'R-03',
};

/** 说明卡两行的标签。 */
export const TASK_ROW_LABELS = { needs: '需要什么', yields: '得到什么' } as const;

/** 说明卡首要按钮文字。 */
export function primaryLabel(t: RoleTask): string {
  return t.primary.kind === 'scene' ? '看示例' : '看能力介绍';
}
