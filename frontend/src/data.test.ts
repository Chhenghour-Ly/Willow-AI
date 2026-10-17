import { describe, expect, it } from 'vitest'
import { money, preview, relativeTime, SAMPLE, showValue } from './data'

describe('data helpers', () => {
  it('formats money', () => {
    expect([money(500), money(20000), money(2_000_000), money(1_500_000)]).toEqual(['$500', '$20k', '$2M', '$1.5M'])
  })
  it('formats relative time', () => {
    const now = new Date(2026, 9, 17, 15, 0)
    const at = (d: Date) => d.getTime() / 1000
    expect(relativeTime(at(new Date(2026, 9, 16, 9, 0)), now)).toBe('Yesterday')
    expect(relativeTime(at(new Date(2026, 8, 2, 9, 0)), now)).toBe('Sep 2')
  })
  it('shows missing profile values as null', () => {
    expect(showValue('crops', [])).toBeNull()
    expect(showValue('has_crop_insurance', false)).toBe('No')
    expect(showValue('annual_income', 180000)).toBe('$180,000')
  })
  it('writes previews per status', () => {
    const m = SAMPLE.matches[0]
    expect(preview(m, 'submitted')).toMatch(/^Sent/)
    expect(preview({ ...m, unknown: ['a', 'b'] }, 'possible')).toBe('You may qualify. 2 questions left.')
  })
})
