import type { SequencePitch } from './sequence'

export type DemoRequest = {
  pitcher_id: string; batter_id: string
  state: { balls: number; strikes: number; outs: number; bases: boolean[] }
  sequence: SequencePitch[]
}
export type DemoCase<T> = {
  id: string; title: string; description: string; request: DemoRequest; response: T
  pitcher_name?: string; batter_name?: string
}
export type DemoBundle<T> = {
  model_version: string; data_version: string; data_cutoff: string; bundle_sha256: string
  cases: DemoCase<T>[]; [key: string]: unknown
}

/** Fixed cases cannot be mixed with another model or silently accept an empty asset. */
export function validateDemo<T>(value: unknown): DemoBundle<T> {
  const bundle = value as DemoBundle<T>
  if (!bundle || typeof bundle.model_version !== 'string' || typeof bundle.data_version !== 'string'
    || typeof bundle.data_cutoff !== 'string' || !/^[a-f0-9]{64}$/.test(bundle.bundle_sha256)
    || !Array.isArray(bundle.cases) || bundle.cases.length === 0) throw new Error('固定案例檔案不完整，請重新載入網站。')
  const ids = new Set<string>()
  for (const item of bundle.cases) {
    const response = item.response as Record<string, unknown>
    if (!item.id || ids.has(item.id) || !item.title || !item.request?.state || !Array.isArray(item.request.sequence)
      || !response || response.model_version !== bundle.model_version || response.data_version !== bundle.data_version
      || response.data_cutoff !== bundle.data_cutoff || !Array.isArray(response.pitch_probabilities)
      || !Array.isArray(response.zone_probabilities) || !Array.isArray(response.recommendations)) {
      throw new Error('固定案例與模型版本不一致，請重新載入網站。')
    }
    ids.add(item.id)
  }
  return bundle
}
