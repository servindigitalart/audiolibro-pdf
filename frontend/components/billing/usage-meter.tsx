/**
 * Usage Meter Component
 * ====================
 * Displays character usage with quota visualization
 */

'use client';

import { useQuery } from '@tanstack/react-query';
import { getUsageData, getPlan } from '@/lib/billing-service';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Progress } from '@/components/ui/progress';
import { Alert, AlertDescription } from '@/components/ui/alert';
import { AlertTriangle, TrendingUp } from 'lucide-react';
import { cn } from '@/lib/utils';

interface UsageMeterProps {
  planTier: string;
  className?: string;
}

export function UsageMeter({ planTier, className }: UsageMeterProps) {
  const { data: usage, isLoading } = useQuery({
    queryKey: ['usage'],
    queryFn: getUsageData,
    refetchInterval: 60000, // Refresh every minute
  });

  if (isLoading) {
    return (
      <Card className={className}>
        <CardHeader>
          <CardTitle>Usage</CardTitle>
          <CardDescription>Loading usage data...</CardDescription>
        </CardHeader>
        <CardContent>
          <div className="h-20 animate-pulse bg-muted rounded" />
        </CardContent>
      </Card>
    );
  }

  if (!usage) {
    return null;
  }

  const plan = getPlan(planTier as any);
  const usagePercentage = (usage.characters_used / usage.character_quota) * 100;
  const remainingCharacters = usage.character_quota - usage.characters_used;
  
  // Color thresholds
  const getProgressColor = () => {
    if (usagePercentage >= 90) return 'bg-red-500';
    if (usagePercentage >= 70) return 'bg-yellow-500';
    return 'bg-green-500';
  };

  const showWarning = usagePercentage >= 85;

  const formatNumber = (num: number) => {
    return new Intl.NumberFormat('en-US').format(num);
  };

  const formatDate = (dateString: string) => {
    return new Date(dateString).toLocaleDateString('en-US', {
      month: 'short',
      day: 'numeric',
    });
  };

  return (
    <Card className={className}>
      <CardHeader>
        <div className="flex items-center justify-between">
          <div>
            <CardTitle>Character Usage</CardTitle>
            <CardDescription>
              Current billing period: {formatDate(usage.current_period_start)} - {formatDate(usage.current_period_end)}
            </CardDescription>
          </div>
          <TrendingUp className="h-5 w-5 text-muted-foreground" />
        </div>
      </CardHeader>
      <CardContent className="space-y-4">
        {/* Usage Progress */}
        <div className="space-y-2">
          <div className="flex items-center justify-between text-sm">
            <span className="font-medium">
              {formatNumber(usage.characters_used)} / {formatNumber(usage.character_quota)} characters
            </span>
            <span className={cn(
              'font-semibold',
              usagePercentage >= 90 ? 'text-red-600 dark:text-red-400' :
              usagePercentage >= 70 ? 'text-yellow-600 dark:text-yellow-400' :
              'text-green-600 dark:text-green-400'
            )}>
              {usagePercentage.toFixed(1)}%
            </span>
          </div>
          
          <div className="relative">
            <Progress 
              value={Math.min(usagePercentage, 100)} 
              className="h-3"
            />
            <div 
              className={cn(
                'absolute top-0 left-0 h-3 rounded-full transition-all',
                getProgressColor()
              )}
              style={{ width: `${Math.min(usagePercentage, 100)}%` }}
            />
          </div>
          
          <p className="text-xs text-muted-foreground">
            {remainingCharacters > 0 
              ? `${formatNumber(remainingCharacters)} characters remaining`
              : 'Quota exceeded'
            }
          </p>
        </div>

        {/* Warning Alert */}
        {showWarning && (
          <Alert variant="destructive" className="border-yellow-500 bg-yellow-50 dark:bg-yellow-950">
            <AlertTriangle className="h-4 w-4 text-yellow-600 dark:text-yellow-400" />
            <AlertDescription className="text-yellow-600 dark:text-yellow-400">
              {usagePercentage >= 100 
                ? "You've reached your character limit. Upgrade to continue processing documents."
                : "You're approaching your character limit. Consider upgrading to avoid interruptions."
              }
            </AlertDescription>
          </Alert>
        )}

        {/* Documents Processed */}
        <div className="pt-2 border-t">
          <div className="flex items-center justify-between text-sm">
            <span className="text-muted-foreground">Documents processed</span>
            <span className="font-semibold">{usage.documents_processed}</span>
          </div>
        </div>
      </CardContent>
    </Card>
  );
}
