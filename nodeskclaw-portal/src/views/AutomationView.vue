<!--
  自动化任务管理页面
  - 展示「已安排」和「已完成」任务列表
  - 支持「添加自动化任务」对话框
  - 执行频率：每天 / 按间隔 / 单次
  - AI 员工字段为必选，从 GET /api/v1/instances 拉取
-->
<script setup lang="ts">
import { ref, computed, onMounted, onBeforeUnmount } from 'vue'
import { Plus, Zap, Clock, CheckCircle2, Circle, Trash2, X, ChevronDown, Bot } from 'lucide-vue-next'
import api from '@/services/api'

// ——— 类型定义 ———

type FrequencyType = 'daily' | 'interval' | 'once'
type WeekDay = 0 | 1 | 2 | 3 | 4 | 5 | 6

interface InstanceInfo {
  id: string
  name: string
  display_status?: string
  status: string
}

interface AutomationTask {
  id: string
  name: string
  instanceId: string
  instanceName: string
  prompt: string
  frequency: FrequencyType
  time?: string
  intervalMinutes?: number
  weekDays?: WeekDay[]
  startDate?: string
  endDate?: string
  status: 'scheduled' | 'completed'
  nextRunLabel?: string
  lastRunLabel?: string
}

// ——— AI 员工列表 ———

const instances = ref<InstanceInfo[]>([])
const instancesLoading = ref(false)

async function fetchInstances() {
  instancesLoading.value = true
  try {
    const { data } = await api.get('/instances')
    instances.value = data.data ?? []
  } finally {
    instancesLoading.value = false
  }
}

onMounted(fetchInstances)

// ——— 任务列表 ———

const tasks = ref<AutomationTask[]>([])

const scheduledTasks = computed(() => tasks.value.filter((t) => t.status === 'scheduled'))
const completedTasks = computed(() => tasks.value.filter((t) => t.status === 'completed'))

// ——— 弹窗 & 表单 ———

const showDialog = ref(false)

const form = ref({
  name: '',
  instanceId: '',   // 必选，AI 员工 id
  prompt: '',
  frequency: 'daily' as FrequencyType,
  time: '09:00',
  intervalMinutes: 60,
  weekDays: [0, 1, 2, 3, 4] as WeekDay[],
  startDate: '',
  endDate: '',
  pushNotification: false,
})

/** AI 员工下拉展开状态 */
const instanceDropdownOpen = ref(false)
const instanceDropdownRef = ref<HTMLElement>()

/** 当前选中的实例对象 */
const selectedInstance = computed(() =>
  instances.value.find((i) => i.id === form.value.instanceId) ?? null,
)

/** 表单是否可提交 */
const canSubmit = computed(
  () => form.value.name.trim() !== '' && form.value.instanceId !== '' && form.value.prompt.trim() !== '',
)

function selectInstance(instance: InstanceInfo) {
  form.value.instanceId = instance.id
  instanceDropdownOpen.value = false
}

/** 点击外部关闭下拉 */
function onDocumentClick(e: MouseEvent) {
  if (
    instanceDropdownOpen.value &&
    instanceDropdownRef.value &&
    !instanceDropdownRef.value.contains(e.target as Node)
  ) {
    instanceDropdownOpen.value = false
  }
}

onMounted(() => document.addEventListener('click', onDocumentClick))
onBeforeUnmount(() => document.removeEventListener('click', onDocumentClick))

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
  form.value = {
    name: '',
    instanceId: '',
    prompt: '',
    frequency: 'daily',
    time: '09:00',
    intervalMinutes: 60,
    weekDays: [0, 1, 2, 3, 4],
    startDate: '',
    endDate: '',
    pushNotification: false,
  }
  instanceDropdownOpen.value = false
  showDialog.value = true
}

function closeDialog() {
  showDialog.value = false
}

