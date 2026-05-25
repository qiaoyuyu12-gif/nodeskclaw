/// <reference types="vite/client" />
declare const __APP_VERSION__: string

declare module 'vue-router' {
  interface RouteMeta {
    requireSuperAdmin?: boolean
  }
}
