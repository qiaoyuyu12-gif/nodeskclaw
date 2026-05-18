<script setup lang="ts">
defineProps<{ sourceType: 'doc' | 'system' | 'mixed' }>()

const labelMap = { doc: '文档', system: '系统数据', mixed: '混合' }
const colorMap = {
  doc: 'bg-blue-100 text-blue-700',
  system: 'bg-purple-100 text-purple-700',
  mixed: 'bg-amber-100 text-amber-700',
}
</script>

<template>
  <span
    class="inline-flex items-center rounded-full px-2.5 py-0.5 text-xs font-medium"
    :class="colorMap[sourceType]"
  >
    {{ labelMap[sourceType] }}
  </span>
</template>
