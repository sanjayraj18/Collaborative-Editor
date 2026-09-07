import { useEffect, useState } from "react"
import type * as Y from "yjs"

import { CollabProvider, type ConnectionState } from "./provider"

interface UseProviderResult {
  doc: Y.Doc | null
  connectionState: ConnectionState
  role: string | null
  provider: CollabProvider | null
}

export function useProvider(url: string | null): UseProviderResult {
  const [provider, setProvider] = useState<CollabProvider | null>(null)
  const [connectionState, setConnectionState] = useState<ConnectionState>("connecting")

  useEffect(() => {
    if (!url) {
      setProvider(null)
      return
    }

    const instance = new CollabProvider({
      url,
      onStateChange: setConnectionState,
    })
    setProvider(instance)
    instance.connect()

    return () => {
      instance.disconnect()
    }
  }, [url])

  return {
    doc: provider?.doc ?? null,
    connectionState,
    role: provider?.documentRole ?? null,
    provider,
  }
}