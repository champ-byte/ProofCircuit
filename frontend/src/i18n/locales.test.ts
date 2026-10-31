import { describe, expect, it } from 'vitest'
import { LANGUAGES, resources } from '.'

type Tree = { [key: string]: unknown }

function flatten(tree: Tree, prefix = ''): Map<string, unknown> {
  const out = new Map<string, unknown>()
  for (const [key, value] of Object.entries(tree)) {
    const path = prefix ? `${prefix}.${key}` : key
    if (value && typeof value === 'object' && !Array.isArray(value)) {
      for (const [k, v] of flatten(value as Tree, path)) out.set(k, v)
    } else {
      out.set(path, value)
    }
  }
  return out
}

const placeholders = (value: unknown) =>
  [...String(value).matchAll(/\{\{(\w+)\}\}/g)].map((m) => m[1]).sort()

const english = flatten(resources.en as Tree)

/** Every language but English is partial: new strings are English-only until a translation pass; missing keys show English. */
const PARTIAL = new Set<string>(['hi', 'mr', 'bn', 'gu', 'kn', 'ml', 'pa', 'ta', 'te'])

describe('locale files', () => {
  it('registers ten languages', () => {
    expect(LANGUAGES.map((l) => l.code).sort()).toEqual(Object.keys(resources).sort())
    expect(LANGUAGES).toHaveLength(10)
  })

  for (const { code } of LANGUAGES) {
    const partial = PARTIAL.has(code)
    it(`${code} has ${partial ? 'no unknown keys (partial: falls back to English)' : 'exactly the English keys'} and matching placeholders`, () => {
      const locale = flatten(resources[code] as Tree)
      expect([...locale.keys()].filter((k) => !english.has(k))).toEqual([])
      if (!partial) expect([...english.keys()].filter((k) => !locale.has(k))).toEqual([])
      for (const [key, value] of english) {
        if (!locale.has(key)) continue
        const other = locale.get(key)
        if (Array.isArray(value)) {
          expect(Array.isArray(other) && other.length, key).toBe(value.length)
        } else {
          expect(placeholders(other), key).toEqual(placeholders(value))
        }
      }
    })
  }
})
