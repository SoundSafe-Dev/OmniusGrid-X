import { format, formatDistanceToNow } from 'date-fns';

export function formatDate(date: string | Date, formatStr: string = 'MM/dd/yyyy'): string {
  try {
    return format(new Date(date), formatStr);
  } catch {
    return 'Invalid date';
  }
}

export function formatDateTime(date: string | Date, format12h: boolean = true): string {
  try {
    const formatStr = format12h ? 'MM/dd/yyyy hh:mm:ss a' : 'MM/dd/yyyy HH:mm:ss';
    return format(new Date(date), formatStr);
  } catch {
    return 'Invalid date';
  }
}

export function formatTimeAgo(date: string | Date): string {
  try {
    return formatDistanceToNow(new Date(date), { addSuffix: true });
  } catch {
    return 'Invalid date';
  }
}

export function formatDuration(seconds: number): string {
  if (seconds < 60) {
    return `${Math.round(seconds)}s`;
  } else if (seconds < 3600) {
    return `${Math.round(seconds / 60)}m`;
  } else if (seconds < 86400) {
    return `${Math.round(seconds / 3600)}h`;
  } else {
    return `${Math.round(seconds / 86400)}d`;
  }
}

export function formatBytes(bytes: number): string {
  if (bytes === 0) return '0 B';
  const k = 1024;
  const sizes = ['B', 'KB', 'MB', 'GB', 'TB'];
  const i = Math.floor(Math.log(bytes) / Math.log(k));
  return `${parseFloat((bytes / Math.pow(k, i)).toFixed(2))} ${sizes[i]}`;
}

export function formatNumber(num: number, decimals: number = 2): string {
  return num.toLocaleString(undefined, {
    minimumFractionDigits: decimals,
    maximumFractionDigits: decimals,
  });
}

export function formatPercentage(value: number, decimals: number = 1): string {
  return `${(value * 100).toFixed(decimals)}%`;
}
