<script setup lang="ts">
import { ref, computed, watch } from 'vue'
import { useRouter } from 'vue-router'
import { useI18n } from 'vue-i18n'
import { useAuthStore } from '@/stores/auth'
import { getCurrentLocale, setCurrentLocale } from '@/i18n'
import { resolveApiErrorMessage } from '@/i18n/error'
import { useConfirm } from '@/composables/useConfirm'
import { useEdition } from '@/composables/useFeature'
import { Loader2, Building2, BrainCircuit, Rocket, Target, KeyRound, MessageSquareCode, Eye, EyeOff, ExternalLink } from 'lucide-vue-next'
import LocaleSelect from '@/components/shared/LocaleSelect.vue'

const router = useRouter()
const authStore = useAuthStore()
const { t } = useI18n()
const { confirm } = useConfirm()
const { isEE } = useEdition()

const loading = ref(false)
const error = ref('')
const activeTab = ref<'account' | 'code'>('account')

const accountForm = ref({ account: '', password: '' })
const showPassword = ref(false)

const codeForm = ref({ account: '', code: '' })
const codeSending = ref(false)
const codeCountdown = ref(0)
let codeTimer: ReturnType<typeof setInterval> | null = null
const locale = ref(getCurrentLocale())

const themes = [
  { icon: Building2, key: 'cyberOffice' },
  { icon: BrainCircuit, key: 'aiEmployee' },
  { icon: Target, key: 'aiOkr' },
  { icon: Rocket, key: 'industryShift' },
]

const canSubmitAccount = computed(() => {
  return accountForm.value.account && accountForm.value.password
})

function isEmailInput(value: string) {
  return /^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(value.trim())
}

const canSubmitCode = computed(() => {
  return isEmailInput(codeForm.value.account) && codeForm.value.code.length >= 4
})

async function handleAccountSubmit() {
  if (!canSubmitAccount.value || loading.value) return
  if (isEE.value && isNonWhitelistedEmail(accountForm.value.account)) {
    await showWaitlistDialog()
    return
  }
  loading.value = true
  try {
    await authStore.accountLogin(accountForm.value.account, accountForm.value.password)
    error.value = ''
    router.replace('/')
  } catch (e: any) {
    const detail = e?.response?.data?.detail
    if (isEE.value && detail?.message_key === 'errors.auth.email_domain_not_allowed') {
      await showWaitlistDialog()
      return
    }
    error.value = resolveApiErrorMessage(e, t('auth.loginFailed'))
  } finally {
    loading.value = false
  }
}

async function handleSendCode() {
  if (!codeForm.value.account || codeSending.value || codeCountdown.value > 0) return
  if (!isEmailInput(codeForm.value.account)) {
    error.value = t('auth.codeEmailOnly')
    return
  }
  if (isEE.value && isNonWhitelistedEmail(codeForm.value.account)) {
    await showWaitlistDialog()
    return
  }
  codeSending.value = true
  try {
    await authStore.sendVerificationCode(codeForm.value.account)
    codeCountdown.value = 60
    codeTimer = setInterval(() => {
      codeCountdown.value--
      if (codeCountdown.value <= 0 && codeTimer) {
        clearInterval(codeTimer)
        codeTimer = null
      }
    }, 1000)
  } catch (e: any) {
    const detail = e?.response?.data?.detail
    if (isEE.value && detail?.message_key === 'errors.auth.email_domain_not_allowed') {
      await showWaitlistDialog()
      return
    }
    error.value = resolveApiErrorMessage(e, t('auth.sendFailed'))
  } finally {
    codeSending.value = false
  }
}

async function handleCodeSubmit() {
  if (!canSubmitCode.value || loading.value) return
  if (!isEmailInput(codeForm.value.account)) {
    error.value = t('auth.codeEmailOnly')
    return
  }
  if (isEE.value && isNonWhitelistedEmail(codeForm.value.account)) {
    await showWaitlistDialog()
    return
  }
  loading.value = true
  try {
    await authStore.verificationCodeLogin(codeForm.value.account, codeForm.value.code)
    error.value = ''
    router.replace('/')
  } catch (e: any) {
    const detail = e?.response?.data?.detail
    if (isEE.value && detail?.message_key === 'errors.auth.email_domain_not_allowed') {
      await showWaitlistDialog()
      return
    }
    error.value = resolveApiErrorMessage(e, t('auth.loginFailed'))
  } finally {
    loading.value = false
  }
}

