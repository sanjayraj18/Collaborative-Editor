import http from "./http"
import type { DocumentResponse, MemberResponse, TicketResponse, Visibility } from "./types/Document"

export class DocumentService {
  async list(): Promise<DocumentResponse[]> {
    const { data } = await http.get<DocumentResponse[]>("/docs")
    return data
  }

  async create(title: string, visibility: Visibility = "private"): Promise<DocumentResponse> {
    const { data } = await http.post<DocumentResponse>("/docs", { title, visibility })
    return data
  }

  async get(id: string): Promise<DocumentResponse> {
    const { data } = await http.get<DocumentResponse>(`/docs/${id}`)
    return data
  }

  async update(id: string, patch: { title?: string; visibility?: Visibility }): Promise<DocumentResponse> {
    const { data } = await http.patch<DocumentResponse>(`/docs/${id}`, patch)
    return data
  }

  async remove(id: string): Promise<void> {
    await http.delete(`/docs/${id}`)
  }

  async listMembers(id: string): Promise<MemberResponse[]> {
    const { data } = await http.get<MemberResponse[]>(`/docs/${id}/members`)
    return data
  }

  async addMember(id: string, email: string, role: "reader" | "writer"): Promise<MemberResponse> {
    const { data } = await http.post<MemberResponse>(`/docs/${id}/members`, { email, role })
    return data
  }

  async removeMember(id: string, userId: string): Promise<void> {
    await http.delete(`/docs/${id}/members/${userId}`)
  }

  async mintTicket(id: string): Promise<TicketResponse> {
    const { data } = await http.post<TicketResponse>(`/docs/${id}/ticket`)
    return data
  }
}

export const documentService = new DocumentService()