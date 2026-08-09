import { FC, FormEvent, useEffect, useState } from 'react';
import { AlertCircle, CheckCircle2, Factory, ShieldCheck } from 'lucide-react';
import { useNavigate } from 'react-router-dom';

import { authApi, handleApiError } from '../../api';
import { Button, Input } from '../../components';
import { InvitationValidation } from '../../types';


type PageState = 'validating' | 'ready' | 'invalid' | 'accepted';

const consumeFragmentToken = (): string => {
  const parameters = new URLSearchParams(window.location.hash.slice(1));
  const token = parameters.get('token') ?? '';
  if (token) {
    window.history.replaceState(
      null,
      document.title,
      `${window.location.pathname}${window.location.search}`
    );
  }
  return token;
};

export const AcceptInvitation: FC = () => {
  const navigate = useNavigate();
  const [token] = useState(consumeFragmentToken);
  const [pageState, setPageState] = useState<PageState>('validating');
  const [invitation, setInvitation] = useState<InvitationValidation | null>(null);
  const [name, setName] = useState('');
  const [password, setPassword] = useState('');
  const [confirmPassword, setConfirmPassword] = useState('');
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let active = true;
    if (!token) {
      setError('This invitation link is missing or invalid.');
      setPageState('invalid');
      return () => {
        active = false;
      };
    }

    authApi
      .validateInvitation(token)
      .then((value) => {
        if (!active) return;
        setInvitation(value);
        setPageState('ready');
      })
      .catch((value) => {
        if (!active) return;
        setError(handleApiError(value).message);
        setPageState('invalid');
      });

    return () => {
      active = false;
    };
  }, [token]);

  const submit = async (event: FormEvent) => {
    event.preventDefault();
    setError(null);
    if (password !== confirmPassword) {
      setError('Passwords do not match.');
      return;
    }
    if (password.length < 12) {
      setError('Password must be at least 12 characters.');
      return;
    }

    setSubmitting(true);
    try {
      await authApi.acceptInvitation({
        token,
        name: name.trim(),
        password,
      });
      setPassword('');
      setConfirmPassword('');
      setPageState('accepted');
    } catch (value) {
      setError(handleApiError(value).message);
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div className="flex min-h-screen items-center justify-center bg-gradient-to-br from-opsgrid-bg via-opsgrid-panel to-opsgrid-bg p-4">
      <div className="w-full max-w-md">
        <div className="mb-8 text-center">
          <div className="mb-4 inline-flex h-16 w-16 items-center justify-center rounded-xl bg-opsgrid-primary/20">
            <Factory className="h-8 w-8 text-opsgrid-primary" />
          </div>
          <h1 className="text-2xl font-bold text-opsgrid-text">OmniusGrid</h1>
          <p className="mt-1 text-opsgrid-text-secondary">
            Accept your organization invitation
          </p>
        </div>

        <div className="overflow-hidden rounded-xl border border-opsgrid-border bg-opsgrid-panel shadow-xl">
          <div className="p-6">
            {pageState === 'validating' && (
              <div className="py-8 text-center">
                <div className="mx-auto mb-4 h-8 w-8 animate-spin rounded-full border-2 border-opsgrid-primary border-t-transparent" />
                <p className="text-opsgrid-text-secondary">
                  Validating invitation…
                </p>
              </div>
            )}

            {pageState === 'invalid' && (
              <div className="space-y-5 py-4 text-center">
                <AlertCircle className="mx-auto h-12 w-12 text-status-alarm" />
                <div>
                  <h2 className="text-xl font-semibold">Invitation unavailable</h2>
                  <p className="mt-2 text-sm text-opsgrid-text-secondary">
                    {error || 'This invitation can no longer be used.'}
                  </p>
                </div>
                <p className="text-sm text-opsgrid-text-secondary">
                  Ask your organization administrator to send a new invitation.
                </p>
                <Button
                  variant="secondary"
                  fullWidth
                  onClick={() => navigate('/login')}
                >
                  Return to sign in
                </Button>
              </div>
            )}

            {pageState === 'accepted' && (
              <div className="space-y-5 py-4 text-center">
                <CheckCircle2 className="mx-auto h-12 w-12 text-status-running" />
                <div>
                  <h2 className="text-xl font-semibold">Account ready</h2>
                  <p className="mt-2 text-sm text-opsgrid-text-secondary">
                    Your invitation was accepted. Sign in with your new password.
                  </p>
                </div>
                <Button fullWidth onClick={() => navigate('/login')}>
                  Continue to sign in
                </Button>
              </div>
            )}

            {pageState === 'ready' && invitation && (
              <>
                <div className="mb-6">
                  <div className="mb-3 flex items-center gap-2">
                    <ShieldCheck className="h-5 w-5 text-opsgrid-primary" />
                    <h2 className="text-xl font-semibold">Create your account</h2>
                  </div>
                  <p className="text-sm text-opsgrid-text-secondary">
                    You were invited to <strong>{invitation.organizationName}</strong>{' '}
                    as <strong>{invitation.role}</strong>.
                  </p>
                  <p className="mt-1 text-sm text-opsgrid-text-secondary">
                    Account email: {invitation.email}
                  </p>
                </div>

                {error && (
                  <div className="mb-4 flex items-center gap-2 rounded-lg border border-status-alarm/30 bg-status-alarm/10 p-3 text-status-alarm">
                    <AlertCircle className="h-5 w-5 shrink-0" />
                    <span className="text-sm">{error}</span>
                  </div>
                )}

                <form onSubmit={submit} className="space-y-4">
                  <Input
                    label="Full name"
                    autoComplete="name"
                    required
                    minLength={1}
                    maxLength={255}
                    value={name}
                    onChange={(event) => setName(event.target.value)}
                    disabled={submitting}
                  />
                  <Input
                    label="Password"
                    type="password"
                    autoComplete="new-password"
                    required
                    minLength={12}
                    maxLength={72}
                    value={password}
                    onChange={(event) => setPassword(event.target.value)}
                    helperText="Use at least 12 characters."
                    disabled={submitting}
                  />
                  <Input
                    label="Confirm password"
                    type="password"
                    autoComplete="new-password"
                    required
                    minLength={12}
                    maxLength={72}
                    value={confirmPassword}
                    onChange={(event) => setConfirmPassword(event.target.value)}
                    disabled={submitting}
                  />
                  <Button type="submit" fullWidth loading={submitting}>
                    Accept invitation
                  </Button>
                </form>
              </>
            )}
          </div>
        </div>
      </div>
    </div>
  );
};
