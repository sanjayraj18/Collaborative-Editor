import { useState } from "react"
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"

import { documentService } from "@/services/DocumentService"
import type { DocumentResponse } from "@/services/types/Document"
import { Button } from "@/components/ui/button"
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog"
import { Input } from "@/components/ui/input"
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select"

interface ShareDialogProps {
  doc: DocumentResponse
  open: boolean
  onOpenChange: (open: boolean) => void
}

export function ShareDialog({ doc, open, onOpenChange }: ShareDialogProps) {
  const queryClient = useQueryClient()
  const [email, setEmail] = useState("")
  const [role, setRole] = useState<"reader" | "writer">("writer")
  const [copied, setCopied] = useState(false)

  const shareUrl = `${window.location.origin}/docs/${doc.id}`

  const membersQuery = useQuery({
    queryKey: ["members", doc.id],
    queryFn: () => documentService.listMembers(doc.id),
    enabled: open,
  })

  const visibilityMutation = useMutation({
    mutationFn: (visibility: "private" | "link") =>
      documentService.update(doc.id, { visibility }),
    onSuccess: (updated) => {
      queryClient.setQueryData<DocumentResponse[]>(["docs"], (docs) =>
        docs?.map((d) => (d.id === updated.id ? updated : d)),
      )
    },
  })

  const addMemberMutation = useMutation({
    mutationFn: () => documentService.addMember(doc.id, email, role),
    onSuccess: () => {
      setEmail("")
      queryClient.invalidateQueries({ queryKey: ["members", doc.id] })
    },
  })

  const removeMemberMutation = useMutation({
    mutationFn: (userId: string) => documentService.removeMember(doc.id, userId),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["members", doc.id] }),
  })

  async function handleCopyLink() {
    if (doc.visibility !== "link") {
      await visibilityMutation.mutateAsync("link")
    }
    await navigator.clipboard.writeText(shareUrl)
    setCopied(true)
    setTimeout(() => setCopied(false), 2000)
  }

  function handleAddMember(e: React.FormEvent) {
    e.preventDefault()
    if (email.trim()) addMemberMutation.mutate()
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-md">
        <DialogHeader>
          <DialogTitle>Share "{doc.title}"</DialogTitle>
        </DialogHeader>

        <div className="flex flex-col gap-2">
          <p className="text-sm text-muted-foreground">
            {doc.visibility === "link"
              ? "Anyone with this link can open and edit this document."
              : "Copying the link makes this document editable by anyone who has it."}
          </p>
          <div className="flex gap-2">
            <Input value={shareUrl} readOnly onFocus={(e) => e.target.select()} />
            <Button onClick={handleCopyLink} disabled={visibilityMutation.isPending}>
              {copied ? "Copied!" : "Copy link"}
            </Button>
          </div>
          {doc.visibility === "link" && (
            <button
              type="button"
              className="self-start text-xs text-muted-foreground underline underline-offset-4"
              onClick={() => visibilityMutation.mutate("private")}
            >
              Make private again
            </button>
          )}
        </div>

        <div className="flex flex-col gap-3 border-t pt-4">
          <p className="text-sm font-medium">Members</p>

          {membersQuery.isLoading && (
            <p className="text-sm text-muted-foreground">Loading…</p>
          )}
          {membersQuery.data?.length === 0 && (
            <p className="text-sm text-muted-foreground">No members added yet.</p>
          )}
          {membersQuery.data && membersQuery.data.length > 0 && (
            <ul className="flex flex-col gap-2">
              {membersQuery.data.map((member) => (
                <li key={member.user_id} className="flex items-center justify-between text-sm">
                  <span>
                    {member.name}{" "}
                    <span className="text-muted-foreground">({member.email})</span>
                  </span>
                  <div className="flex items-center gap-2">
                    <span className="text-xs text-muted-foreground">{member.role}</span>
                    <Button
                      variant="ghost"
                      size="sm"
                      onClick={() => removeMemberMutation.mutate(member.user_id)}
                    >
                      Remove
                    </Button>
                  </div>
                </li>
              ))}
            </ul>
          )}

          <form onSubmit={handleAddMember} className="flex gap-2">
            <Input
              type="email"
              placeholder="Email address"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
            />
            <Select value={role} onValueChange={(value) => setRole(value as "reader" | "writer")}>
              <SelectTrigger className="w-28">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="writer">Writer</SelectItem>
                <SelectItem value="reader">Reader</SelectItem>
              </SelectContent>
            </Select>
            <Button type="submit" disabled={addMemberMutation.isPending || !email.trim()}>
              Add
            </Button>
          </form>
          {addMemberMutation.isError && (
            <p className="text-sm text-destructive">
              Couldn't add member: {addMemberMutation.error.message}
            </p>
          )}
        </div>
      </DialogContent>
    </Dialog>
  )
}
