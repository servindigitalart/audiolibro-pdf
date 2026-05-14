/**
 * Auth form tests — validation logic and submission states.
 */
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import LoginForm    from '@/components/auth/LoginForm';
import RegisterForm from '@/components/auth/RegisterForm';
import * as clientApi from '@/lib/api/client';

vi.mock('@/lib/api/client', () => ({
  login:           vi.fn(),
  register:        vi.fn(),
  getErrorMessage: vi.fn((e: unknown) => (e instanceof Error ? e.message : String(e))),
}));

const mockLogin    = clientApi.login    as ReturnType<typeof vi.fn>;
const mockRegister = clientApi.register as ReturnType<typeof vi.fn>;

// ── LoginForm ─────────────────────────────────────────────────────────────────

describe('LoginForm', () => {
  beforeEach(() => vi.clearAllMocks());

  it('renders email and password fields', () => {
    render(<LoginForm />);
    expect(screen.getByLabelText(/email address/i)).toBeInTheDocument();
    expect(screen.getByLabelText(/password/i)).toBeInTheDocument();
  });

  it('submit button is disabled when fields empty', () => {
    render(<LoginForm />);
    expect(screen.getByRole('button', { name: /sign in/i })).toBeDisabled();
  });

  it('enables submit when both fields filled', () => {
    render(<LoginForm />);
    fireEvent.change(screen.getByLabelText(/email address/i), { target: { value: 'a@b.com' } });
    fireEvent.change(screen.getByLabelText(/password/i),     { target: { value: 'secret' } });
    expect(screen.getByRole('button', { name: /sign in/i })).not.toBeDisabled();
  });

  it('shows API error message on failure', async () => {
    mockLogin.mockRejectedValue(new Error('Invalid credentials'));
    vi.mocked(clientApi.getErrorMessage).mockReturnValue('Invalid credentials');

    render(<LoginForm />);
    fireEvent.change(screen.getByLabelText(/email address/i), { target: { value: 'a@b.com' } });
    fireEvent.change(screen.getByLabelText(/password/i),     { target: { value: 'wrong' } });
    fireEvent.click(screen.getByRole('button', { name: /sign in/i }));

    await waitFor(() => {
      expect(screen.getByRole('alert')).toHaveTextContent('Invalid credentials');
    });
  });
});

// ── RegisterForm ──────────────────────────────────────────────────────────────

describe('RegisterForm', () => {
  beforeEach(() => vi.clearAllMocks());

  it('renders all three fields', () => {
    render(<RegisterForm />);
    expect(screen.getByLabelText(/email address/i)).toBeInTheDocument();
    expect(screen.getByLabelText(/^password$/i)).toBeInTheDocument();
    expect(screen.getByLabelText(/confirm password/i)).toBeInTheDocument();
  });

  it('shows mismatch hint when passwords differ', () => {
    render(<RegisterForm />);
    fireEvent.change(screen.getByLabelText(/^password$/i),      { target: { value: 'abc12345' } });
    fireEvent.change(screen.getByLabelText(/confirm password/i), { target: { value: 'abc12346' } });
    expect(screen.getByText(/don't match/i)).toBeInTheDocument();
  });

  it('submit is disabled while passwords mismatch', () => {
    render(<RegisterForm />);
    fireEvent.change(screen.getByLabelText(/email address/i),    { target: { value: 'a@b.com' } });
    fireEvent.change(screen.getByLabelText(/^password$/i),        { target: { value: 'abc12345' } });
    fireEvent.change(screen.getByLabelText(/confirm password/i), { target: { value: 'abc99999' } });
    expect(screen.getByRole('button', { name: /create/i })).toBeDisabled();
  });
});
