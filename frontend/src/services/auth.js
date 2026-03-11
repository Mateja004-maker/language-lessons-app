import { api } from './api'

export async function login(email, password) {
    const { data } = await api.post('/auth/login', { email, password })
    localStorage.setItem('access_token', data.access_token)
    localStorage.setItem('user_role', data.user.role)
    return data.user
}

export async function register(email, password, display_name) {
    const { data } = await api.post('/auth/register', { email, password, display_name })
    return data
}

export function logout() {
    localStorage.removeItem('access_token')
    localStorage.removeItem('user_role')
}