
const WS_ORIGIN = import.meta.env.VITE_WS_ORIGIN ?? "ws://localhost:8000"

export function buildWsUrl(docId: string, ticket: string): string {
  const params = new URLSearchParams({ doc: docId, ticket })
  return `${WS_ORIGIN}/ws?${params.toString()}`
}
