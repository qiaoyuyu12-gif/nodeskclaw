import { computed } from 'vue'
import { useAuthStore } from '@/stores/auth'

export function useFeature(featureId: string) {
  const authStore = useAuthStore()

  const isEnabled = computed(() => {
    const info = authStore.systemInfo
    if (!info) return false
    const feature = info.features.find(f => f.id === featureId)
    // features 数组只登记了受控 feature；不在列表里的 id 视为不受控，默认放行
    if (!feature) return true
    return feature.enabled
  })

  return { isEnabled }
}

export function useEdition() {
  const authStore = useAuthStore()

  const edition = computed(() => authStore.systemInfo?.edition ?? 'ce')
  const isEE = computed(() => edition.value === 'ee')

  return { edition, isEE }
}
