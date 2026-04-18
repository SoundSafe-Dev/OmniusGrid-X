import { FC, useState, FormEvent } from 'react';
import { useNavigate, useLocation, Link } from 'react-router-dom';
import { Factory, Eye, EyeOff, AlertCircle, Zap } from 'lucide-react';
import { useAuthStore } from '../../stores';
import { Input, Button } from '../../components';

const DEV_MODE = true; // Set to false for production

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
    console.log('Form submitted', { username, password, DEV_MODE });

    // DEV MODE: Bypass authentication
    const trimmedUsername = username.trim().toLowerCase();
    console.log('Trimmed username:', trimmedUsername, 'Matches dev?', trimmedUsername === 'dev');
    if (DEV_MODE && trimmedUsername === 'dev') {
      console.log('DEV MODE: Bypassing authentication');
      devLogin({
        id: 'dev-user',
        email: 'admin@omniusgrid.com',
        name: 'Dev Admin',
        role: 'admin',
        isActive: true,
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
          <div className="inline-flex items-center justify-center w-16 h-16 bg-opsgrid-primary/20 rounded-xl mb-4">
            <Factory className="w-8 h-8 text-opsgrid-primary" />
          </div>
          <h1 className="text-2xl font-bold text-opsgrid-text">OmniusGrid</h1>
          <p className="text-opsgrid-text-secondary mt-1">Universal Manufacturing Data Feed Dashboard</p>
          {DEV_MODE && (
            <div className="mt-2 inline-flex items-center gap-1 px-3 py-1 bg-status-warning/20 text-status-warning rounded-full text-xs">
              <Zap size={12} />
              DEV MODE - Login with "dev" / any password
            </div>
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
                <button
                  type="button"
                  onClick={() => setShowPassword(!showPassword)}
                  className="absolute right-3 top-[30px] text-opsgrid-text-secondary hover:text-opsgrid-text"
                >
                  {showPassword ? <EyeOff size={18} /> : <Eye size={18} />}
                </button>
              </div>

              <div className="flex items-center justify-between">
                <label className="flex items-center gap-2 cursor-pointer">
                  <input
                    type="checkbox"
                    checked={rememberMe}
                    onChange={(e) => setRememberMe(e.target.checked)}
                    className="w-4 h-4 rounded border-opsgrid-border bg-opsgrid-bg text-opsgrid-primary focus:ring-opsgrid-primary"
                  />
                  <span className="text-sm text-opsgrid-text-secondary">Remember me</span>
                </label>
                <Link
                  to="/forgot-password"
                  className="text-sm text-opsgrid-primary hover:underline"
                >
                  Forgot password?
                </Link>
              </div>

              <Button type="submit" fullWidth loading={isLoading}>
                Sign In
              </Button>
            </form>
          </div>

          {/* Footer */}
          <div className="px-6 py-4 bg-opsgrid-bg/50 border-t border-opsgrid-border">
            <p className="text-center text-sm text-opsgrid-text-secondary">
              Don't have an account?{' '}
              <Link to="/register" className="text-opsgrid-primary hover:underline">
                Contact administrator
              </Link>
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
