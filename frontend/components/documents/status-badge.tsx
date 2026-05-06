/**
 * Status Badge Component
 * =====================
 * Displays document status with appropriate colors and animations
 */

'use client';

import { Badge } from '@/components/ui/badge';
import { getStatusConfig } from '@/lib/document-status';
import { Loader2 } from 'lucide-react';
import { cn } from '@/lib/utils';

interface StatusBadgeProps {
  status: string;
  className?: string;
  showIcon?: boolean;
}

const colorVariants = {
  default: 'bg-gray-100 text-gray-800 dark:bg-gray-800 dark:text-gray-300',
  secondary: 'bg-blue-100 text-blue-800 dark:bg-blue-900 dark:text-blue-300',
  warning: 'bg-yellow-100 text-yellow-800 dark:bg-yellow-900 dark:text-yellow-300',
  success: 'bg-green-100 text-green-800 dark:bg-green-900 dark:text-green-300',
  destructive: 'bg-red-100 text-red-800 dark:bg-red-900 dark:text-red-300',
};

export function StatusBadge({ status, className, showIcon = true }: StatusBadgeProps) {
  const config = getStatusConfig(status);
  const isProcessing = status === 'processing' || status === 'queued' || status === 'pending';

  return (
    <Badge
      variant="outline"
      className={cn(
        'font-medium',
        colorVariants[config.color],
        className
      )}
    >
      {showIcon && isProcessing && (
        <Loader2 className="mr-1 h-3 w-3 animate-spin" />
      )}
      {config.label}
    </Badge>
  );
}
