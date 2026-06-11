import { defineStore } from 'pinia'
import { ref } from 'vue'
import { useAdminApi, type AdminOrg, type AdminPlan } from '../api'

export const useAdminStore = defineStore('admin', () => {
  const { fetchOrgs, createOrg, updateOrg, deleteOrg, fetchPlans, createPlan, updatePlan, deletePlan } = useAdminApi()

  const orgs = ref<AdminOrg[]>([])
  const plans = ref<AdminPlan[]>([])
  const loading = ref(false)
  const error = ref<string | null>(null)

  async function loadOrgs() {
    loading.value = true
    error.value = null
    try {
      orgs.value = await fetchOrgs()
    } catch (e: unknown) {
      error.value = (e as Error).message
      throw e
    } finally {
      loading.value = false
    }
  }

  async function addOrg(data: Parameters<typeof createOrg>[0]) {
    const org = await createOrg(data)
    orgs.value.push(org)
    return org
  }

  async function editOrg(id: string, data: Parameters<typeof updateOrg>[1]) {
    const updated = await updateOrg(id, data)
    const idx = orgs.value.findIndex(o => o.id === id)
    if (idx !== -1) orgs.value[idx] = updated
    return updated
  }

  async function removeOrg(id: string) {
    await deleteOrg(id)
    orgs.value = orgs.value.filter(o => o.id !== id)
  }

  async function loadPlans() {
    loading.value = true
    error.value = null
    try {
      plans.value = await fetchPlans()
    } catch (e: unknown) {
      error.value = (e as Error).message
      throw e
    } finally {
      loading.value = false
    }
  }

  async function addPlan(data: Parameters<typeof createPlan>[0]) {
    const plan = await createPlan(data)
    plans.value.push(plan)
    return plan
  }

  async function editPlan(name: string, data: Parameters<typeof updatePlan>[1]) {
    const updated = await updatePlan(name, data)
    const idx = plans.value.findIndex(p => p.name === name)
    if (idx !== -1) plans.value[idx] = updated
    return updated
  }

  async function removePlan(name: string) {
    await deletePlan(name)
    plans.value = plans.value.filter(p => p.name !== name)
  }

  return {
    orgs,
    plans,
    loading,
    error,
    loadOrgs,
    addOrg,
    editOrg,
    removeOrg,
    loadPlans,
    addPlan,
    editPlan,
    removePlan,
  }
})