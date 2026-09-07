import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import type { DocumentResponse } from "@/services/types/Document"

interface DocumentCardProps {
  doc: DocumentResponse
  onClick: () => void
}

export const DocumentCard = ({ doc, onClick }: DocumentCardProps) => {
  return (
    <Card
      className="cursor-pointer transition-colors hover:bg-accent"
      onClick={onClick}
    >
      <CardHeader>
        <CardTitle className="flex items-center justify-between text-base">
          <span>{doc.title}</span>
          <span className="flex gap-2 text-xs font-normal text-muted-foreground">
            <span>{doc.role}</span>
            {doc.visibility === "link" && <span>· link-shared</span>}
          </span>
        </CardTitle>
      </CardHeader>
      <CardContent className="text-xs text-muted-foreground">
        Updated {new Date(doc.updated_at).toLocaleString()}
      </CardContent>
    </Card>
  )
}