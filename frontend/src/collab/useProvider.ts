import { useEffect, useRef, useState } from "react"
import type * as Y from "yjs"

import { CollabProvider, type ConnectionState } from "./provider"

interface UseProviderResult {
  doc: Y.Doc | null
  connectionState: ConnectionState
  role: string | null
  provider: CollabProvider | null
}

export function useProvider(url: string | null, docId: string | null): UseProviderResult {
  const [provider, setProvider] = useState<CollabProvider | null>(null)
  const [connectionState, setConnectionState] = useState<ConnectionState>("connecting")

  
  const lastSeqRef = useRef<bigint | null>(null)
  const lastDocIdRef = useRef<string | null>(null)

  useEffect(() => {
    if (!url) {
      setProvider(null)
      return
    }


    if (docId !== lastDocIdRef.current) {
      lastSeqRef.current = null
      lastDocIdRef.current = docId
    }

    const instance = new CollabProvider({
      url,
      initialLastSeq: lastSeqRef.current,
      onStateChange: setConnectionState,
    })
    setProvider(instance)
    instance.connect()

    return () => {
      
      lastSeqRef.current = instance.lastSeq
      instance.disconnect()
    }
  }, [url, docId])

  return {
    doc: provider?.doc ?? null,
    connectionState,
    role: provider?.documentRole ?? null,
    provider,
  }
}
