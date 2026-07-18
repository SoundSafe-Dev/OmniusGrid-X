import { FC, useState, FormEvent } from 'react';
import { useNavigate, useLocation } from 'react-router-dom';
import { Eye, EyeOff, AlertCircle, Zap } from 'lucide-react';
import { useAuthStore } from '../../stores';
import { Input, Button } from '../../components';
import { Tooltip, TooltipTrigger, TooltipContent, Wordmark } from '../../components/ui';

// Dev login bypass is OFF unless explicitly enabled (VITE_DEV_MODE=true), and
// only ever in a non-production build. Production bundles can never enable it.
const DEV_MODE = import.meta.env.DEV && import.meta.env.VITE_DEV_MODE === 'true'

export const Login: FC = () => {
  const navigate = useNavigate();
  const location = useLocation();
  const { login, isLoading, error, clearError, devLogin } = useAuthStore();

  const [username, setUsername] = useState('');
  const [password, setPassword] = useState('');
  const [rememberMe, setRememberMe] = useState(false);
  const [showPassword, setShowPassword] = useState(false);

  const from = (location.state as any)?.from?.pathname || '/';

  const handleSubmit = async (e: FormEvent) => {
    e.preventDefault();
    clearError();

    // DEV MODE: bypass authentication when username is "dev" (non-prod only).
    const trimmedUsername = username.trim().toLowerCase();
    if (DEV_MODE && trimmedUsername === 'dev') {
      devLogin({
        id: 'dev-user',
        email: 'admin@omniusgrid.com',
        name: 'Dev Admin',
        role: 'admin',
        isActive: true,
        // The seeded demo org (== the dev-token org, see seed_demo_data.py). The
        // real login path gets this from /auth/me; devLogin must set it so
        // org-scoped endpoints (transportation/geotab) work in the offline demo.
        organizationId: '00000000-0000-0000-0000-000000000001',
        createdAt: new Date().toISOString(),
        updatedAt: new Date().toISOString(),
      }, 'dev-token');
      navigate(from, { replace: true });
      return;
    }

    try {
      await login({ email: username, password, rememberMe });
      navigate(from, { replace: true });
    } catch {
      // Error is handled by the auth store
    }
  };

  return (
    <div className="min-h-screen bg-gradient-to-br from-opsgrid-bg via-opsgrid-panel to-opsgrid-bg flex items-center justify-center p-4">
      <div className="w-full max-w-md">
        {/* Logo & Header */}
        <div className="text-center mb-8">
          <Tooltip>
            <TooltipTrigger asChild>
              <div className="inline-flex items-center justify-center w-16 h-16 bg-white rounded-xl mb-4 shadow-sm border border-opsgrid-border overflow-hidden">
                <img src="/omniusgrid-logo.png" alt="OmniusGrid" className="w-16 h-16" />
              </div>
            </TooltipTrigger>
            <TooltipContent>OmniusGrid Logo</TooltipContent>
          </Tooltip>
          <Tooltip>
            <TooltipTrigger asChild>
              <h1 className="text-2xl text-opsgrid-text"><Wordmark /></h1>
            </TooltipTrigger>
            <TooltipContent>The correlation engine for Industry 4.0</TooltipContent>
          </Tooltip>
          <p className="text-opsgrid-text-secondary mt-1">Data Correlation for Industry 4.0</p>
          {DEV_MODE && (
            <Tooltip>
              <TooltipTrigger asChild>
                <div className="mt-2 inline-flex items-center gap-1 px-3 py-1 bg-status-warning/20 text-status-warning rounded-full text-xs">
                  <Zap size={12} />
                  DEV MODE - Login with "dev" / any password
                </div>
              </TooltipTrigger>
              <TooltipContent>Development mode enabled - use "dev" as username</TooltipContent>
            </Tooltip>
          )}
        </div>

        {/* Login Card */}
        <div className="bg-opsgrid-panel border border-opsgrid-border rounded-xl shadow-xl overflow-hidden">
          <div className="p-6">
            <h2 className="text-xl font-semibold text-opsgrid-text mb-6">Sign In</h2>

            {error && (
              <div className="mb-4 p-3 bg-status-alarm/10 border border-status-alarm/30 rounded-lg flex items-center gap-2 text-status-alarm">
                <AlertCircle size={18} />
                <span className="text-sm">{error}</span>
              </div>
            )}

            <form onSubmit={handleSubmit} className="space-y-4">
              <div>
                <Input
                  type="text"
                  label="Username"
                  placeholder={DEV_MODE ? 'Enter "dev" for dev mode' : 'Enter your username'}
                  value={username}
                  onChange={(e) => setUsername(e.target.value)}
                  required
                  disabled={isLoading}
                />
              </div>

              <div className="relative">
                <Input
                  type={showPassword ? 'text' : 'password'}
                  label="Password"
                  placeholder="Enter your password"
                  value={password}
                  onChange={(e) => setPassword(e.target.value)}
                  required
                  disabled={isLoading}
                />
                <Tooltip>
                  <TooltipTrigger asChild>
                    <button
                      type="button"
                      onClick={() => setShowPassword(!showPassword)}
                      className="absolute right-3 top-[30px] text-opsgrid-text-secondary hover:text-opsgrid-text"
                    >
                      {showPassword ? <EyeOff size={18} /> : <Eye size={18} />}
                    </button>
                  </TooltipTrigger>
                  <TooltipContent>{showPassword ? 'Hide password' : 'Show password'}</TooltipContent>
                </Tooltip>
              </div>

              <div className="flex items-center justify-between">
                <Tooltip>
                  <TooltipTrigger asChild>
                    <label className="flex items-center gap-2 cursor-pointer">
                      <input
                        type="checkbox"
                        checked={rememberMe}
                        onChange={(e) => setRememberMe(e.target.checked)}
                        className="w-4 h-4 rounded border-opsgrid-border bg-opsgrid-bg text-opsgrid-primary focus:ring-opsgrid-primary"
                      />
                      <span className="text-sm text-opsgrid-text-secondary">Remember me</span>
                    </label>
                  </TooltipTrigger>
                  <TooltipContent>Keep me signed in on this device</TooltipContent>
                </Tooltip>
                <Tooltip>
                  <TooltipTrigger asChild>
                    <span className="text-sm text-opsgrid-text-secondary cursor-help">
                      Forgot password?
                    </span>
                  </TooltipTrigger>
                  <TooltipContent>
                    Password resets are handled by your administrator — there is no
                    self-serve reset.
                  </TooltipContent>
                </Tooltip>
              </div>

              <Tooltip>
                <TooltipTrigger asChild>
                  <Button type="submit" fullWidth loading={isLoading}>
                    Sign In
                  </Button>
                </TooltipTrigger>
                <TooltipContent>Sign in to your account</TooltipContent>
              </Tooltip>
            </form>
          </div>

          {/* Footer */}
          <div className="px-6 py-4 bg-opsgrid-bg/50 border-t border-opsgrid-border">
            <p className="text-center text-sm text-opsgrid-text-secondary">
              Don't have an account?{' '}
              <span className="text-opsgrid-primary">Contact your administrator</span>
            </p>
          </div>
        </div>

        {/* Version */}
        <p className="text-center text-xs text-opsgrid-text-secondary mt-6">
          OmniusGrid v0.1.0 • Industrial IoT Platform
        </p>
      </div>
    </div>
  );
};
