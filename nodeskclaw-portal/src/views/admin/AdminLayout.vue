<template>
  <!-- 超管后台布局：左侧导航 + 右侧内容区 -->
  <div class="flex h-screen bg-gray-50">
    <!-- 左侧侧边栏 -->
    <aside class="w-56 shrink-0 border-r border-gray-200 bg-white flex flex-col">
      <!-- 返回门户 -->
      <div class="p-4 border-b border-gray-200">
        <router-link
          to="/"
          class="flex items-center gap-2 text-sm text-gray-600 hover:text-gray-900 transition-colors"
        >
          <Home class="w-4 h-4" />
          <span>返回门户</span>
        </router-link>
      </div>

      <!-- 导航入口 -->
      <nav class="flex-1 p-3 space-y-1">
        <router-link
          v-for="item in navItems"
          :key="item.to"
          :to="item.to"
          class="flex items-center gap-2.5 px-3 py-2 rounded-md text-sm text-gray-700 hover:bg-gray-100 transition-colors"
          active-class="bg-gray-100 text-gray-900 font-medium"
        >
          <component :is="item.icon" class="w-4 h-4 shrink-0" />
          <span>{{ item.label }}</span>
        </router-link>
      </nav>
    </aside>

    <!-- 右侧内容区 -->
    <main class="flex-1 overflow-auto">
      <router-view />
    </main>
  </div>
</template>

<script setup lang="ts">
import { Home, Building2, Users, ToggleLeft, ClipboardList } from 'lucide-vue-next'

// 侧边栏导航项定义
const navItems = [
  { to: '/admin/orgs', icon: Building2, label: 'Orgs' },
  { to: '/admin/users', icon: Users, label: 'Users' },
  { to: '/admin/features', icon: ToggleLeft, label: 'Features' },
  { to: '/admin/audit', icon: ClipboardList, label: 'Audit' },
]
</script>
