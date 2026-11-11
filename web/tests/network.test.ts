import test from 'node:test'
import assert from 'node:assert/strict'
import { fetchJson } from '../src/network.ts'

test('bounded request aborts a stalled response with a visible timeout', async () => {
  const original = globalThis.fetch
  globalThis.fetch = (_url, options) => new Promise((_resolve, reject) => options?.signal?.addEventListener('abort', () => reject(new DOMException('Aborted', 'AbortError'))))
  try { await assert.rejects(fetchJson('/stalled', {}, 5), /超過時限/) } finally { globalThis.fetch = original }
})

test('caller cancellation remains cancellation so stale inputs cannot show errors', async () => {
  const original = globalThis.fetch
  globalThis.fetch = (_url, options) => new Promise((_resolve, reject) => options?.signal?.addEventListener('abort', () => reject(new DOMException('Aborted', 'AbortError'))))
  const caller = new AbortController()
  try {
    const request = fetchJson('/cancelled', { signal: caller.signal }, 1000)
    caller.abort()
    await assert.rejects(request, { name: 'AbortError' })
  } finally { globalThis.fetch = original }
})

test('service status is preserved without requiring a JSON error body', async () => {
  const original = globalThis.fetch
  globalThis.fetch = async () => new Response('unavailable', { status: 503 })
  try { await assert.rejects(fetchJson('/unavailable'), /503/) } finally { globalThis.fetch = original }
})
