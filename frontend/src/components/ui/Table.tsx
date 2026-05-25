import { FC, ReactNode, ThHTMLAttributes, TdHTMLAttributes } from 'react';
import { cn } from '../../utils';
import { Tooltip, TooltipTrigger, TooltipContent } from './Tooltip';

interface TableProps {
  children: ReactNode;
  className?: string;
}

interface TableHeaderProps extends ThHTMLAttributes<HTMLTableHeaderCellElement> {
  tooltip?: string;
}

interface TableCellProps extends TdHTMLAttributes<HTMLTableCellElement> {
  tooltip?: string;
}

export const Table: FC<TableProps> & {
  Head: FC<TableProps>;
  Body: FC<TableProps>;
  Row: FC<TableProps>;
  Header: FC<TableHeaderProps>;
  Cell: FC<TableCellProps>;
} = ({ children, className }) => {
  return (
    <div className="overflow-x-auto">
      <table className={cn('w-full text-left', className)}>{children}</table>
    </div>
  );
};

const Head: FC<TableProps> = ({ children, className }) => {
  return (
    <thead className={cn('bg-opsgrid-bg', className)}>{children}</thead>
  );
};

const Body: FC<TableProps> = ({ children, className }) => {
  return (
    <tbody className={cn('divide-y divide-opsgrid-border', className)}>
      {children}
    </tbody>
  );
};

const Row: FC<TableProps> = ({ children, className }) => {
  return (
    <tr className={cn('hover:bg-opsgrid-bg/50 transition-colors', className)}>
      {children}
    </tr>
  );
};

const Header: FC<TableHeaderProps> = ({
  children,
  className,
  tooltip,
  ...props
}) => {
  if (tooltip) {
    return (
      <Tooltip>
        <TooltipTrigger asChild>
          <th
            className={cn(
              'px-4 py-3 text-sm font-medium text-opsgrid-text-secondary',
              className
            )}
            {...props}
          >
            {children}
          </th>
        </TooltipTrigger>
        <TooltipContent>{tooltip}</TooltipContent>
      </Tooltip>
    );
  }
  return (
    <th
      className={cn(
        'px-4 py-3 text-sm font-medium text-opsgrid-text-secondary',
        className
      )}
      {...props}
    >
      {children}
    </th>
  );
};

const Cell: FC<TableCellProps> = ({
  children,
  className,
  tooltip,
  ...props
}) => {
  if (tooltip) {
    return (
      <Tooltip>
        <TooltipTrigger asChild>
          <td
            className={cn('px-4 py-3 text-sm text-opsgrid-text', className)}
            {...props}
          >
            {children}
          </td>
        </TooltipTrigger>
        <TooltipContent>{tooltip}</TooltipContent>
      </Tooltip>
    );
  }
  return (
    <td
      className={cn('px-4 py-3 text-sm text-opsgrid-text', className)}
      {...props}
    >
      {children}
    </td>
  );
};

Table.Head = Head;
Table.Body = Body;
Table.Row = Row;
Table.Header = Header;
Table.Cell = Cell;
