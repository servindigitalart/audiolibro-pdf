/**
 * Authentication Service
 * ====================
 * Handles login, register, logout, and token management
 */

import Cookies from 'js-cookie';
import apiClient from './api-client';

export interface LoginCredentials {
  email: string;
  password: string;
}

export interface RegisterData {
  email: string;
  password: string;
  confirmPassword?: string;
}

export interface AuthResponse {
  access_token: string;
  refresh_token: string;
  token_type: string;
  user: User;
}

export interface User {
  id: string;
  email: string;
  role: string;
  plan_tier: string;
  is_active: boolean;
  is_verified: boolean;
  created_at: string;
}

class AuthService {
  /**
   * Login user with email and password
   */
  async login(credentials: LoginCredentials): Promise<AuthResponse> {
    // OAuth2 password flow expects form data
    const formData = new URLSearchParams();
    formData.append('username', credentials.email);
    formData.append('password', credentials.password);

    const response = await apiClient.post<AuthResponse>('/auth/login', formData, {
      headers: {
        'Content-Type': 'application/x-www-form-urlencoded',
      },
    });

    const { access_token, refresh_token } = response.data;

    // Store tokens in cookies
    this.setTokens(access_token, refresh_token);

    return response.data;
  }

  /**
   * Register new user
   */
  async register(data: RegisterData): Promise<AuthResponse> {
    const response = await apiClient.post<AuthResponse>('/auth/register', {
      email: data.email,
      password: data.password,
    });

    const { access_token, refresh_token } = response.data;

    // Store tokens in cookies
    this.setTokens(access_token, refresh_token);

    return response.data;
  }

  /**
   * Logout user and clear tokens
   */
  async logout(): Promise<void> {
    try {
      // Call logout endpoint to invalidate tokens on server
      await apiClient.post('/auth/logout');
    } catch (error) {
      // Continue with local logout even if server call fails
      console.error('Logout error:', error);
    } finally {
      this.clearTokens();
    }
  }

  /**
   * Get current user profile
   */
  async getCurrentUser(): Promise<User> {
    const response = await apiClient.get<User>('/auth/me');
    return response.data;
  }

  /**
   * Check if user is authenticated
   */
  isAuthenticated(): boolean {
    const token = Cookies.get('access_token');
    return !!token;
  }

  /**
   * Get access token
   */
  getAccessToken(): string | undefined {
    return Cookies.get('access_token');
  }

  /**
   * Store tokens in cookies
   */
  private setTokens(accessToken: string, refreshToken: string): void {
    Cookies.set('access_token', accessToken, {
      secure: process.env.NODE_ENV === 'production',
      sameSite: 'strict',
      expires: 1 / 48, // 30 minutes
    });

    Cookies.set('refresh_token', refreshToken, {
      secure: process.env.NODE_ENV === 'production',
      sameSite: 'strict',
      expires: 7, // 7 days
    });
  }

  /**
   * Clear tokens from cookies
   */
  private clearTokens(): void {
    Cookies.remove('access_token');
    Cookies.remove('refresh_token');
  }
}

export const authService = new AuthService();
export default authService;
