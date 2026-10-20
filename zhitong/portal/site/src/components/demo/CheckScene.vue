<script setup lang="ts">
import AppIcon from '../AppIcon.vue';
import brandMark from '../../../assets/brand-mark.svg';
import { comparisonRows, formatMoney } from '../../data/demo';

defineProps<{ totals: { submitted: number; approved: number; reduction: number; rate: string } }>();
defineEmits<{ source: [event: MouseEvent] }>();
</script>

<template>
  <section id="scene-check" class="scene" role="tabpanel" aria-labelledby="tab-check">
    <div class="prompt demo-part">
      <span class="avatar-user">你</span><span>核对送审和审定计价表</span
      ><AppIcon name="arrow" class="prompt-arrow" />
    </div>
    <div class="assistant-label demo-part">
      <img :src="brandMark" alt="" width="22" height="22" /><strong>智通数工AI</strong
      ><span class="read-status"><AppIcon name="check" />已读取 2 份文件</span>
    </div>
    <p class="response-intro demo-part">已完成逐行核对。以下为章节汇总：</p>
    <div class="result-table demo-part">
      <div class="table-unit">金额单位：元</div>
      <table>
        <caption class="sr-only">
          示例计价表章节核对汇总，金额单位为元
        </caption>
        <thead>
          <tr>
            <th scope="col">章节</th>
            <th scope="col">送审金额</th>
            <th scope="col">审定金额</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="row in comparisonRows" :key="row.name">
            <th scope="row">{{ row.name }}</th>
            <td>{{ formatMoney(row.submitted) }}</td>
            <td>{{ formatMoney(row.approved) }}</td>
          </tr>
          <tr class="table-total">
            <th scope="row">合计</th>
            <td>{{ formatMoney(totals.submitted) }}</td>
            <td>{{ formatMoney(totals.approved) }}</td>
          </tr>
        </tbody>
      </table>
      <div class="mobile-amounts">
        <span
          >送审合计<strong>{{ formatMoney(totals.submitted) }}</strong></span
        ><span
          >审定合计<strong>{{ formatMoney(totals.approved) }}</strong></span
        >
      </div>
    </div>
    <div class="result-summary demo-part">
      <div>
        <span class="result-label">核减额 <span>元</span></span
        ><button
          class="amount-button"
          :aria-label="`核减额${formatMoney(totals.reduction)}元，查看出处`"
          @click="$emit('source', $event)"
        >
          {{ formatMoney(totals.reduction).split('.')[0] }}<span>.00</span><AppIcon name="link" />
        </button>
      </div>
      <div class="rate-block">
        <span class="result-label">核减率</span><strong>{{ totals.rate }}<span>%</span></strong>
      </div>
      <button class="source-link" @click="$emit('source', $event)">
        查看出处<AppIcon name="arrow" />
      </button>
    </div>
    <div class="result-note demo-part">
      <span class="badge badge-warning"><AppIcon name="alert" />需人工确认</span
      ><span>点击金额，可回查原表</span>
    </div>
  </section>
</template>
