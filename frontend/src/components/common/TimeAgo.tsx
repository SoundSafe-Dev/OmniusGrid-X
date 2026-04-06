import { FC } from 'react';
import { formatTimeAgo } from '../../utils';

interface TimeAgoProps {
  date: string | Date;
  className?: string;
  titleFormat?: string;
}

export const TimeAgo: FC<TimeAgoProps> = ({
  date,
  className = '',
}) => {
  const timeAgo = formatTimeAgo(date);
  const fullDate = new Date(date).toLocaleString();

  return (
    <span className={`text-sm text-opsgrid-text-secondary ${className}`} title={fullDate}>
      {timeAgo}
    </span>
  );
};
