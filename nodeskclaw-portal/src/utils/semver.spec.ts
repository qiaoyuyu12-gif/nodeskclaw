// nodeskclaw-portal/src/utils/semver.spec.ts
import { describe, it, expect } from 'vitest'
import { parseVersion, compareVersions, suggestNextPatch } from './semver'

describe('semver', () => {
  it('parses a valid X.Y.Z version', () => {
    expect(parseVersion('1.10.2')).toEqual([1, 10, 2])
  })

  it('returns null for invalid formats', () => {
    expect(parseVersion('latest')).toBeNull()
    expect(parseVersion('v1.0.0')).toBeNull()
    expect(parseVersion('1.0')).toBeNull()
  })

  it('compares numerically, not lexicographically', () => {
    expect(compareVersions('1.10.0', '1.9.0')).toBe(1)
    expect(compareVersions('1.9.0', '1.10.0')).toBe(-1)
  })

  it('treats equal versions as 0', () => {
    expect(compareVersions('1.0.0', '1.0.0')).toBe(0)
  })

  it('returns null when either version is invalid', () => {
    expect(compareVersions('bad', '1.0.0')).toBeNull()
    expect(compareVersions('1.0.0', 'bad')).toBeNull()
  })

  it('suggests the next patch version', () => {
    expect(suggestNextPatch('1.0.0')).toBe('1.0.1')
    expect(suggestNextPatch('2.3.9')).toBe('2.3.10')
  })

  it('suggestNextPatch falls back to the input when unparseable', () => {
    expect(suggestNextPatch('latest')).toBe('latest')
  })
})
