<!-- 功能开关列表页：主表格 + 右侧抽屉展示 org override 详情 -->
<template>
  <div class="p-6 space-y-4">
    <h2 class="text-2xl font-semibold">功能开关</h2>

    <!-- 主功能列表表格，行点击打开覆盖抽屉 -->
    <table class="w-full text-sm">
      <thead>
        <tr class="text-left border-b">
          <th class="pb-2 pr-4">Feature</th>
          <th class="pb-2 pr-4">名称</th>
          <th class="pb-2 pr-4">描述</th>
          <th class="pb-2 pr-4">默认</th>
          <th class="pb-2">覆盖</th>
        </tr>
      </thead>
      <tbody>
        <tr
          v-for="f in features"
          :key="f.feature_id"
          class="hover:bg-muted/50 cursor-pointer border-b"
          @click="openDrawer(f)"
        >
          <td class="py-2 pr-4 font-mono text-xs">{{ f.feature_id }}</td>
          <td class="py-2 pr-4">{{ f.name }}</td>
          <td class="py-2 pr-4 text-muted-foreground">{{ f.description }}</td>
          <td class="py-2 pr-4">{{ f.default_enabled ? '开' : '关' }}</td>
          <td class="py-2">{{ f.override_count }} 个组织</td>
        </tr>
      </tbody>
    </table>

    <!-- 右侧抽屉：显示选中 feature 的 org override 列表 -->
    <aside
      v-if="drawerFeature"
      class="fixed top-0 right-0 h-full w-[480px] bg-card shadow-xl border-l border-border p-6 overflow-auto z-50"
    >
      <div class="flex justify-between items-center mb-4">
        <h3 class="text-lg font-semibold">{{ drawerFeature.feature_id }} 的组织覆盖</h3>
        <!-- 关闭按钮 -->
        <button class="text-muted-foreground hover:text-foreground" @click="drawerFeature = null">关闭</button>
      </div>

      <!-- 覆盖列表为空时的提示 -->
      <p v-if="overrides.length === 0" class="text-sm text-muted-foreground/70">暂无组织覆盖。</p>

      <table v-else class="w-full text-sm">
        <thead>
          <tr class="text-left border-b">
            <th class="pb-2 pr-3">组织</th>
            <th class="pb-2 pr-3">状态</th>
            <th class="pb-2 pr-3">理由</th>
            <th class="pb-2 pr-3">时间</th>
            <th class="pb-2"></th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="o in overrides" :key="o.org_id" class="border-b">
            <td class="py-2 pr-3 font-mono text-xs">{{ o.org_id }}</td>
            <td class="py-2 pr-3">{{ o.enabled ? '强制开' : '强制关' }}</td>
            <td class="py-2 pr-3 text-muted-foreground">{{ o.reason ?? '-' }}</td>
            <td class="py-2 pr-3 text-muted-foreground/70 text-xs">{{ o.set_at }}</td>
            <!-- 清除该 org 的 feature override -->
            <td class="py-2">
              <button class="text-red-500 hover:text-red-700 text-xs" @click="onClear(o)">清除</button>
            </td>
          </tr>
        </tbody>
      </table>
    </aside>
  </div>
</template>

<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { useAdminApi, type AdminFeatureItem } from '@/services/adminApi'

const api = useAdminApi()

// 功能列表数据
const features = ref<AdminFeatureItem[]>([])
// 当前打开抽屉对应的 feature，null 表示抽屉关闭
const drawerFeature = ref<AdminFeatureItem | null>(null)
// 当前抽屉中展示的 override 列表
const overrides = ref<any[]>([])

// 初始化加载所有 feature
onMounted(async () => {
  features.value = await api.fetchFeatures()
})

// 点击行：打开抽屉并拉取该 feature 的 org override 列表
async function openDrawer(f: AdminFeatureItem) {
  drawerFeature.value = f
  const res = await api.fetchFeatureOverrides(f.feature_id)
  overrides.value = res.data
}

// 清除某 org 的 override，之后刷新抽屉和主表格
async function onClear(o: any) {
  if (!drawerFeature.value) return
  if (!confirm('清除 override？')) return
  await api.clearOrgFeature(o.org_id, drawerFeature.value.feature_id)
  await openDrawer(drawerFeature.value)
  // 刷新主表格 override_count
  features.value = await api.fetchFeatures()
}
</script>
