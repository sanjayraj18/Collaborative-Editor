import axios, { type AxiosError, type InternalAxiosRequestConfig } from "axios"

const http = axios.create({
    baseURL: "/api",
    withCredentials : true
})

let accessToken: string | null = null

export function setAccessToken(token: string | null): void {
  accessToken = token
}

http.interceptors.request.use((config) => {
  if(accessToken){
    config.headers.Authorization = `Bearer ${accessToken}`
  }
  return config
})

interface RetriableConfig extends InternalAxiosRequestConfig {
  _retried?: boolean
}

let refreshInFlight: Promise<string> | null = null

function refreshAccessToken() : Promise<string> | null {

  if(!refreshInFlight){
    refreshInFlight = axios.post<{access_token : string}>("/api/auth/refresh", null, { withCredentials: true })
    .then((res) =>{
      setAccessToken(res.data.access_token)
      return res.data.access_token
    })
    .finally(() =>{
      refreshInFlight = null
    })
  }
  return refreshInFlight

}

http.interceptors.response.use(
  (res) => res,
  async (error: AxiosError) => {
    const config = error.config as RetriableConfig | undefined

    if (error.response?.status === 401 && config && !config._retried) {
      config._retried = true
      try {
        await refreshAccessToken()
        return http(config) 
      } catch {
        setAccessToken(null)
      }
    }
    return Promise.reject(error)
  },
)


export default http