<script setup lang="ts">
import { ref, computed } from 'vue'
import { useRouter } from 'vue-router'
import { useI18n } from 'vue-i18n'
import { useAuthStore } from '@/stores/auth'
import { getCurrentLocale, setCurrentLocale } from '@/i18n'
import { resolveApiErrorMessage } from '@/i18n/error'
import { Loader2, Eye, EyeOff, ArrowLeft } from 'lucide-vue-next'
import LocaleSelect from '@/components/shared/LocaleSelect.vue'

const router = useRouter()
const authStore = useAuthStore()
const { t } = useI18n()

const loading = ref(false)
const error = ref('')

const form = ref({ name: '', email: '', phone: '', password: '' })
const showPassword = ref(false)
const locale = ref(getCurrentLocale())

const canSubmit = computed(() => {
  return form.value.name && form.value.email && form.value.password.length >= 6
})

async function handleSubmit() {
  if (!canSubmit.value || loading.value) return
  loading.value = true
  try {
    await authStore.register(form.value.name, form.value.email, form.value.password, form.value.phone || undefined)
    error.value = ''
    router.replace('/')
  } catch (e: any) {
    error.value = resolveApiErrorMessage(e, t('auth.registerFailed'))
  } finally {
    loading.value = false
  }
}

function onLocaleChange(value: string) {
  locale.value = setCurrentLocale(value)
}
</script>

