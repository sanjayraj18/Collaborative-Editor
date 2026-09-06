export type Role = "none" | "reader" | "writer"
export type Visibility = "private" | "link"

export interface DocumentResponse {
  id: string
  title: string
  owner_id: string
  visibility: Visibility
  role: Role
  created_at: string
  updated_at: string
}

export interface MemberResponse {
  user_id: string
  email: string
  name: string
  role: Role
  created_at: string
}

export interface TicketResponse {
  ticket: string
  expires_at: number
}
