import { useEffect, useState } from "react"
import { useMutation, useQuery } from "@tanstack/react-query"
import { useParams } from "react-router-dom"

import { documentService } from "@/services/DocumentService"
import { useProvider } from "@/collab/useProvider"
import { buildWsUrl } from "@/collab/url"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"

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

  const { doc: yDoc, connectionState, role } = useProvider(wsUrl)

  useEffect(() => {
    console.log("connection state:", connectionState)
  }, [connectionState])

  useEffect(() => {
    if (!yDoc) return
    ;(window as unknown as { __ydoc: typeof yDoc }).__ydoc = yDoc
  }, [yDoc])

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
              <span className="font-mono">· {connectionState}</span>
            </span>
          </CardTitle>
        </CardHeader>
        <CardContent>
          {ticketMutation.isError && (
            <p className="text-sm text-destructive">
              Couldn't connect: {ticketMutation.error.message}
            </p>
          )}
          {connectionState === "live" ? (
            <p className="text-sm text-muted-foreground">
              Connected as {role}. Editor arrives in Milestone 3 — for now, the
              console: <code className="font-mono">__ydoc.getText("content")</code>
            </p>
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