<template>
  <div class="min-h-screen flex">
    <!-- 左侧品牌区 -->
    <div class="hidden lg:flex lg:w-[55%] relative overflow-hidden bg-linear-to-br from-primary/20 via-background to-background">
      <div class="absolute inset-0">
        <div class="absolute inset-0 brand-grid opacity-[0.04]" />
        <div class="absolute top-[15%] left-[20%] w-[500px] h-[500px] rounded-full bg-primary/6 blur-[100px] brand-float" />
        <div class="absolute bottom-[10%] right-[15%] w-[400px] h-[400px] rounded-full bg-primary/8 blur-[80px] brand-float-reverse" />
      </div>

      <div class="relative z-10 flex flex-col justify-between px-12 xl:px-20 py-12">
        <div class="flex items-center gap-3">
          <img src="/logo.png" alt="DeskClaw" class="w-10 h-10" />
          <span class="text-xl font-bold tracking-tight">DeskClaw</span>
          <span class="px-1.5 py-0.5 text-[10px] font-semibold leading-none rounded bg-primary/15 text-primary">Beta</span>
        </div>

        <div>
          <h1 class="text-4xl xl:text-5xl font-bold leading-tight mb-5">
            {{ t('auth.landing.headline1') }}<br />
            <span class="text-primary">{{ t('auth.landing.headline2') }}</span>
          </h1>
          <p class="text-base text-muted-foreground max-w-lg mb-10 leading-relaxed">
            {{ t('auth.landing.subtitle') }}
          </p>
        </div>
      </div>
    </div>

    <!-- 右侧注册区 -->
    <div class="flex-1 flex items-center justify-center px-6">
      <div class="w-full max-w-sm space-y-6">
        <div class="flex justify-end">
          <LocaleSelect :model-value="locale" @update:model-value="onLocaleChange" />
        </div>

        <button
          class="flex items-center gap-1 text-sm text-muted-foreground hover:text-foreground transition-colors"
          @click="router.back()"
        >
          <ArrowLeft class="w-4 h-4" />
          {{ t('common.goBack') }}
        </button>

        <div class="space-y-1 text-center lg:text-left">
          <h2 class="text-2xl font-bold">{{ t('auth.registerTitle') || '创建账号' }}</h2>
          <p class="text-sm text-muted-foreground">
            {{ t('auth.registerSubtitle') || '填写信息以创建你的账号' }}
          </p>
        </div>

        <form class="space-y-4" @submit.prevent="handleSubmit">
          <div class="space-y-1.5">
            <label class="text-sm font-medium text-foreground">{{ t('auth.nameLabel') }}</label>
            <input
              v-model="form.name"
              type="text"
              :placeholder="t('auth.namePlaceholder')"
              required
              class="w-full h-10 px-3 rounded-lg border border-input bg-background text-sm placeholder:text-muted-foreground focus:outline-none focus:ring-2 focus:ring-ring focus:ring-offset-1 transition-shadow"
            />
          </div>

          <div class="space-y-1.5">
            <label class="text-sm font-medium text-foreground">{{ t('auth.emailLabel') }}</label>
            <input
              v-model="form.email"
              type="email"
              inputmode="email"
              :placeholder="t('auth.emailPlaceholder')"
              required
              class="w-full h-10 px-3 rounded-lg border border-input bg-background text-sm placeholder:text-muted-foreground focus:outline-none focus:ring-2 focus:ring-ring focus:ring-offset-1 transition-shadow"
            />
          </div>

          <div class="space-y-1.5">
            <label class="text-sm font-medium text-foreground">{{ t('auth.phoneLabel') || '手机号（可选）' }}</label>
            <input
              v-model="form.phone"
              type="tel"
              inputmode="tel"
              :placeholder="t('auth.phonePlaceholder') || '可选'"
              class="w-full h-10 px-3 rounded-lg border border-input bg-background text-sm placeholder:text-muted-foreground focus:outline-none focus:ring-2 focus:ring-ring focus:ring-offset-1 transition-shadow"
            />
          </div>

          <div class="space-y-1.5">
            <label class="text-sm font-medium text-foreground">{{ t('auth.passwordLabel') }}</label>
            <div class="relative">
              <input
                v-model="form.password"
                :type="showPassword ? 'text' : 'password'"
                :placeholder="t('auth.passwordPlaceholder')"
                required
                minlength="6"
                class="w-full h-10 px-3 pr-10 rounded-lg border border-input bg-background text-sm placeholder:text-muted-foreground focus:outline-none focus:ring-2 focus:ring-ring focus:ring-offset-1 transition-shadow"
              />
              <button
                type="button"
                tabindex="-1"
                class="absolute right-3 top-1/2 -translate-y-1/2 text-muted-foreground hover:text-foreground transition-colors"
                @click="showPassword = !showPassword"
              >
                <EyeOff v-if="showPassword" class="w-4 h-4" />
                <Eye v-else class="w-4 h-4" />
              </button>
            </div>
            <p class="text-xs text-muted-foreground">{{ t('auth.passwordMinLength') }}</p>
          </div>

          <button
            type="submit"
            :disabled="!canSubmit || loading"
            class="w-full h-10 rounded-lg bg-primary text-primary-foreground font-medium text-sm hover:bg-primary/90 transition-all hover:shadow-lg hover:shadow-primary/20 disabled:opacity-50 disabled:cursor-not-allowed flex items-center justify-center gap-2"
          >
            <Loader2 v-if="loading" class="w-4 h-4 animate-spin" />
            {{ t('auth.register') }}
          </button>
        </form>

        <Transition
          enter-active-class="transition duration-200 ease-out"
          enter-from-class="opacity-0 -translate-y-1"
          enter-to-class="opacity-100 translate-y-0"
          leave-active-class="transition duration-150 ease-in"
          leave-from-class="opacity-100 translate-y-0"
          leave-to-class="opacity-0 -translate-y-1"
        >
          <p v-if="error" class="text-sm text-destructive text-center bg-destructive/10 rounded-lg py-2.5 px-3 border border-destructive/20">
            {{ error }}
          </p>
        </Transition>

        <p class="text-center text-sm text-muted-foreground">
          {{ t('auth.alreadyHaveAccount') || '已有账号？' }}
          <router-link to="/login" class="text-primary font-medium hover:underline ml-1">
            {{ t('auth.login') }}
          </router-link>
        </p>

        <div class="pt-4 text-center">
          <p class="text-[11px] text-muted-foreground/50">
            DeskClaw &copy; 2026 &middot; by <a href="https://nodesks.ai/" target="_blank" class="hover:text-muted-foreground transition-colors underline underline-offset-2">NoDesk AI</a>
          </p>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.brand-grid {
  background-image:
    linear-gradient(to right, currentColor 1px, transparent 1px),
    linear-gradient(to bottom, currentColor 1px, transparent 1px);
  background-size: 60px 60px;
}

.brand-float {
  animation: brand-float 12s ease-in-out infinite;
}

.brand-float-reverse {
  animation: brand-float 15s ease-in-out infinite reverse;
}

@keyframes brand-float {
  0%, 100% { transform: translate(0, 0); }
  50% { transform: translate(10px, -15px); }
}
</style>