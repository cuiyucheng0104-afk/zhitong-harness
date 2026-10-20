<script setup lang="ts">
import AppIcon from '../AppIcon.vue';
import brandMark from '../../../assets/brand-mark.svg';
import { rooms } from '../../data/demo';
import type { RoomId } from '../../types/portal';

defineProps<{ room: RoomId; roomLabel: string }>();
defineEmits<{ select: [id: RoomId] }>();
</script>

<template>
  <section id="scene-cad" class="scene" role="tabpanel" aria-labelledby="tab-cad">
    <div class="prompt">
      <span class="avatar-user">你</span><span>查看这张图的房间标注</span
      ><AppIcon name="arrow" class="prompt-arrow" />
    </div>
    <div class="assistant-label">
      <img :src="brandMark" alt="" width="22" height="22" /><strong>智通数工AI</strong
      ><span class="read-status"><AppIcon name="check" />图框已定位</span>
    </div>
    <div class="cad-layout">
      <div class="drawing-wrap">
        <span class="drawing-id mono">A-02 / 平面示意</span>
        <svg
          class="floorplan"
          viewBox="0 0 300 210"
          role="img"
          aria-label="示例平面图，西侧会议室，东北侧办公室，东南侧资料室"
        >
          <defs>
            <pattern id="cad-grid" width="10" height="10" patternUnits="userSpaceOnUse">
              <path d="M10 0H0v10" fill="none" stroke="#DCE8F4" stroke-width=".4" />
            </pattern>
          </defs>
          <rect width="300" height="210" fill="url(#cad-grid)" />
          <path d="M28 20h240v164H28z" fill="#fff" stroke="#446185" stroke-width="4" />
          <rect
            class="room-shape"
            :class="{ selected: room === 'meeting' }"
            data-room-shape="meeting"
            x="31"
            y="23"
            width="122"
            height="158"
          />
          <rect
            class="room-shape"
            :class="{ selected: room === 'office' }"
            data-room-shape="office"
            x="157"
            y="23"
            width="108"
            height="82"
          />
          <rect
            class="room-shape"
            :class="{ selected: room === 'archive' }"
            data-room-shape="archive"
            x="157"
            y="109"
            width="108"
            height="72"
          />
          <path d="M155 20v72m0 32v60m0-77h113" stroke="#446185" stroke-width="3" fill="none" />
          <path
            d="M155 92h-30a30 30 0 0 0 30 30m45-15v25a25 25 0 0 0 25-25"
            stroke="#8CA6C6"
            fill="none"
          />
          <path
            d="M53 20h58M188 20h42M53 184h58M268 45v33M268 135v27"
            stroke="#4D9DFF"
            stroke-width="5"
          />
          <g fill="#526C8B" font-family="sans-serif" font-size="12" text-anchor="middle">
            <text x="90" y="87">会议室</text>
            <text x="90" y="106" class="drawing-measure">42.00 m²</text>
            <text x="211" y="56">办公室</text>
            <text x="211" y="75" class="drawing-measure">28.00 m²</text>
            <text x="211" y="140">资料室</text>
            <text x="211" y="158" class="drawing-measure">18.00 m²</text>
          </g>
          <path d="M28 198h240M28 192v12m240-12v12" stroke="#9FB1C7" />
          <text
            x="148"
            y="207"
            fill="#7890AB"
            text-anchor="middle"
            font-size="8"
            font-family="monospace"
          >
            图纸示意 · 非真实项目
          </text>
        </svg>
      </div>
      <div class="room-list" role="group" aria-label="选择房间定位图纸">
        <button
          v-for="item in rooms"
          :key="item.id"
          :data-room="item.id"
          :aria-pressed="room === item.id"
          @click="$emit('select', item.id)"
        >
          <span>{{ item.name }}</span
          ><strong>{{ item.area }} <small>m²</small></strong>
        </button>
      </div>
    </div>
    <div class="result-note">
      <span class="badge badge-warning"><AppIcon name="alert" />需人工确认</span
      ><span id="room-status" role="status">已定位：{{ roomLabel }}</span>
    </div>
    <p class="scene-disclaimer">点击房间定位 · 此处为图纸阅读示意</p>
  </section>
</template>
