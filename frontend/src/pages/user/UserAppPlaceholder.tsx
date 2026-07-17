import { FC } from 'react';
import { Link } from 'react-router-dom';
import { Factory } from 'lucide-react';
import { useAuthStore } from '../../stores';

/** Placeholder for upcoming operator / field-facing UI (non-console). */
export const UserAppPlaceholder: FC = () => {
  const { user, logout } = useAuthStore();

  return (
    <div className="min-h-screen bg-opsgrid-bg flex flex-col items-center justify-center p-6 text-center">
      <div className="inline-flex items-center justify-center w-14 h-14 bg-opsgrid-primary/20 rounded-xl mb-4">
        <Factory className="w-7 h-7 text-opsgrid-primary" />
      </div>
      <h1 className="text-2xl font-semibold text-opsgrid-text mb-2">Operator workspace</h1>
      <p className="text-opsgrid-text-secondary max-w-md mb-6">
        You are signed in as <span className="text-opsgrid-text font-medium">{user?.email}</span> (
        {user?.role}). The technical console (dashboard, engines, logistics, admin tools) is restricted
        to administrators. End-user features will be added here.
      </p>
      <div className="flex flex-wrap gap-3 justify-center">
        <button
          type="button"
          onClick={() => logout()}
          className="px-4 py-2 rounded-lg border border-opsgrid-border text-opsgrid-text-secondary hover:bg-opsgrid-panel"
        >
          Sign out
        </button>
        <Link
          to="/login"
          className="px-4 py-2 rounded-lg bg-opsgrid-primary text-white hover:opacity-90"
        >
          Use a different account
        </Link>
      </div>
    </div>
  );
};
