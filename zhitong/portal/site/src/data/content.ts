import type { FeatureGroup, Role } from '../types/portal';

export const featureGroups: FeatureGroup[] = [
  {
    id: 'project',
    label: '项目资料',
    icon: 'folder',
    features: [
      {
        id: 'project',
        name: '开项目与资料盘点',
        icon: 'folder',
        kicker: '项目资料 / 资料盘点',
        title: '先看清项目，再开始工作。',
        description: '打开或新建项目，按咨询类型检查资料是否齐全，明确列出缺失项。',
        input: '项目目录、咨询类型与现有文件',
        output: '项目说明与缺失资料清单',
        caution: '先盘点资料，不替资料自动贴标签。',
      },
      {
        id: 'qa',
        name: '项目与知识库问答',
        icon: 'chat',
        kicker: '项目资料 / 问答',
        title: '带着问题，找到资料里的回答。',
        description: '围绕当前项目或企业知识库提问，按需读取文件，引用实际查阅的位置。',
        input: '项目或企业知识库中的文件',
        output: '带资料引用的回答',
        caution: '没有出处的数字会被标出，文件中的指令不执行。',
      },
      {
        id: 'cad',
        name: 'CAD 看图',
        icon: 'cad',
        kicker: '项目资料 / 图纸阅读',
        title: '让图纸中的信息，有处可查。',
        description: '转换DWG、识别图框，按需查看图纸，提取指定词表内的文字与房间面积。',
        input: 'DWG图纸',
        output: '图框图片、文字与面积阅读结果',
        caution: '看图结果需人工确认，不替代完整算量。',
        scene: 'cad',
      },
    ],
  },
  {
    id: 'calculate',
    label: '核对与测算',
    icon: 'calc',
    features: [
      {
        id: 'check',
        name: '送审审定核对',
        icon: 'sheet',
        kicker: '核对与测算 / 计价表',
        title: '核增核减，逐行对得上。',
        description: '核对送审与审定计价表，汇总各章节核增、核减金额及核减率，生成Excel供您复核。',
        input: '送审与审定计价表',
        output: '逐行核对明细与章节汇总表',
        caution: '金额与数量需人工确认。',
        scene: 'check',
      },
      {
        id: 'metrics',
        name: '造价指标分析',
        icon: 'calc',
        kicker: '核对与测算 / 造价指标',
        title: '看懂指标，也看懂偏差。',
        description: '计算单方造价与各章节费用占比，查找公司已归档的同类项目，辅助判断指标偏差。',
        input: '规模、计算结果与公司案例索引',
        output: '造价指标与同类项目偏差说明',
        caution: '指标由脚本计算，结果需人工确认。',
      },
      {
        id: 'control',
        name: '全过程投控检查',
        icon: 'shield',
        kicker: '核对与测算 / 投控复核',
        title: '异常逐条看，决定逐条留。',
        description:
          '检查重复计取、暂估价、行内自洽和大额项。有合同基准时，再检查单价、工程量与合同外新增项。',
        input: '送审清单，可选合同基准',
        output: '异常明细、依据与复核记录',
        caution: '检测提供线索，最终判断由审核人员作出。',
        scene: 'review',
      },
      {
        id: 'estimate',
        name: '概算编制辅助',
        icon: 'calc',
        kicker: '核对与测算 / 概算',
        title: '计算有公式，调整可复算。',
        description:
          '提取规模等计算条件，缺少的输入由您补充，按公式计算，生成可修改、可复算的Excel。',
        input: '设计说明、项目资料与补充输入',
        output: '带真实公式的概算Excel',
        caution: '模型不参与算钱，规模量附原文引文。',
      },
    ],
  },
  {
    id: 'output',
    label: '成果与归档',
    icon: 'file',
    features: [
      {
        id: 'report',
        name: '报告撰写',
        icon: 'file',
        kicker: '成果与归档 / 报告',
        title: '按章组织，把依据写进报告。',
        description: '按内置模板逐章选材和撰写，标注资料来源，金额引用脚本结果，支持导出Word。',
        input: '项目资料、计算结果与报告模板',
        output: '带来源的Word报告初稿',
        caution: '数字须有资料依据，未核实陈述标注“待核”。',
      },
      {
        id: 'bills',
        name: 'GB50854 清单框架',
        icon: 'sheet',
        kicker: '成果与归档 / 清单框架',
        title: '从设计说明，搭起清单框架。',
        description: '对照受控清单码表匹配设计做法，生成清单框架，并列出待核与未匹配项。',
        input: '设计说明与受控清单码表',
        output: '清单、待核与未匹配、覆盖核算、说明',
        caution: '无图纸依据时，工程量留空。',
      },
      {
        id: 'archive',
        name: '归档与案例查询',
        icon: 'archive',
        kicker: '成果与归档 / 项目积累',
        title: '这次的成果，下次找得到。',
        description: '核对“工作”“成果”目录，归档回公司云存储，更新项目说明与案例索引。',
        input: '项目过程文件与交付成果',
        output: '完整项目归档与历史案例入口',
        caution: '归档回读校验，方便下一位同事接手。',
      },
    ],
  },
  {
    id: 'knowledge',
    label: '知识与协作',
    icon: 'team',
    features: [
      {
        id: 'knowledge',
        name: '企业知识库建设',
        icon: 'file',
        kicker: '知识与协作 / 企业积累',
        title: '把公司的经验，留给每个项目。',
        description: '整理定额、规范、清单码表、费率和公司经验，记录来源与日期，供所有项目查阅。',
        input: '初始资料整理与工作经验积累',
        output: '带来源和日期的共享知识',
        caution: '按目录组织、按需读取，不要求建立向量索引。',
      },
      {
        id: 'cloud',
        name: '火山引擎运维',
        icon: 'cloud',
        kicker: '知识与协作 / 云资源',
        title: '按交付配置，管理公司云资源。',
        description: '管理云存储、云服务器与访问白名单，支持服务器启停和远程命令执行。',
        input: '已授权的公司交付配置',
        output: '按需执行的云资源操作',
        caution: '此为桌面产品能力，门户原型不提供真实运维操作。',
      },
    ],
  },
];

