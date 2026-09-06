import axios, { type AxiosError, type InternalAxiosRequestConfig } from "axios"

const http = axios.create({
    baseURL: "api",
    withCredentials : true
})

let accessToken: string | null = null

export function setAccessToken(token: string | null): void {
  accessToken = token
}




export default http