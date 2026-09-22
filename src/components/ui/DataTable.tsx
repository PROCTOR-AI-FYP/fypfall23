import { useState, useMemo, type ReactNode } from 'react';
import { ChevronUp, ChevronDown, Search } from 'lucide-react';

export interface Column<T> {
  key: string;
  header: string;
  render?: (row: T) => ReactNode;
  sortable?: boolean;
  width?: string;
}

interface DataTableProps<T> {
  columns: Column<T>[];
  data: T[];
  loading?: boolean;
  error?: string;
  emptyMessage?: string;
  emptyAction?: ReactNode;
  onRetry?: () => void;
  searchable?: boolean;
  searchPlaceholder?: string;
  onRowClick?: (row: T) => void;
  rowKey: (row: T) => string;
  filters?: ReactNode;
}

export function DataTable<T>({
  columns,
  data,
  loading,
  error,
  emptyMessage = 'No data found',
  emptyAction,
  onRetry,
  searchable,
  searchPlaceholder = 'Search...',
  onRowClick,
  rowKey,
  filters,
}: DataTableProps<T>) {
  const [searchQuery, setSearchQuery] = useState('');
  const [sortKey, setSortKey] = useState<string | null>(null);
  const [sortDir, setSortDir] = useState<'asc' | 'desc'>('asc');

  const handleSort = (key: string) => {
    if (sortKey === key) {
      setSortDir(prev => (prev === 'asc' ? 'desc' : 'asc'));
    } else {
      setSortKey(key);
      setSortDir('asc');
    }
  };

  const filteredData = useMemo(() => {
    let result = [...data];

    if (searchQuery) {
      const q = searchQuery.toLowerCase();
      result = result.filter(row =>
        Object.values(row as object).some(val =>
          String(val).toLowerCase().includes(q)
        )
      );
    }

    if (sortKey) {
      result.sort((a, b) => {
        const aVal = (a as any)[sortKey];
        const bVal = (b as any)[sortKey];
        const cmp = String(aVal).localeCompare(String(bVal), undefined, { numeric: true });
        return sortDir === 'asc' ? cmp : -cmp;
      });
    }

    return result;
  }, [data, searchQuery, sortKey, sortDir]);

  // Loading state
  if (loading) {
    return (
      <div className="bg-(--color-bg-surface) rounded-[6px] border border-(--color-border-default)">
        <div className="p-8 flex flex-col items-center gap-3">
          <div className="h-6 w-6 border-2 border-(--color-accent-primary) border-t-transparent rounded-full animate-spin" />
          <p className="text-body-sm text-(--color-text-muted)">Loading data...</p>
        </div>
      </div>
    );
  }

  // Error state
  if (error) {
    return (
      <div className="bg-(--color-bg-surface) rounded-[6px] border border-(--color-border-default)">
        <div className="p-8 flex flex-col items-center gap-3">
          <div className="w-10 h-10 rounded-full bg-(--color-error-subtle) flex items-center justify-center">
            <span className="text-(--color-error) text-lg">!</span>
          </div>
          <p className="text-body text-(--color-text-primary)">Something went wrong</p>
          <p className="text-body-sm text-(--color-text-muted)">{error}</p>
          {onRetry && (
            <button
              onClick={onRetry}
              className="mt-2 px-4 py-2 text-[13px] font-medium text-(--color-accent-primary) hover:bg-(--color-accent-primary-subtle) rounded-[6px] transition-colors cursor-pointer"
            >
              Try again
            </button>
          )}
        </div>
      </div>
    );
  }

  return (
    <div className="bg-(--color-bg-surface) rounded-[6px] border border-(--color-border-default)">
      {/* Toolbar */}
      {(searchable || filters) && (
        <div className="px-4 py-3 border-b border-(--color-border-default) flex flex-wrap items-center gap-3">
          {searchable && (
            <div className="relative flex-1 min-w-[200px] max-w-sm">
              <Search size={16} className="absolute left-3 top-1/2 -translate-y-1/2 text-(--color-text-muted)" />
              <input
                type="text"
                value={searchQuery}
                onChange={e => setSearchQuery(e.target.value)}
                placeholder={searchPlaceholder}
                className="w-full pl-9 pr-3 py-2 text-body-sm bg-(--color-bg-surface-raised) border border-(--color-border-default) rounded-[6px] text-(--color-text-primary) placeholder:text-(--color-text-muted) focus:outline-none focus:border-(--color-border-focus)"
              />
            </div>
          )}
          {filters}
        </div>
      )}

      {/* Table */}
      <div className="overflow-x-auto">
        <table className="w-full">
          <thead>
            <tr className="bg-(--color-bg-surface-raised)">
              {columns.map(col => (
                <th
                  key={col.key}
                  className={`
                    px-4 py-3 text-left text-label text-(--color-text-secondary) font-medium
                    border-b border-(--color-border-default)
                    ${col.sortable ? 'cursor-pointer select-none hover:text-(--color-text-primary)' : ''}
                  `}
                  style={col.width ? { width: col.width } : undefined}
                  onClick={() => col.sortable && handleSort(col.key)}
                >
                  <span className="inline-flex items-center gap-1">
                    {col.header}
                    {col.sortable && sortKey === col.key && (
                      sortDir === 'asc' ? <ChevronUp size={14} /> : <ChevronDown size={14} />
                    )}
                  </span>
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {filteredData.length === 0 ? (
              <tr>
                <td colSpan={columns.length} className="px-4 py-12 text-center">
                  <p className="text-body text-(--color-text-muted)">{emptyMessage}</p>
                  {emptyAction && <div className="mt-3">{emptyAction}</div>}
                </td>
              </tr>
            ) : (
              filteredData.map(row => (
                <tr
                  key={rowKey(row)}
                  onClick={() => onRowClick?.(row)}
                  className={`
                    border-b border-(--color-border-default) last:border-b-0
                    transition-colors
                    ${onRowClick ? 'cursor-pointer hover:bg-(--color-accent-primary-subtle)' : ''}
                  `}
                >
                  {columns.map(col => (
                    <td key={col.key} className="px-4 py-3 text-body text-(--color-text-primary)">
                      {col.render ? col.render(row) : String((row as any)[col.key] ?? '')}
                    </td>
                  ))}
                </tr>
              ))
            )}
          </tbody>
        </table>
      </div>

      {/* Footer */}
      {filteredData.length > 0 && (
        <div className="px-4 py-2.5 border-t border-(--color-border-default) text-body-sm text-(--color-text-muted)">
          {filteredData.length} {filteredData.length === 1 ? 'record' : 'records'}
          {searchQuery && ` matching "${searchQuery}"`}
        </div>
      )}
    </div>
  );
}
