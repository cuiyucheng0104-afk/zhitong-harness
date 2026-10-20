<script setup lang="ts">
defineProps<{
  name: string;
}>();
</script>

<template>
  <svg
    class="icon"
    xmlns="http://www.w3.org/2000/svg"
    viewBox="0 0 24 24"
    aria-hidden="true"
    focusable="false"
  >
    <g v-if="name === 'arrow'"><path d="M5 12h14m-6-6 6 6-6 6" /></g>
    <g v-else-if="name === 'down'"><path d="M12 4v16m-6-6 6 6 6-6" /></g>
    <g v-else-if="name === 'file'">
      <path d="M14 3H5v18h14V8zM14 3v6h5M8 13h8M8 17h5" />
    </g>
    <g v-else-if="name === 'sheet'">
      <rect x="4" y="3" width="16" height="18" rx="2" />
      <path d="M4 9h16M10 9v12M4 15h16" />
    </g>
    <g v-else-if="name === 'folder'"><path d="M3 7V5h7l2 3h9v12H3z" /></g>
    <g v-else-if="name === 'check'"><path d="m5 12 4 4L19 6" /></g>
    <g v-else-if="name === 'close'"><path d="m6 6 12 12M18 6 6 18" /></g>
    <g v-else-if="name === 'link'">
      <path
        d="m10 13 4-4m-7 5-1 1a4 4 0 0 0 6 6l3-3a4 4 0 0 0 0-6M17 10l1-1a4 4 0 0 0-6-6L9 6a4 4 0 0 0 0 6"
      />
    </g>
    <g v-else-if="name === 'replay'">
      <path d="M4 10a8 8 0 1 1 0 6M4 4v6h6" />
    </g>
    <g v-else-if="name === 'shield'">
      <path d="M12 3 4 6v6c0 5 8 9 8 9s8-4 8-9V6z" />
      <path d="m8 12 3 3 5-6" />
    </g>
    <g v-else-if="name === 'calc'">
      <rect x="5" y="2" width="14" height="20" rx="2" />
      <path d="M8 6h8M8 11h1m6 0h1m-8 4h1m6 0h1m-8 4h1m6 0h1" />
    </g>
    <g v-else-if="name === 'cube'">
      <path d="m12 2 9 5v10l-9 5-9-5V7zM3 7l9 5 9-5M12 12v10m-4-17 9 5" />
    </g>
    <g v-else-if="name === 'cad'">
      <path d="M3 21V3h18v18zM3 11h10V3M13 21v-6h8M7 7h2M17 7h1M7 16h2" />
    </g>
    <g v-else-if="name === 'cloud'">
      <path d="M6 18a5 5 0 0 1-1-10 7 7 0 0 1 13-1 5.5 5.5 0 0 1 0 11z" />
      <path d="m9 13 3-3 3 3m-3-3v10" />
    </g>
    <g v-else-if="name === 'laptop'">
      <rect x="4" y="3" width="16" height="13" rx="2" />
      <path d="m4 16-2 5h20l-2-5M9 19h6" />
    </g>
    <g v-else-if="name === 'chat'">
      <path d="M4 3h16v14H9l-5 4zM8 8h8M8 12h5" />
    </g>
    <g v-else-if="name === 'archive'">
      <path d="M3 3h18v5H3zM5 8v13h14V8M9 12h6" />
    </g>
    <g v-else-if="name === 'user'">
      <circle cx="12" cy="7" r="4" />
      <path d="M4 21v-2a8 8 0 0 1 16 0v2" />
    </g>
    <g v-else-if="name === 'team'">
      <circle cx="9" cy="7" r="3" />
      <path d="M2 21v-3a7 7 0 0 1 14 0v3m1-17a3 3 0 0 1 0 6m2 4a6 6 0 0 1 3 5v2" />
    </g>
    <g v-else-if="name === 'plus'"><path d="M12 5v14M5 12h14" /></g>
    <g v-else-if="name === 'window'">
      <path d="m3 5 8-1v7H3zm10-1 8-1v8h-8zM3 13h8v7l-8-1zm10 0h8v8l-8-1z" />
    </g>
    <g v-else-if="name === 'apple'">
      <path
        d="M15 3c0 2-1.5 3-3 3 0-2 1-3 3-3zM12 8c-3-2-7-1-7 4 0 4 3 9 5 8 1-.6 3-.6 4 0 2 1 4-3 5-5-3-1-4-4-1-6-2-2-4-2-6-1z"
      />
    </g>
    <g v-else-if="name === 'alert'"><path d="m12 3 10 18H2zM12 9v5m0 3v1" /></g>
  </svg>
</template>
