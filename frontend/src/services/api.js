import axios from 'axios'

export const api = axios.create({
    baseURL: '/api'
})

// Dodaj JWT token u svaki zahtev (ako postoji)
api.interceptors.request.use((config) => {
    const token = localStorage.getItem('access_token')
    if (token) config.headers.Authorization = `Bearer ${token}`
    return config
})

// Ako backend vrati 401, izbaci usera na login
api.interceptors.response.use(
    (res) => res,
    (err) => {
        if (err?.response?.status === 401) {
            localStorage.removeItem('access_token')
            localStorage.removeItem('user_role')
            // hard redirect da bude jednostavno
            window.location.href = '/login'
        }
        return Promise.reject(err)
    }
)