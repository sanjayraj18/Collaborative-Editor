import { useState } from "react"
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { redirect, useNavigate, type LoaderFunctionArgs } from "react-router-dom"

import { documentService } from "@/services/DocumentService"
import { authService } from "@/services/AuthService"
import type { DocumentResponse } from "@/services/types/Document"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { DocumentCard } from "../components/DocumentCard"
import { ShareDialog } from "@/components/ShareDialog"

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
  const [title, setTitle] = useState("")
  const [sharingDocId, setSharingDocId] = useState<string | null>(null)
  const navigate = useNavigate()
  const queryClient = useQueryClient()

  const docsQuery = useQuery({
    queryKey: ["docs"],
    queryFn: () => documentService.list(),
  })

  const createMutation = useMutation({
    mutationFn: () => documentService.create(title),
    onSuccess: (doc) => {
      setTitle("")
      queryClient.invalidateQueries({ queryKey: ["docs"] })
      navigate(`/docs/${doc.id}`)
    },
  })

  async function handleSignOut() {
    await authService.signout()
    navigate("/")
  }

  function handleCreate(e: React.FormEvent) {
    e.preventDefault()
    if (title.trim()) createMutation.mutate()
  }

  if (docsQuery.isPending) {
    return <div className="p-8 text-muted-foreground">Loading…</div>
  }

  if (docsQuery.isError) {
    return (
      <div className="p-8 text-destructive">
        Couldn't load documents: {docsQuery.error.message}
      </div>
    )
  }

  const sharingDoc = docsQuery.data.find((d) => d.id === sharingDocId) ?? null

  return (
    <div className="mx-auto max-w-2xl p-8">
      <div className="mb-6 flex items-center justify-between">
        <h1 className="text-2xl font-semibold">Your documents</h1>
        <Button variant="outline" onClick={handleSignOut}>
          Sign out
        </Button>
      </div>

      <form onSubmit={handleCreate} className="mb-8 flex gap-2">
        <Input
          value={title}
          onChange={(e) => setTitle(e.target.value)}
          placeholder="New document title"
          maxLength={100}
        />
        <Button type="submit" disabled={createMutation.isPending || !title.trim()}>
          {createMutation.isPending ? "Creating…" : "Create"}
        </Button>
      </form>

      {docsQuery.data.length === 0 ? (
        <p className="text-muted-foreground">No documents yet — create one above.</p>
      ) : (
        <div className="flex flex-col gap-3">
          {docsQuery.data.map((doc: DocumentResponse) => (
            <DocumentCard
              key={doc.id}
              doc={doc}
              onClick={() => navigate(`/docs/${doc.id}`)}
              onShare={() => setSharingDocId(doc.id)}
            />
          ))}
        </div>
      )}

      {sharingDoc && (
        <ShareDialog
          doc={sharingDoc}
          open={sharingDocId !== null}
          onOpenChange={(open) => {
            if (!open) setSharingDocId(null)
          }}
        />
      )}
    </div>
  )
}

export function HydrateFallback() {
  return <div className="p-8 text-muted-foreground">Loading…</div>
}
