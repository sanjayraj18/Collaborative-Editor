import { useEffect, useRef, useState } from "react"
import { useMutation, useQuery } from "@tanstack/react-query"
import { redirect, useParams, type LoaderFunctionArgs } from "react-router-dom"

import { documentService } from "@/services/DocumentService"
import { authService } from "@/services/AuthService"
import { useProvider } from "@/collab/useProvider"
import { buildWsUrl } from "@/collab/url"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { CodeEditor } from "@/collab/CodeEditor"
import { ConnectionStatus } from "@/components/ConnectionStatus"

const RECONNECT_BASE_DELAY_MS = 1000
const RECONNECT_MAX_DELAY_MS = 15000
const MAX_RECONNECT_ATTEMPTS = 8

export async function loader({ request }: LoaderFunctionArgs) {
  try {
    await authService.me()
  } catch {
    const { pathname, search } = new URL(request.url)
    throw redirect(`/?next=${encodeURIComponent(pathname + search)}`)
  }
  return null
}

export const Component = () => {
  const { docId } = useParams<{ docId: string }>()
  const [wsUrl, setWsUrl] = useState<string | null>(null)

  const docQuery = useQuery({
    queryKey: ["doc", docId],
    queryFn: () => documentService.get(docId!),
    enabled: !!docId,
  })

  const ticketMutation = useMutation({
    mutationFn: () => documentService.mintTicket(docId!),
    onSuccess: (data) => {
      setWsUrl(buildWsUrl(docId!, data.ticket))
    },
  })

  useEffect(() => {
    if (docQuery.isSuccess && docId) {
      ticketMutation.mutate()
    }
    
  }, [docQuery.isSuccess, docId])

  const { doc: yDoc, connectionState, role, provider } = useProvider(wsUrl, docId ?? null)

  useEffect(() => {
    console.log("connection state:", connectionState)
  }, [connectionState])

 
  useEffect(() => {
    if (connectionState !== "live" || !provider) return
    provider.awareness.setLocalState({
      name: `User ${Math.floor(Math.random() * 1000)}`,
      color: `hsl(${Math.floor(Math.random() * 360)}, 70%, 50%)`,
    })
  }, [connectionState, provider])

  useEffect(() => {
    if (!yDoc) return
    ;(window as unknown as { __ydoc: typeof yDoc }).__ydoc = yDoc
  }, [yDoc])

  
  const reconnectAttemptRef = useRef(0)
  const [reconnectAttempt, setReconnectAttempt] = useState(0)

  useEffect(() => {
    if (connectionState === "live") {
      reconnectAttemptRef.current = 0
      setReconnectAttempt(0)
      return
    }

    if (connectionState !== "offline") return
    if (reconnectAttemptRef.current >= MAX_RECONNECT_ATTEMPTS) return

    const attempt = reconnectAttemptRef.current
    const delay = Math.min(RECONNECT_BASE_DELAY_MS * 2 ** attempt, RECONNECT_MAX_DELAY_MS)
    const jitter = delay * 0.2 * (Math.random() * 2 - 1)

    const timer = setTimeout(() => {
      reconnectAttemptRef.current += 1
      setReconnectAttempt(reconnectAttemptRef.current)
      ticketMutation.mutate()
    }, delay + jitter)

    return () => clearTimeout(timer)
  }, [connectionState])

  function handleManualRetry() {
    reconnectAttemptRef.current = 0
    setReconnectAttempt(0)
    ticketMutation.mutate()
  }

  if (docQuery.isPending) {
    return <div className="p-8 text-muted-foreground">Loading…</div>
  }

  if (docQuery.isError) {
    return (
      <div className="p-8 text-destructive">
        Couldn't load document: {docQuery.error.message}
      </div>
    )
  }

  const doc = docQuery.data

  return (
    <div className="mx-auto max-w-2xl p-8">
      <Card>
        <CardHeader>
          <CardTitle className="flex items-center justify-between text-base">
            <span>{doc.title}</span>
            <span className="flex items-center gap-2 text-xs font-normal text-muted-foreground">
              <span>{doc.role}</span>
              {doc.visibility === "link" && <span>· link-shared</span>}
              <ConnectionStatus
                state={connectionState}
                reconnectAttempt={reconnectAttempt}
                onRetry={handleManualRetry}
              />
            </span>
          </CardTitle>
        </CardHeader>
        <CardContent>
          {ticketMutation.isError && (
            <p className="text-sm text-destructive">
              Couldn't connect: {ticketMutation.error.message}
            </p>
          )}
          {connectionState === "live" && yDoc && provider ? (
            <CodeEditor
              doc={yDoc}
              awareness={provider.awareness}
              editable={role === "writer"}
            />
          ) : (
            <p className="text-sm text-muted-foreground">Connecting…</p>
          )}
        </CardContent>
      </Card>
    </div>
  )
}

export function HydrateFallback() {
  return <div className="p-8 text-muted-foreground">Loading…</div>
}
