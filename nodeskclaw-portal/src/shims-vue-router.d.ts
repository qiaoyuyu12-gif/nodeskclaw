// vue-router 类型增强:为路由 meta 增加 requireSuperAdmin 字段。
// 关键:本文件带顶层 import,因此是「模块」而非「全局脚本」,
// declare module 在此为「模块增强」(与原类型合并);
// 若放在无 import/export 的全局脚本里,会被 TS 当成整体替换 vue-router 的
// 环境声明,导致 useRouter/createRouter/RouteRecordRaw 等真实导出全部失效。
import 'vue-router'

declare module 'vue-router' {
  interface RouteMeta {
    requireSuperAdmin?: boolean
  }
}
