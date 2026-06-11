<!--
  自动化任务管理页面
  - 展示「已安排」和「已完成」任务列表
  - 支持「添加自动化任务」对话框
  - 执行频率：每天 / 按间隔 / 单次
-->
<script setup lang="ts">
import { ref, computed } from 'vue'
import { Plus, Zap, Clock, CheckCircle2, Circle, Trash2, X, ChevronDown } from 'lucide-vue-next'

// ——— 类型定义 ———

type FrequencyType = 'daily' | 'interval' | 'once'
type WeekDay = 0 | 1 | 2 | 3 | 4 | 5 | 6

interface AutomationTask {
  id: string
  name: string
  workspace?: string
  prompt: string
  frequency: FrequencyType
  time?: string            // HH:mm，每天/单次模式使用
  intervalMinutes?: number // 按间隔模式使用
  weekDays?: WeekDay[]     // 每天模式选中的星期
  startDate?: string
  endDate?: string
  status: 'scheduled' | 'completed'
  nextRunLabel?: string    // 展示用，如「3天后开始」
  lastRunLabel?: string    // 展示用，如「3天前」
}

// ——— 状态 ———

/** 模拟任务列表（实际应从 API 获取） */
const tasks = ref<AutomationTask[]>([
  {
    id: '1',
    name: 'GitHub每周热门项目',
    prompt: '搜索本周 GitHub 上 star 数增长最快的 10 个仓库，输出名称、简介和 star 数。',
    frequency: 'daily',
    time: '09:00',
    weekDays: [0, 1, 2, 3, 4],
    status: 'scheduled',
    nextRunLabel: '3天后开始',
  },
  {
    id: '2',
    name: 'GitHub每周热门项目',
    prompt: '搜索本周 GitHub 上 star 数增长最快的 10 个仓库，输出名称、简介和 star 数。',
    frequency: 'daily',
    time: '09:00',
    weekDays: [0, 1, 2, 3, 4],
    status: 'completed',
    lastRunLabel: '3天前',
  },
])

const scheduledTasks = computed(() => tasks.value.filter((t) => t.status === 'scheduled'))
const completedTasks = computed(() => tasks.value.filter((t) => t.status === 'completed'))

// ——— 弹窗状态 ———

const showDialog = ref(false)

/** 表单数据 */
const form = ref({
  name: '',
  workspace: '',
  prompt: '',
  frequency: 'daily' as FrequencyType,
  time: '09:00',
  intervalMinutes: 60,
  weekDays: [0, 1, 2, 3, 4] as WeekDay[], // 默认周一到周五
  startDate: '',
  endDate: '',
  pushNotification: false,
})

const weekDayLabels: { value: WeekDay; label: string }[] = [
  { value: 0, label: '周一' },
  { value: 1, label: '周二' },
  { value: 2, label: '周三' },
  { value: 3, label: '周四' },
  { value: 4, label: '周五' },
  { value: 5, label: '周六' },
  { value: 6, label: '周日' },
]

function toggleWeekDay(day: WeekDay) {
  const idx = form.value.weekDays.indexOf(day)
  if (idx === -1) {
    form.value.weekDays = [...form.value.weekDays, day].sort((a, b) => a - b)
  } else {
    form.value.weekDays = form.value.weekDays.filter((d) => d !== day)
  }
}

function openDialog() {
  // 重置表单
  form.value = {
    name: '',
    workspace: '',
    prompt: '',
    frequency: 'daily',
    time: '09:00',
    intervalMinutes: 60,
    weekDays: [0, 1, 2, 3, 4],
    startDate: '',
    endDate: '',
    pushNotification: false,
  }
  showDialog.value = true
}

function closeDialog() {
  showDialog.value = false
}

function addTask() {
  if (!form.value.name.trim() || !form.value.prompt.trim()) return

  tasks.value.unshift({
    id: Date.now().toString(),
    name: form.value.name.trim(),
    workspace: form.value.workspace || undefined,
    prompt: form.value.prompt.trim(),
    frequency: form.value.frequency,
    time: form.value.time,
    intervalMinutes: form.value.intervalMinutes,
    weekDays: [...form.value.weekDays],
    startDate: form.value.startDate || undefined,
    endDate: form.value.endDate || undefined,
    status: 'scheduled',
    nextRunLabel: '稍后开始',
  })
  closeDialog()
}