export const roles: Role[] = [
  {
    id: 'engineer',
    name: '造价工程师',
    icon: 'user',
    title: '把精力，放回专业判断。',
    description: '查资料、核对计价表、算指标、写报告，\n过程文件与成果统一保存。',
    tasks: [
      { label: '资料盘点', action: { type: 'feature', id: 'project' } },
      { label: '送审审定核对', action: { type: 'feature', id: 'check' } },
      { label: '报告撰写', action: { type: 'feature', id: 'report' } },
    ],
  },
  {
    id: 'reviewer',
    name: '审核负责人',
    icon: 'shield',
    title: '结果看得清，依据找得到。',
    description: '回查数据来源，逐条复核异常，\n记录审核决定，确认后形成成果。',
    tasks: [
      { label: '投控检查', action: { type: 'feature', id: 'control' } },
      { label: '查看来源', action: { type: 'source' } },
      { label: '审核留痕', action: { type: 'scene', id: 'review' } },
    ],
  },
  {
    id: 'manager',
    name: '公司管理者',
    icon: 'team',
    title: '让每个项目，都留下积累。',
    description: '统一管理项目资料与成果，积累企业知识和历史案例，\n便于团队接手与复用。',
    tasks: [
      { label: '归档与案例', action: { type: 'feature', id: 'archive' } },
      { label: '企业知识库', action: { type: 'feature', id: 'knowledge' } },
      { label: '数据持有说明', action: { type: 'section', id: 'trust' } },
    ],
  },
];

export const faqs = [
  {
    id: 'model',
    question: '资料会发送给模型吗？',
    answer: '读取的文件内容会作为对话上下文发送至所配置的模型服务，具体部署方式在交付时说明。',
  },
  {
    id: 'collaboration',
    question: '支持多人同时使用吗？',
    answer:
      '支持多人共用公司的云存储。系统不锁定项目文件，同时修改可能造成覆盖，可通过已开启的版本控制回退。',
  },
  {
    id: 'scans',
    question: '扫描件能读吗？',
    answer: '支持。优先读取已有识别文本，没有时由模型看图，识别结果需人工确认。',
  },
  {
    id: 'import',
    question: '原有项目资料如何导入？',
    answer: '由服务方在交付前整理目录、清理重复文件、核对后上传，并提供整理报告。',
  },
];

export const workflowSteps = [
  {
    title: '安装并导入配置',
    icon: 'laptop',
    description: '安装客户端，把服务方提供的配置包拖入对话，完成连接配置。',
    caption: '电脑准备就绪',
  },
  {
    title: '打开项目',
    icon: 'folder',
    description: '选择或新建项目，读取项目说明，检查资料是否齐全。',
    caption: '明确现有与缺失资料',
  },
  {
    title: '对话处理任务',
    icon: 'chat',
    description: '说明要做的工作，查看结果，确认需要复核的事项。',
    caption: '用专业判断确认结果',
  },
  {
    title: '归档成果',
    icon: 'archive',
    description: '过程存入“工作”，交付存入“成果”，归档回公司云存储。',
    caption: '更新项目说明与案例索引',
  },
];

export const trustStatements = [
  {
    title: '公司持有资料',
    icon: 'folder',
    description: '项目资料、成果与知识库存放在公司自己的火山引擎TOS中，访问凭据保存在本机。',
  },
  {
    title: '计算有依据',
    icon: 'calc',
    description: '模型负责阅读、分析和写作，金额与数量由脚本计算，报告数字须有资料依据。',
  },
  {
    title: '人工确认后使用',
    icon: 'shield',
    description: '金额、数量及看图结果需人工确认，异常逐条复核，最终成果由人签发。',
  },
];
