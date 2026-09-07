import { MoreVertical } from "lucide-react"
import { useQuery } from "@tanstack/react-query"

import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Button } from "@/components/ui/button"
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu"
import { authService } from "@/services/AuthService"
import type { DocumentResponse } from "@/services/types/Document"

interface DocumentCardProps {
  doc: DocumentResponse
  onClick: () => void
  onShare: () => void
}

export const DocumentCard = ({ doc, onClick, onShare }: DocumentCardProps) => {
  const { data: me } = useQuery({
    queryKey: ["me"],
    queryFn: () => authService.me(),
    staleTime: Infinity,
  })
  const isOwner = me?.id === doc.owner_id

  return (
    <Card
      className="cursor-pointer transition-colors hover:bg-accent"
      onClick={onClick}
    >
      <CardHeader>
        <CardTitle className="flex items-center justify-between text-base">
          <span>{doc.title}</span>
          <span className="flex items-center gap-2 text-xs font-normal text-muted-foreground">
            <span>{doc.role}</span>
            {doc.visibility === "link" && <span>· link-shared</span>}
            {isOwner && (
              <DropdownMenu>
                <DropdownMenuTrigger
                  render={
                    <Button
                      variant="ghost"
                      size="icon-sm"
                      onClick={(e: React.MouseEvent) => e.stopPropagation()}
                    />
                  }
                >
                  <MoreVertical className="size-4" />
                  <span className="sr-only">Document options</span>
                </DropdownMenuTrigger>
                <DropdownMenuContent onClick={(e: React.MouseEvent) => e.stopPropagation()}>
                  <DropdownMenuItem onClick={onShare}>
                    Share &amp; manage access
                  </DropdownMenuItem>
                </DropdownMenuContent>
              </DropdownMenu>
            )}
          </span>
        </CardTitle>
      </CardHeader>
      <CardContent className="text-xs text-muted-foreground">
        Updated {new Date(doc.updated_at).toLocaleString()}
      </CardContent>
    </Card>
  )
}