function deleteTask(id: string) {
  tasks.value = tasks.value.filter((t) => t.id !== id)
}
</script>

<template>
  <div class="max-w-4xl mx-auto p-6 space-y-6">
    <!-- 页头 -->
    <div class="flex items-start justify-between">
      <div class="space-y-1">
        <h1 class="text-2xl font-semibold flex items-center gap-2">
          <Zap class="w-6 h-6" />
          自动化
        </h1>
        <p class="text-sm text-muted-foreground">管理自动化任务并查看执行历史</p>
      </div>
      <div class="flex items-center gap-2">
        <button
          class="px-3 py-1.5 text-sm border border-border rounded-lg hover:bg-muted/50 transition-colors"
          disabled
        >
          从模板添加
        </button>
        <button
          class="px-3 py-1.5 text-sm bg-primary text-primary-foreground rounded-lg hover:bg-primary/90 transition-colors flex items-center gap-1.5"
          @click="openDialog"
        >
          <Plus class="w-4 h-4" />
          添加
        </button>
      </div>
    </div>

    <!-- 已安排 -->
    <div class="space-y-2">
      <h2 class="text-sm font-medium text-muted-foreground">已安排</h2>
      <div
        v-if="scheduledTasks.length === 0"
        class="text-center py-10 text-sm text-muted-foreground border border-dashed border-border rounded-lg"
      >
        暂无已安排的任务
      </div>
      <div
        v-for="task in scheduledTasks"
        :key="task.id"
        class="flex items-center gap-3 px-4 py-3 bg-card border border-border rounded-lg hover:bg-muted/20 transition-colors group"
      >
        <Circle class="w-4 h-4 text-muted-foreground shrink-0" />
        <span class="flex-1 text-sm font-medium truncate">{{ task.name }}</span>
        <span class="text-xs text-muted-foreground shrink-0">{{ task.nextRunLabel }}</span>
        <button
          class="opacity-0 group-hover:opacity-100 transition-opacity p-1 rounded hover:bg-destructive/10 hover:text-destructive"
          @click="deleteTask(task.id)"
        >
          <Trash2 class="w-3.5 h-3.5" />
        </button>
      </div>
    </div>

    <!-- 已完成 -->
    <div class="space-y-2">
      <h2 class="text-sm font-medium text-muted-foreground">已完成</h2>
      <div
        v-if="completedTasks.length === 0"
        class="text-center py-10 text-sm text-muted-foreground border border-dashed border-border rounded-lg"
      >
        暂无已完成的任务
      </div>
      <div
        v-for="task in completedTasks"
        :key="task.id"
        class="flex items-center gap-3 px-4 py-3 bg-card border border-border rounded-lg hover:bg-muted/20 transition-colors group"
      >
        <CheckCircle2 class="w-4 h-4 text-green-500 shrink-0" />
        <span class="flex-1 text-sm font-medium truncate">{{ task.name }}</span>
        <span class="text-xs text-muted-foreground shrink-0">{{ task.lastRunLabel }}</span>
        <button
          class="opacity-0 group-hover:opacity-100 transition-opacity p-1 rounded hover:bg-destructive/10 hover:text-destructive"
          @click="deleteTask(task.id)"
        >
          <Trash2 class="w-3.5 h-3.5" />
        </button>
      </div>
    </div>
  </div>

  <!-- 添加自动化任务对话框 -->
  <Teleport to="body">
    <Transition
      enter-active-class="transition duration-150 ease-out"
      enter-from-class="opacity-0"
      enter-to-class="opacity-100"
      leave-active-class="transition duration-100 ease-in"
      leave-from-class="opacity-100"
      leave-to-class="opacity-0"
    >
      <div
        v-if="showDialog"
        class="fixed inset-0 z-50 flex items-center justify-center"
        @click.self="closeDialog"
      >
        <!-- 遮罩 -->
        <div class="absolute inset-0 bg-black/40 backdrop-blur-sm" @click="closeDialog" />

        <!-- 对话框主体 -->
        <div
          class="relative z-10 w-full max-w-xl mx-4 bg-muted/95 backdrop-blur-sm border border-border rounded-2xl shadow-2xl max-h-[90vh] overflow-y-auto"
        >
          <!-- 头部 -->
          <div class="flex items-center justify-between px-6 pt-6 pb-2">
            <h2 class="text-lg font-semibold">添加自动化任务</h2>
            <button
              class="p-1.5 rounded-lg hover:bg-muted transition-colors text-muted-foreground"
              @click="closeDialog"
            >
              <X class="w-4 h-4" />
            </button>
          </div>

          <div class="px-6 pb-6 space-y-5">
            <!-- 名称 -->
            <div class="space-y-1.5">
              <label class="text-sm font-medium">名称</label>
              <input
                v-model="form.name"
                type="text"
                placeholder="为任务起一个名称"
                class="w-full px-3 py-2.5 bg-background border border-border rounded-lg text-sm placeholder:text-muted-foreground focus:outline-none focus:ring-2 focus:ring-primary/30"
              />
            </div>

            <!-- 工作空间（可选） -->
            <div class="space-y-1.5">
              <label class="text-sm font-medium">
                工作空间
                <span class="text-muted-foreground font-normal ml-1">（可选）</span>
              </label>
              <div
                class="w-full px-3 py-2.5 bg-background border border-border rounded-lg flex items-center gap-2 cursor-pointer hover:border-primary/50 transition-colors text-sm text-muted-foreground"
              >
                <Plus class="w-4 h-4 shrink-0" />
                <span>选择工作空间</span>
              </div>
            </div>

            <!-- 提示词 -->
            <div class="space-y-1.5">
              <label class="text-sm font-medium">提示词</label>
              <div class="bg-background border border-border rounded-lg overflow-hidden focus-within:ring-2 focus-within:ring-primary/30">
                <textarea
                  v-model="form.prompt"
                  placeholder="描述你希望 AI 执行的任务内容..."
                  rows="6"
                  class="w-full px-3 pt-3 pb-2 text-sm placeholder:text-muted-foreground focus:outline-none resize-none bg-transparent"
                />
                <!-- 提示词工具栏 -->
                <div class="flex items-center gap-2 px-3 pb-2.5 pt-1 border-t border-border">
                  <button
                    class="flex items-center gap-1 px-2 py-1 text-xs bg-muted rounded-md hover:bg-muted/80 transition-colors text-foreground"
                  >
                    Auto
                    <ChevronDown class="w-3 h-3" />
                  </button>
                  <button
                    class="flex items-center gap-1 px-2 py-1 text-xs bg-muted rounded-md hover:bg-muted/80 transition-colors text-foreground"
                  >
                    Skills
                  </button>
                </div>
              </div>
            </div>

            <!-- 执行频率 -->
            <div class="space-y-3">
              <label class="text-sm font-medium">执行频率</label>

              <!-- 频率类型切换 -->
              <div class="flex gap-2">
                <button
                  v-for="opt in [
                    { value: 'daily', label: '每天' },
                    { value: 'interval', label: '按间隔' },
                    { value: 'once', label: '单次' },
                  ]"
                  :key="opt.value"
                  :class="[
                    'px-4 py-1.5 rounded-full text-sm font-medium transition-colors border',
                    form.frequency === opt.value
                      ? 'bg-foreground text-background border-foreground'
                      : 'bg-background text-foreground border-border hover:bg-muted/50',
                  ]"
                  @click="form.frequency = opt.value as FrequencyType"
                >
                  {{ opt.label }}
                </button>
              </div>

              <!-- 每天：时间 + 星期选择 -->
              <div v-if="form.frequency === 'daily'" class="flex items-center gap-3 flex-wrap">
                <div class="flex items-center gap-2 bg-background border border-border rounded-lg px-3 py-2">
                  <Clock class="w-4 h-4 text-muted-foreground" />
                  <input
                    v-model="form.time"
                    type="time"
                    class="text-sm bg-transparent focus:outline-none w-20"
                  />
                </div>
                <div class="flex gap-1.5">
                  <button
                    v-for="day in weekDayLabels"
                    :key="day.value"
                    :class="[
                      'w-9 h-9 rounded-full text-xs font-medium transition-colors',
                      form.weekDays.includes(day.value)
                        ? 'bg-foreground text-background'
                        : 'bg-background text-foreground border border-border hover:bg-muted/50',
                    ]"
                    @click="toggleWeekDay(day.value)"
                  >
                    {{ day.label }}
                  </button>
                </div>
              </div>

              <!-- 按间隔：间隔分钟数 -->
              <div v-if="form.frequency === 'interval'" class="flex items-center gap-2">
                <span class="text-sm text-muted-foreground">每隔</span>
                <input
                  v-model.number="form.intervalMinutes"
                  type="number"
                  min="1"
                  class="w-20 px-3 py-2 bg-background border border-border rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-primary/30"
                />
                <span class="text-sm text-muted-foreground">分钟</span>
              </div>

              <!-- 单次：时间选择 -->
              <div v-if="form.frequency === 'once'" class="flex items-center gap-2">
                <div class="flex items-center gap-2 bg-background border border-border rounded-lg px-3 py-2">
                  <Clock class="w-4 h-4 text-muted-foreground" />
                  <input
                    v-model="form.time"
                    type="time"
                    class="text-sm bg-transparent focus:outline-none w-20"
                  />
                </div>
              </div>
            </div>

            <!-- 生效日期区间 -->
            <div class="space-y-1.5">
              <label class="text-sm font-medium">
                生效日期区间
                <span class="text-muted-foreground font-normal ml-1">（可选，留空表示始终生效。）</span>
              </label>
              <div class="flex gap-2 items-center">
                <input
                  v-model="form.startDate"
                  type="date"
                  placeholder="开始日期"
                  class="flex-1 px-3 py-2.5 bg-background border border-border rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-primary/30 text-muted-foreground"
                />
                <span class="text-muted-foreground text-sm">—</span>
                <input
                  v-model="form.endDate"
                  type="date"
                  placeholder="结束日期"
                  class="flex-1 px-3 py-2.5 bg-background border border-border rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-primary/30 text-muted-foreground"
                />
              </div>
            </div>

            <!-- 推送通知开关 -->
            <div class="flex items-center justify-between py-1">
              <div>
                <span class="text-sm font-medium">执行完成后发送通知</span>
                <span class="text-xs text-muted-foreground ml-1.5">（可在消息渠道中配置）</span>
              </div>
              <!-- Toggle 按钮 -->
              <button
                :class="[
                  'relative inline-flex h-6 w-11 items-center rounded-full transition-colors focus:outline-none',
                  form.pushNotification ? 'bg-primary' : 'bg-muted-foreground/30',
                ]"
                @click="form.pushNotification = !form.pushNotification"
              >
                <span
                  :class="[
                    'inline-block h-4 w-4 transform rounded-full bg-white shadow transition-transform',
                    form.pushNotification ? 'translate-x-6' : 'translate-x-1',
                  ]"
                />
              </button>
            </div>

            <!-- 操作按钮 -->
            <div class="flex justify-end gap-2 pt-1">
              <button
                class="px-4 py-2 text-sm border border-border rounded-lg hover:bg-muted/50 transition-colors"
                @click="closeDialog"
              >
                取消
              </button>
              <button
                :disabled="!form.name.trim() || !form.prompt.trim()"
                :class="[
                  'px-4 py-2 text-sm rounded-lg transition-colors font-medium',
                  form.name.trim() && form.prompt.trim()
                    ? 'bg-foreground text-background hover:bg-foreground/90'
                    : 'bg-muted text-muted-foreground cursor-not-allowed',
                ]"
                @click="addTask"
              >
                添加
              </button>
            </div>
          </div>
        </div>
      </div>
    </Transition>
  </Teleport>
</template>
