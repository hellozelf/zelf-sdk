import assert from 'node:assert/strict'
import { test } from 'node:test'
import { readFileSync } from 'node:fs'

import type {
  AdvancedAiAnalysisReport,
  AiAnalysisReport,
  CreatorVettingReport,
} from '../dist/index.js'

const FIXTURES = JSON.parse(
  readFileSync(new URL('../../fixtures/fixtures.json', import.meta.url), 'utf8'),
) as { reports: Record<string, Record<string, unknown>> }

// The report types promise nothing is present, so every one of these compiles.
const empty: [AdvancedAiAnalysisReport, AiAnalysisReport, CreatorVettingReport] = [{}, {}, {}]

test('every malformed report case parses and keeps its values', () => {
  for (const [name, cases] of Object.entries(FIXTURES.reports)) {
    for (const [kind, document] of Object.entries(cases)) {
      assert.deepEqual(JSON.parse(JSON.stringify(document)), document, `${name}.${kind}`)
    }
  }
  assert.equal(empty.length, 3)
})

test('a decimal in a whole number field is kept', () => {
  const report = FIXTURES.reports.AdvancedAiAnalysisReport!.decimals as AdvancedAiAnalysisReport
  assert.equal(report.summary?.videos, 12.6)
})

test('missing and null fields read as nothing', () => {
  const report = JSON.parse('{"violations": null}') as CreatorVettingReport
  assert.equal(report.profile_summary, undefined)
  assert.equal(report.violations, null)
})
