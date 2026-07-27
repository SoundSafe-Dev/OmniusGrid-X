export type UserRole = 'admin' | 'operator' | 'viewer';

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

export type UserInvitationStatus = 'pending' | 'accepted' | 'revoked' | 'expired';
export type UserInvitationDeliveryStatus = 'pending' | 'sent' | 'failed';

export interface UserInvitation {
  id: string;
  email: string;
  role: UserRole;
  status: UserInvitationStatus;
  expiresAt: string;
  deliveryStatus: UserInvitationDeliveryStatus;
  deliveryAttempts: number;
  deliveryErrorCode?: string | null;
  deliveredAt?: string | null;
  createdBy?: string | null;
  acceptedUserId?: string | null;
  acceptedAt?: string | null;
  revokedAt?: string | null;
  createdAt: string;
  updatedAt: string;
}

export interface InvitationValidation {
  email: string;
  role: UserRole;
  organizationName: string;
  expiresAt: string;
}

export interface LoginCredentials {
  email: string;
  password: string;
  rememberMe?: boolean;
}

export interface AuthResponse {
  access_token: string;
  refresh_token: string;
  token_type: string;
}

export interface Permission {
  resource: string;
  action: 'create' | 'read' | 'update' | 'delete' | 'manage';
}

/** Technical console (current app) is admin-only at API and UI level. */
export function isConsoleAdminUser(user: User | null | undefined): boolean {
  return user?.role === 'admin';
}

export const ROLE_PERMISSIONS: Record<UserRole, Permission[]> = {
  admin: [{ resource: '*', action: 'manage' }],
  operator: [
    { resource: 'assets', action: 'read' },
    { resource: 'assets', action: 'update' },
    { resource: 'alarms', action: 'read' },
    { resource: 'alarms', action: 'update' },
    { resource: 'telemetry', action: 'read' },
    { resource: 'oee', action: 'read' },
    { resource: 'kanban', action: 'read' },
    { resource: 'kanban', action: 'update' },
    { resource: 'fleet', action: 'read' },
    { resource: 'logistics', action: 'read' },
  ],
  viewer: [
    { resource: 'assets', action: 'read' },
    { resource: 'alarms', action: 'read' },
    { resource: 'telemetry', action: 'read' },
    { resource: 'oee', action: 'read' },
    { resource: 'kanban', action: 'read' },
    { resource: 'fleet', action: 'read' },
    { resource: 'logistics', action: 'read' },
  ],
};

export function hasPermission(user: User, resource: string, action: Permission['action']): boolean {
  const permissions = ROLE_PERMISSIONS[user.role];
  return permissions.some(
    (p) => (p.resource === '*' || p.resource === resource) && (p.action === 'manage' || p.action === action)
  );
}
