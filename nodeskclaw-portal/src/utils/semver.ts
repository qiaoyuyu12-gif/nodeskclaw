// nodeskclaw-portal/src/utils/semver.ts
/**
 * 语义化版本号解析与比较工具，只认 "X.Y.Z" 格式，逻辑跟后端
 * app/core/version_compare.py 保持一致。
 */

const SEMVER_RE = /^(\d+)\.(\d+)\.(\d+)$/

export function parseVersion(version: string): [number, number, number] | null {
  const match = SEMVER_RE.exec(version.trim())
  if (!match) return null
  return [Number(match[1]), Number(match[2]), Number(match[3])]
}

export function compareVersions(a: string, b: string): number | null {
  const parsedA = parseVersion(a)
  const parsedB = parseVersion(b)
  if (!parsedA || !parsedB) return null
  for (let i = 0; i < 3; i++) {
    if (parsedA[i] !== parsedB[i]) return parsedA[i] > parsedB[i] ? 1 : -1
  }
  return 0
}

/** 在当前版本号基础上建议下一个 patch 版本，解析失败时原样返回，不瞎猜。 */
export function suggestNextPatch(version: string): string {
  const parsed = parseVersion(version)
  if (!parsed) return version
  const [major, minor, patch] = parsed
  return `${major}.${minor}.${patch + 1}`
}
