<script setup lang="ts">
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'
import { Bot, Container, MessageSquare, ExternalLink } from 'lucide-vue-next'
import { getStatusDisplay } from '@/utils/instanceStatus'

// AI 员工实例的基本信息接口
interface InstanceInfo {
  id: string
  name: string
  cluster_id: string
  namespace: string
  image_version: string
  status: string
  display_status?: string
  compute_provider?: string
  my_role: string | null
}

const props = defineProps<{
  instance: InstanceInfo
}>()

const emit = defineEmits<{
  chat: []      // 点击卡片主体，进入对话
  detail: []    // 点击底部详情按钮
}>()

const { t } = useI18n()

// 状态展示信息
const statusDisplay = computed(() => getStatusDisplay(props.instance.display_status ?? ''))

// 角色显示文字
const roleKey = computed(() => {
  const map: Record<string, string> = {
    admin: 'instanceMembers.roleAdmin',
    editor: 'instanceMembers.roleEditor',
    user: 'instanceMembers.roleUser',
    viewer: 'instanceMembers.roleViewer',
  }
  return props.instance.my_role ? map[props.instance.my_role] : null
})

// 卡片主体点击 → 进入对话
function onCardClick() {
  emit('chat')
}

// 详情按钮点击（阻止冒泡到卡片 click）
function onDetailClick(e: MouseEvent) {
  e.stopPropagation()
  emit('detail')
}
</script>

<template>
  <!-- 整张卡片可点击，进入对话 -->
  <div
    class="group flex flex-col rounded-xl border border-border bg-card hover:border-primary/40 hover:shadow-md cursor-pointer transition-all duration-150 overflow-hidden"
    @click="onCardClick"
  >
    <!-- 卡片主体内容区 -->
    <div class="flex-1 p-4 space-y-3">
      <!-- 顶部：状态指示 + AI Bot 图标 -->
      <div class="flex items-start justify-between">
        <!-- 状态圆点 + 标签 -->
        <span class="inline-flex items-center gap-1.5 text-xs">
          <span
            class="w-2 h-2 rounded-full shrink-0"
            :class="[statusDisplay.bgColor, statusDisplay.pulse ? 'animate-pulse' : '']"
          />
          <span :class="statusDisplay.color">
            {{ t(`displayStatus.${statusDisplay.key}`) }}
          </span>
        </span>

        <!-- 进入对话图标提示 -->
        <MessageSquare class="w-4 h-4 text-muted-foreground opacity-0 group-hover:opacity-60 transition-opacity" />
      </div>

      <!-- Bot 图标 -->
      <div class="flex justify-center py-2">
        <div class="w-14 h-14 rounded-2xl flex items-center justify-center"
          style="background-color: var(--agent-color, rgba(var(--primary), 0.1))"
        >
          <Bot class="w-7 h-7 text-primary" />
        </div>
      </div>

      <!-- 实例名称 -->
      <div class="text-center space-y-1">
        <div class="font-semibold text-sm flex items-center justify-center gap-1.5">
          <span class="truncate max-w-[140px]">{{ instance.name }}</span>
          <!-- Docker 标签 -->
          <span
            v-if="instance.compute_provider === 'docker'"
            class="inline-flex items-center gap-0.5 px-1.5 py-0.5 rounded text-[10px] font-semibold bg-sky-500/15 text-sky-400 shrink-0"
          >
            <Container class="w-3 h-3" />
            Docker
          </span>
        </div>

        <!-- 镜像版本 -->
        <div class="text-xs text-muted-foreground font-mono truncate">
          {{ instance.image_version || '-' }}
        </div>
      </div>

      <!-- 角色 badge（如果有） -->
      <div v-if="roleKey" class="flex justify-center">
        <span class="px-2 py-0.5 rounded-full text-[10px] font-medium bg-primary/10 text-primary">
          {{ t(roleKey) }}
        </span>
      </div>
    </div>

    <!-- 卡片底部：详情入口 -->
    <div class="border-t border-border">
      <button
        class="w-full flex items-center justify-center gap-1.5 px-3 py-2 text-xs text-muted-foreground hover:text-foreground hover:bg-accent/50 transition-colors"
        @click="onDetailClick"
      >
        <ExternalLink class="w-3.5 h-3.5" />
        {{ t('instanceCard.detail') }}
      </button>
    </div>
  </div>
</template>