function addTask() {
  if (!canSubmit.value) return

  tasks.value.unshift({
    id: Date.now().toString(),
    name: form.value.name.trim(),
    instanceId: form.value.instanceId,
    instanceName: selectedInstance.value?.name ?? '',
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
          class="px-3 py-1.5 text-sm border border-border rounded-lg hover:bg-muted/50 transition-colors opacity-50 cursor-not-allowed"
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
        <div class="flex-1 min-w-0">
          <span class="text-sm font-medium truncate block">{{ task.name }}</span>
          <span class="text-xs text-muted-foreground truncate block">{{ task.instanceName }}</span>
        </div>
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
        <div class="flex-1 min-w-0">
          <span class="text-sm font-medium truncate block">{{ task.name }}</span>
          <span class="text-xs text-muted-foreground truncate block">{{ task.instanceName }}</span>
        </div>
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

            <!-- AI 员工（必选） -->
            <div class="space-y-1.5" ref="instanceDropdownRef">
              <label class="text-sm font-medium">AI 员工</label>
              <!-- 触发器 -->
              <button
                type="button"
                :class="[
                  'w-full px-3 py-2.5 bg-background border rounded-lg text-sm flex items-center gap-2 transition-colors',
                  instanceDropdownOpen
                    ? 'border-primary/50 ring-2 ring-primary/30'
                    : 'border-border hover:border-primary/40',
                ]"
                @click="instanceDropdownOpen = !instanceDropdownOpen"
              >
                <Bot class="w-4 h-4 text-muted-foreground shrink-0" />
                <span
                  :class="selectedInstance ? 'text-foreground flex-1 text-left' : 'text-muted-foreground flex-1 text-left'"
                >
                  {{ selectedInstance ? selectedInstance.name : '选择 AI 员工' }}
                </span>
                <ChevronDown
                  :class="['w-4 h-4 text-muted-foreground transition-transform', instanceDropdownOpen && 'rotate-180']"
                />
              </button>

              <!-- 下拉选项 -->
              <div
                v-if="instanceDropdownOpen"
                class="absolute z-20 w-full max-w-[calc(100%-3rem)] bg-background border border-border rounded-xl shadow-xl overflow-hidden"
              >
                <!-- 加载中 -->
                <div
                  v-if="instancesLoading"
                  class="px-4 py-3 text-sm text-muted-foreground text-center"
                >
                  加载中...
                </div>
                <!-- 空列表 -->
                <div
                  v-else-if="instances.length === 0"
                  class="px-4 py-3 text-sm text-muted-foreground text-center"
                >
                  暂无可用的 AI 员工
                </div>
                <!-- 实例列表 -->
                <div v-else class="max-h-52 overflow-y-auto py-1">
                  <button
                    v-for="inst in instances"
                    :key="inst.id"
                    type="button"
                    :class="[
                      'w-full flex items-center gap-3 px-4 py-2.5 text-sm text-left transition-colors',
                      form.instanceId === inst.id
                        ? 'bg-primary/10 text-primary'
                        : 'hover:bg-muted/60 text-foreground',
                    ]"
                    @click="selectInstance(inst)"
                  >
                    <Bot class="w-4 h-4 shrink-0" />
                    <span class="flex-1 truncate">{{ inst.name }}</span>
                    <!-- 状态点 -->
                    <span
                      :class="[
                        'w-2 h-2 rounded-full shrink-0',
                        inst.display_status === 'ready' || inst.status === 'running'
                          ? 'bg-green-400'
                          : 'bg-muted-foreground/40',
                      ]"
                    />
                  </button>
                </div>
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
                    type="button"
                    class="flex items-center gap-1 px-2 py-1 text-xs bg-muted rounded-md hover:bg-muted/80 transition-colors text-foreground"
                  >
                    Auto
                    <ChevronDown class="w-3 h-3" />
                  </button>
                  <button
                    type="button"
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
                  type="button"
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
                <div class="flex gap-1.5 flex-wrap">
                  <button
                    v-for="day in weekDayLabels"
                    :key="day.value"
                    type="button"
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
                  class="flex-1 px-3 py-2.5 bg-background border border-border rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-primary/30 text-muted-foreground"
                />
                <span class="text-muted-foreground text-sm">—</span>
                <input
                  v-model="form.endDate"
                  type="date"
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
              <button
                type="button"
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
                type="button"
                class="px-4 py-2 text-sm border border-border rounded-lg hover:bg-muted/50 transition-colors"
                @click="closeDialog"
              >
                取消
              </button>
              <button
                type="button"
                :disabled="!canSubmit"
                :class="[
                  'px-4 py-2 text-sm rounded-lg transition-colors font-medium',
                  canSubmit
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
