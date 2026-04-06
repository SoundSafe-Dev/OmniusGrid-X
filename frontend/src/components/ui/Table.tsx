import { FC, ReactNode, ThHTMLAttributes, TdHTMLAttributes } from 'react';
import { cn } from '../../utils';

interface TableProps {
  children: ReactNode;
  className?: string;
}

export const Table: FC<TableProps> & {
  Head: FC<TableProps>;
  Body: FC<TableProps>;
  Row: FC<TableProps>;
  Header: FC<ThHTMLAttributes<HTMLTableHeaderCellElement>>;
  Cell: FC<TdHTMLAttributes<HTMLTableCellElement>>;
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

const Header: FC<ThHTMLAttributes<HTMLTableHeaderCellElement>> = ({
  children,
  className,
  ...props
}) => {
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

const Cell: FC<TdHTMLAttributes<HTMLTableCellElement>> = ({
  children,
  className,
  ...props
}) => {
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