const WAITLIST_URL = 'https://nodeskai.feishu.cn/share/base/form/shrcnKfwXbiUOenm73jlpElu1hg'

function isNonWhitelistedEmail(input: string): boolean {
  if (!input.includes('@')) return false
  const domain = input.split('@').pop()?.toLowerCase()
  return domain !== 'nodeskai.com'
}

async function showWaitlistDialog() {
  const confirmed = await confirm({
    title: t('auth.waitlist.title'),
    description: t('auth.waitlist.description'),
    confirmText: t('auth.waitlist.joinButton'),
    cancelText: t('auth.waitlist.cancelButton'),
  })
  if (confirmed) {
    window.open(WAITLIST_URL, '_blank')
  }
}

function onLocaleChange(value: string) {
  locale.value = setCurrentLocale(value)
}

watch(activeTab, () => { error.value = '' })

</script>

<template>
  <div class="min-h-screen flex">
    <!-- 左侧品牌区 -->
    <div class="hidden lg:flex lg:w-[55%] relative overflow-hidden bg-linear-to-br from-primary/20 via-background to-background">
      <!-- 背景装饰层 -->
      <div class="absolute inset-0">
        <!-- 网格线 -->
        <div class="absolute inset-0 brand-grid opacity-[0.04]" />
        <!-- 浮动光晕 -->
        <div class="absolute top-[15%] left-[20%] w-[500px] h-[500px] rounded-full bg-primary/6 blur-[100px] brand-float" />
        <div class="absolute bottom-[10%] right-[15%] w-[400px] h-[400px] rounded-full bg-primary/8 blur-[80px] brand-float-reverse" />
        <!-- 脉冲光点 -->
        <div class="absolute top-[20%] right-[30%] w-1.5 h-1.5 rounded-full bg-primary/60 brand-pulse-dot" />
        <div class="absolute top-[55%] left-[12%] w-1 h-1 rounded-full bg-primary/40 brand-pulse-dot" style="animation-delay: 1.5s" />
        <div class="absolute bottom-[25%] right-[20%] w-1 h-1 rounded-full bg-primary/50 brand-pulse-dot" style="animation-delay: 3s" />
        <div class="absolute top-[40%] left-[45%] w-0.5 h-0.5 rounded-full bg-primary/30 brand-pulse-dot" style="animation-delay: 4.5s" />
        <!-- 扫光 -->
        <div class="absolute inset-0 overflow-hidden">
          <div class="absolute top-0 left-0 w-[200%] h-px bg-linear-to-r from-transparent via-primary/20 to-transparent brand-sweep" />
        </div>
      </div>

      <!-- 内容区 -->
      <div class="relative z-10 flex flex-col justify-between px-12 xl:px-20 py-12">
        <!-- Logo -->
        <div class="flex items-center gap-3">
          <img src="/logo.png" alt="DeskClaw" class="w-10 h-10" />
          <span class="text-xl font-bold tracking-tight">DeskClaw</span>
          <span class="px-1.5 py-0.5 text-[10px] font-semibold leading-none rounded bg-primary/15 text-primary">Beta</span>
        </div>

        <!-- 主体 -->
        <div>
          <h1 class="text-4xl xl:text-5xl font-bold leading-tight mb-5">
            {{ t('auth.landing.headline1') }}<br />
            <span class="text-primary">{{ t('auth.landing.headline2') }}</span>
          </h1>
          <p class="text-base text-muted-foreground max-w-lg mb-10 leading-relaxed">
            {{ t('auth.landing.subtitle') }}
          </p>

          <!-- 主题卡片 -->
          <div class="space-y-3 max-w-lg">
            <div
              v-for="tm in themes"
              :key="tm.key"
              class="flex items-start gap-4 p-4 rounded-xl bg-card/30 backdrop-blur-sm border border-border/40 transition-all hover:border-primary/30 hover:bg-card/50 group"
            >
              <div class="shrink-0 w-9 h-9 rounded-lg bg-primary/10 flex items-center justify-center group-hover:bg-primary/15 transition-colors">
                <component :is="tm.icon" class="w-[18px] h-[18px] text-primary" :stroke-width="1.5" />
              </div>
              <div class="min-w-0">
                <div class="text-sm font-semibold mb-0.5">{{ t(`auth.landing.themes.${tm.key}.title`) }}</div>
                <div class="text-xs text-muted-foreground leading-relaxed">{{ t(`auth.landing.themes.${tm.key}.desc`) }}</div>
              </div>
            </div>
          </div>
        </div>

        <!-- Stats 行 -->
        <div class="flex items-center justify-center max-w-lg">
          <div class="flex-1 text-center">
            <div class="text-2xl font-bold text-primary">{{ t('auth.landing.stats.alwaysOn') }}</div>
            <div class="text-xs text-muted-foreground mt-1">{{ t('auth.landing.stats.alwaysOnLabel') }}</div>
          </div>
          <div class="w-px h-8 bg-border/60" />
          <div class="flex-1 text-center">
            <div class="text-2xl font-bold text-primary">{{ t('auth.landing.stats.evolution') }}</div>
            <div class="text-xs text-muted-foreground mt-1">{{ t('auth.landing.stats.evolutionLabel') }}</div>
          </div>
          <div class="w-px h-8 bg-border/60" />
          <div class="flex-1 text-center">
            <div class="text-2xl font-bold text-primary">{{ t('auth.landing.stats.efficiency') }}</div>
            <div class="text-xs text-muted-foreground mt-1">{{ t('auth.landing.stats.efficiencyLabel') }}</div>
          </div>
        </div>
      </div>
    </div>

    <!-- 右侧登录区 -->
    <div class="flex-1 flex items-center justify-center px-6">
      <div class="w-full max-w-sm space-y-6">
        <div class="flex justify-end">
          <LocaleSelect :model-value="locale" @update:model-value="onLocaleChange" />
        </div>
        <!-- 移动端 Logo -->
        <div class="flex flex-col items-center gap-3 lg:hidden">
          <img src="/logo.png" alt="DeskClaw" class="w-12 h-12" />
          <div class="flex items-center gap-2">
            <span class="text-xl font-bold">DeskClaw</span>
            <span class="px-1.5 py-0.5 text-[10px] font-semibold leading-none rounded bg-primary/15 text-primary">Beta</span>
          </div>
        </div>

        <!-- 标题 -->
        <div class="space-y-1 text-center lg:text-left">
          <h2 class="text-2xl font-bold">{{ t('auth.welcomeBack') }}</h2>
          <p class="text-sm text-muted-foreground">
            {{ t('auth.loginSubtitle') }}
          </p>
        </div>

          <!-- Tab 切换 -->
          <div class="flex rounded-lg bg-muted p-1 gap-1">
            <button
              class="flex-1 flex items-center justify-center gap-1.5 py-2 px-3 rounded-md text-sm font-medium transition-all"
              :class="activeTab === 'account' ? 'bg-background text-foreground shadow-sm' : 'text-muted-foreground hover:text-foreground'"
              @click="activeTab = 'account'"
            >
              <KeyRound class="w-4 h-4" />
              {{ t('auth.accountPasswordLogin') }}
            </button>
            <button
              class="flex-1 flex items-center justify-center gap-1.5 py-2 px-3 rounded-md text-sm font-medium transition-all"
              :class="activeTab === 'code' ? 'bg-background text-foreground shadow-sm' : 'text-muted-foreground hover:text-foreground'"
              @click="activeTab = 'code'"
            >
              <MessageSquareCode class="w-4 h-4" />
              {{ t('auth.emailCodeLogin') }}
            </button>
          </div>

          <!-- 账号密码表单 -->
          <form v-if="activeTab === 'account'" class="space-y-4" @submit.prevent="handleAccountSubmit">
            <div class="space-y-1.5">
              <label class="text-sm font-medium text-foreground">{{ t('auth.accountLabel') }}</label>
              <input
                v-model="accountForm.account"
                type="text"
                :placeholder="t('auth.accountLoginPlaceholder')"
                required
                class="w-full h-10 px-3 rounded-lg border border-input bg-background text-sm placeholder:text-muted-foreground focus:outline-none focus:ring-2 focus:ring-ring focus:ring-offset-1 transition-shadow"
              />
            </div>

            <div class="space-y-1.5">
              <label class="text-sm font-medium text-foreground">{{ t('auth.passwordLabel') }}</label>
              <div class="relative">
                <input
                  v-model="accountForm.password"
                  :type="showPassword ? 'text' : 'password'"
                  :placeholder="t('auth.passwordPlaceholder')"
                  required
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
            </div>

            <button
              type="submit"
              :disabled="!canSubmitAccount || loading"
              class="w-full h-10 rounded-lg bg-primary text-primary-foreground font-medium text-sm hover:bg-primary/90 transition-all hover:shadow-lg hover:shadow-primary/20 disabled:opacity-50 disabled:cursor-not-allowed flex items-center justify-center gap-2"
            >
              <Loader2 v-if="loading" class="w-4 h-4 animate-spin" />
              {{ t('auth.login') }}
            </button>

          </form>

          <!-- 验证码表单 -->
          <form v-if="activeTab === 'code'" class="space-y-4" @submit.prevent="handleCodeSubmit">
            <div class="space-y-1.5">
              <label class="text-sm font-medium text-foreground">{{ t('auth.emailLabel') }}</label>
              <input
                v-model="codeForm.account"
                type="email"
                inputmode="email"
                :placeholder="t('auth.emailPlaceholder')"
                required
                class="w-full h-10 px-3 rounded-lg border border-input bg-background text-sm placeholder:text-muted-foreground focus:outline-none focus:ring-2 focus:ring-ring focus:ring-offset-1 transition-shadow"
              />
              <p class="text-xs text-muted-foreground">{{ t('auth.codeLoginHint') }}</p>
            </div>

            <div class="space-y-1.5">
              <label class="text-sm font-medium text-foreground">{{ t('auth.codeLabel') }}</label>
              <div class="flex gap-2">
                <input
                  v-model="codeForm.code"
                  type="text"
                  inputmode="numeric"
                  maxlength="6"
                  :placeholder="t('auth.codePlaceholder')"
                  required
                  class="flex-1 h-10 px-3 rounded-lg border border-input bg-background text-sm placeholder:text-muted-foreground focus:outline-none focus:ring-2 focus:ring-ring focus:ring-offset-1 transition-shadow"
                />
                <button
                  type="button"
                  :disabled="!isEmailInput(codeForm.account) || codeSending || codeCountdown > 0"
                  class="shrink-0 h-10 px-4 rounded-lg border border-input text-sm font-medium hover:bg-accent transition-colors disabled:opacity-50 disabled:cursor-not-allowed whitespace-nowrap"
                  @click="handleSendCode"
                >
                  <Loader2 v-if="codeSending" class="w-4 h-4 animate-spin" />
                  <template v-else-if="codeCountdown > 0">{{ codeCountdown }}s</template>
                  <template v-else>{{ t('auth.sendCode') }}</template>
                </button>
              </div>
            </div>

            <button
              type="submit"
              :disabled="!canSubmitCode || loading"
              class="w-full h-10 rounded-lg bg-primary text-primary-foreground font-medium text-sm hover:bg-primary/90 transition-all hover:shadow-lg hover:shadow-primary/20 disabled:opacity-50 disabled:cursor-not-allowed flex items-center justify-center gap-2"
            >
              <Loader2 v-if="loading" class="w-4 h-4 animate-spin" />
              {{ t('auth.login') }}
            </button>

          </form>

          <!-- 错误提示 -->
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

          <!-- 注册入口 -->
          <p class="text-center text-sm text-muted-foreground">
            {{ t('auth.noAccount') }}
            <router-link to="/register" class="text-primary font-medium hover:underline ml-1">
              {{ t('auth.register') }}
            </router-link>
          </p>

        <!-- Waitlist 入口 (EE-only) -->
        <a
          v-if="isEE"
          :href="WAITLIST_URL"
          target="_blank"
          class="block rounded-lg border border-primary/20 bg-primary/5 px-4 py-3 text-center transition-all hover:bg-primary/10 hover:border-primary/40 hover:shadow-md hover:shadow-primary/5 group"
        >
          <p class="text-sm font-medium text-foreground">{{ t('auth.waitlist.bannerTitle') }}</p>
          <p class="text-xs text-muted-foreground mt-0.5 flex items-center justify-center gap-1">
            {{ t('auth.waitlist.bannerAction') }}
            <ExternalLink class="w-3 h-3 transition-transform group-hover:translate-x-0.5" />
          </p>
        </a>

        <!-- 底部 -->
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

.brand-pulse-dot {
  animation: brand-pulse-dot 4s ease-in-out infinite;
}

.brand-sweep {
  animation: brand-sweep 10s linear infinite;
}

@keyframes brand-float {
  0%, 100% { transform: translate(0, 0); }
  50% { transform: translate(10px, -15px); }
}

@keyframes brand-pulse-dot {
  0%, 100% { opacity: 0.3; transform: scale(1); }
  50% { opacity: 0.8; transform: scale(1.5); }
}

@keyframes brand-sweep {
  0% { transform: translateX(-100%) rotate(-45deg); }
  100% { transform: translateX(200%) rotate(-45deg); }
}
</style>
