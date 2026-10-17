import { describe, expect, it } from 'vitest'
import { fromApi, money, preview, relativeTime, SAMPLE, showValue, type ApiMatch } from './data'

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
    expect(showValue('land_control', 'leased')).toBe('Lease')
    expect(showValue('assistance_needed_usd', 18000)).toBe('$18,000')
  })
  it('writes previews per status', () => {
    const m = SAMPLE.matches[0]
    expect(preview(m, 'submitted')).toMatch(/^You approved/)
    expect(preview({ ...m, unknown: ['a', 'b'] }, 'possible')).toBe('You may qualify. 2 questions left.')
  })
  it('maps backend matches to app matches', () => {
    const api: ApiMatch = {
      program_id: 'eqip', program_name: 'EQIP', agency: 'NRCS', description: 'Cost share', repayable: false,
      fit_status: 'needs_information', reasons: [{ text: 'Irrigation' }], obstacles: [], missing_requirements: [{ text: 'Land control' }],
      application_deadline: { date: '2026-11-06' }, official_source_urls: [{ title: '7 CFR 1466', url: 'https://ecfr.gov' }],
      next_action: 'Call your county office', relevance: 1.2,
    }
    expect(fromApi(api)).toMatchObject({
      status: 'possible', kind: 'grant', met: ['Irrigation'], unknown: ['Land control'], deadline: '2026-11-06',
      sources: [{ title: '7 CFR 1466', url: 'https://ecfr.gov' }],
    })
  })
})
