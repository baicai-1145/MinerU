import { client } from '@/services/api';

export interface AuthPayload {
  username: string;
  password: string;
}

export interface AuthResponse {
  user_id: string;
  username: string;
}

export async function registerUser(payload: AuthPayload): Promise<AuthResponse> {
  const response = await client.post<AuthResponse>('/auth/register', payload);
  return response.data;
}

export async function loginUser(payload: AuthPayload): Promise<AuthResponse> {
  const response = await client.post<AuthResponse>('/auth/login', payload);
  return response.data;
}
