import { FC, useState, FormEvent } from 'react';
import { useNavigate, useLocation, Link } from 'react-router-dom';
import { Factory, Eye, EyeOff, AlertCircle } from 'lucide-react';
import { useAuth } from '../../hooks';
import { Input, Button } from '../../components';
import { cn } from '../../utils';

export const Login: FC = () => {
  const navigate = useNavigate();
  const location = useLocation();
  const { login, isLoading, error, clearError } = useAuth();

  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [rememberMe, setRememberMe] = useState(false);
  const [showPassword, setShowPassword] = useState(false);

  const from = (location.state as any)?.from?.pathname || '/';

  const handleSubmit = async (e: FormEvent) => {
    e.preventDefault();
    clearError();

    try {
      await login({ email, password, rememberMe });
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
          <h1 className="text-2xl font-bold text-opsgrid-text">OpsGrid</h1>
          <p className="text-opsgrid-text-secondary mt-1">Manufacturing Operations Dashboard</p>
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
                  type="email"
                  label="Email"
                  placeholder="Enter your email"
                  value={email}
                  onChange={(e) => setEmail(e.target.value)}
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
          OpsGrid v0.1.0 • Industrial IoT Platform
        </p>
      </div>
    </div>
  );
};
