import http, { setAccessToken } from "./http"
import type { UserResponse } from "./types/User"

export interface AccessTokenResponse {
  access_token: string
  token_type: string
}

export class AuthService {
  async me(): Promise<UserResponse> {
    const { data } = await http.get<UserResponse>("/auth/me")
    return data
  }

  async signup(name: string, email: string, password: string): Promise<AccessTokenResponse> {
    const { data } = await http.post<AccessTokenResponse>("/auth/signup", { name, email, password })
    setAccessToken(data.access_token)
    return data
  }

  async signin(email: string, password: string): Promise<AccessTokenResponse> {
    const { data } = await http.post<AccessTokenResponse>("/auth/signin", { email, password })
    setAccessToken(data.access_token)
    return data
  }

  async signout(): Promise<void> {
    await http.post("/auth/signout")
    setAccessToken(null)
  }
}

export const authService = new AuthService()