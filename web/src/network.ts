/** Bounded requests, with cancellation shared by the page's current input. */
export async function fetchJson<T>(url: string, options: RequestInit = {}, timeoutMs = 65000): Promise<T> {
  const controller = new AbortController()
  let timedOut = false
  const abort = () => controller.abort()
  if (options.signal?.aborted) controller.abort()
  options.signal?.addEventListener('abort', abort, { once: true })
  const timer = setTimeout(() => { timedOut = true; controller.abort() }, timeoutMs)
  try {
    const response = await fetch(url, { ...options, signal: controller.signal })
    if (!response.ok) {
      const body = await response.json().catch(() => ({}))
      const detail = body.detail
      throw new Error((typeof detail === 'string' ? detail : detail?.message) || `服務回應 ${response.status}，請稍後重試。`)
    }
    return await response.json()
  } catch (error) {
    if (timedOut) throw new Error('連線等待已超過時限，請重新連線，或切換固定示範案例。')
    throw error
  } finally {
    clearTimeout(timer)
    options.signal?.removeEventListener('abort', abort)
  }
}
