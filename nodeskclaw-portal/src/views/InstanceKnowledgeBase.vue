<script setup lang="ts">
import { computed, inject, ref, type ComputedRef, type Ref } from 'vue'
import InstanceKbPanel from '@/components/instance/InstanceKbPanel.vue'

const instanceId = inject<ComputedRef<string>>('instanceId')!
const myInstanceRole = inject<Ref<string | null>>('myInstanceRole', ref(null))
const ROLE_LEVEL: Record<string, number> = { viewer: 10, user: 20, editor: 30, admin: 40 }
const canEdit = computed(() => (ROLE_LEVEL[myInstanceRole.value ?? ''] ?? 0) >= ROLE_LEVEL.admin)
</script>

<template>
  <InstanceKbPanel :instance-id="instanceId" :can-edit="canEdit" />
</template>
