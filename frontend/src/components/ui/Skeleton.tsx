import { FC } from 'react';
import { cn } from '../../utils';

interface SkeletonProps {
  className?: string;
  width?: string | number;
  height?: string | number;
  circle?: boolean;
}

export const Skeleton: FC<SkeletonProps> = ({
  className,
  width,
  height,
  circle = false,
}) => {
  return (
    <div
      className={cn(
        'animate-pulse bg-opsgrid-border',
        circle ? 'rounded-full' : 'rounded',
        className
      )}
      style={{
        width: width,
        height: height,
      }}
    />
  );
};

export const SkeletonCard: FC<{ lines?: number }> = ({ lines = 3 }) => {
  return (
    <div className="space-y-3 p-4">
      <Skeleton width="60%" height={24} />
      {Array.from({ length: lines }).map((_, i) => (
        <Skeleton key={i} width="100%" height={16} />
      ))}
    </div>
  );
};

export const SkeletonTable: FC<{ rows?: number; columns?: number }> = ({
  rows = 5,
  columns = 4,
}) => {
  return (
    <div className="space-y-3 p-4">
      <div className="flex gap-4">
        {Array.from({ length: columns }).map((_, i) => (
          <Skeleton key={i} width={`${100 / columns}%`} height={20} />
        ))}
      </div>
      {Array.from({ length: rows }).map((_, rowIndex) => (
        <div key={rowIndex} className="flex gap-4">
          {Array.from({ length: columns }).map((_, colIndex) => (
            <Skeleton key={colIndex} width={`${100 / columns}%`} height={16} />
          ))}
        </div>
      ))}
    </div>
  );
};
