<script setup lang="ts">
import type { Feature } from '../types/portal';
import AppIcon from './AppIcon.vue';

defineProps<{ feature: Feature }>();
</script>

<template>
  <div v-if="feature.id === 'project'" class="feature-art artifact-list" aria-label="资料盘点示意">
    <div><AppIcon name="check" /><span>合同文件</span><small>已找到</small></div>
    <div><AppIcon name="check" /><span>送审计价表</span><small>已找到</small></div>
    <div class="missing-file">
      <AppIcon name="alert" /><span>设计说明</span><small>待补充</small>
    </div>
  </div>
  <div v-else-if="feature.id === 'qa'" class="feature-art quoted-art">
    <AppIcon name="chat" />
    <p>这个项目的审核范围是什么？</p>
    <div>
      <span>资料引用</span><strong>咨询合同.pdf</strong><small>第 3 页 · 服务范围（示例）</small>
    </div>
  </div>
  <div v-else-if="feature.id === 'cad'" class="feature-art drawing-art">
    <AppIcon name="cad" />
    <div>
      <span class="mono">A-02 / 平面图</span><strong>图框定位 → 文字提取 → 人工确认</strong>
    </div>
  </div>
  <div v-else-if="feature.id === 'check'" class="feature-art compare-art">
    <div class="compare-file">
      <span class="file-type">XLS</span>
      <div><strong>送审计价表</strong><small>原始资料</small></div>
    </div>
    <AppIcon name="arrow" class="compare-arrow" />
    <div class="compare-file">
      <span class="file-type">XLS</span>
      <div><strong>核对结果</strong><small>逐行明细 · 章节汇总</small></div>
      <AppIcon name="check" class="artifact-check" />
    </div>
  </div>
  <div v-else-if="feature.id === 'metrics'" class="feature-art text-art">
    <AppIcon name="calc" />
    <div>
      <strong>单方造价 / 章节占比 / 同类对标</strong>
      <p>计算结果带依据，对标来自公司的历史案例。</p>
    </div>
  </div>
  <div v-else-if="feature.id === 'control'" class="feature-art text-art">
    <AppIcon name="shield" />
    <div>
      <strong>发现异常 → 回查依据 → 人工判定</strong>
      <p>确认或标记误报，决策追加记录。</p>
    </div>
  </div>
  <div v-else-if="feature.id === 'estimate'" class="feature-art formula-art">
    <span class="file-type">ƒx</span>
    <div>
      <strong>保留真实公式</strong>
      <p>修改输入单元格，即可复算。</p>
    </div>
    <span class="mono">=规模 × 指标</span>
  </div>
  <div v-else-if="feature.id === 'report'" class="feature-art report-art">
    <span class="file-type doc-type">DOC</span>
    <div>
      <strong>结算审核报告</strong><span class="report-line"></span
      ><span class="report-line short"></span><small>资料来源 · 计算依据 · 待核事项</small>
    </div>
  </div>
  <div v-else-if="feature.id === 'bills'" class="feature-art text-art">
    <AppIcon name="sheet" />
    <div>
      <strong>清单码来自受控码表</strong>
      <p>一致性不符时标“待核”，不自动改码。</p>
    </div>
  </div>
  <div v-else-if="feature.id === 'archive'" class="feature-art folder-art">
    <div><AppIcon name="folder" /><strong>工作</strong><small>过程与依据</small></div>
    <div><AppIcon name="folder" /><strong>成果</strong><small>交付与归档</small></div>
    <AppIcon name="arrow" />
    <div><AppIcon name="cloud" /><strong>公司 TOS</strong><small>项目说明与案例索引</small></div>
  </div>
  <div v-else-if="feature.id === 'knowledge'" class="feature-art knowledge-art">
    <span>定额</span><span>规范</span><span>清单码表</span
    ><span class="knowledge-emphasis">公司经验<AppIcon name="link" /></span>
  </div>
  <div v-else-if="feature.id === 'cloud'" class="feature-art text-art">
    <AppIcon name="cloud" />
    <div>
      <strong>TOS / ECS / SSH</strong>
      <p>主机别名、密钥与配置由服务方交付。</p>
    </div>
  </div>
</template>
