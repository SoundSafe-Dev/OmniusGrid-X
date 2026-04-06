export type UserRole = 'admin' | 'operator' | 'viewer' | 'maintenance';

export interface User {
  id: string;
  email: string;
  name: string;
  role: UserRole;
  organizationId?: string;
  isActive: boolean;
  lastLoginAt?: string;
  createdAt: string;
  updatedAt: string;
}

export interface LoginCredentials {
  email: string;
  password: string;
  rememberMe?: boolean;
}

export interface AuthResponse {
  accessToken: string;
  refreshToken: string;
  user: User;
  expiresIn: number;
}

export interface Permission {
  resource: string;
  action: 'create' | 'read' | 'update' | 'delete' | 'manage';
}

export const ROLE_PERMISSIONS: Record<UserRole, Permission[]> = {
  admin: [
    { resource: '*', action: 'manage' },
  ],
  operator: [
    { resource: 'assets', action: 'read' },
    { resource: 'assets', action: 'update' },
    { resource: 'alarms', action: 'read' },
    { resource: 'alarms', action: 'update' },
    { resource: 'telemetry', action: 'read' },
    { resource: 'engines', action: 'read' },
    { resource: 'engines', action: 'update' },
  ],
  viewer: [
    { resource: 'assets', action: 'read' },
    { resource: 'alarms', action: 'read' },
    { resource: 'telemetry', action: 'read' },
    { resource: 'engines', action: 'read' },
  ],
  maintenance: [
    { resource: 'assets', action: 'read' },
    { resource: 'assets', action: 'update' },
    { resource: 'alarms', action: 'read' },
    { resource: 'alarms', action: 'update' },
    { resource: 'collectors', action: 'manage' },
  ],
};

export function hasPermission(user: User, resource: string, action: Permission['action']): boolean {
  const permissions = ROLE_PERMISSIONS[user.role];
  return permissions.some(
    (p) => (p.resource === '*' || p.resource === resource) && (p.action === 'manage' || p.action === action)
  );
}
