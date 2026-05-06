/**
 * Subscription Overview Component
 * ==============================
 * Displays current subscription details and management options
 */

'use client';

import { useState } from 'react';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { 
  getSubscription, 
  cancelSubscription, 
  getCustomerPortalUrl,
  getPlan,
  formatSubscriptionStatus,
  type Subscription 
} from '@/lib/billing-service';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import { Badge } from '@/components/ui/badge';
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog';
import { Alert, AlertDescription } from '@/components/ui/alert';
import { 
  CreditCard, 
  Calendar, 
  AlertCircle, 
  ExternalLink,
  Loader2,
  CheckCircle2
} from 'lucide-react';
import { cn } from '@/lib/utils';

interface SubscriptionOverviewProps {
  className?: string;
}

export function SubscriptionOverview({ className }: SubscriptionOverviewProps) {
  const [showCancelDialog, setShowCancelDialog] = useState(false);
  const queryClient = useQueryClient();

  // Fetch subscription
  const { data: subscription, isLoading } = useQuery({
    queryKey: ['subscription'],
    queryFn: getSubscription,
  });

  // Cancel mutation
  const cancelMutation = useMutation({
    mutationFn: cancelSubscription,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['subscription'] });
      setShowCancelDialog(false);
    },
  });

  // Portal mutation
  const portalMutation = useMutation({
    mutationFn: getCustomerPortalUrl,
    onSuccess: (url) => {
      window.location.href = url;
    },
  });

  if (isLoading) {
    return (
      <Card className={className}>
        <CardHeader>
          <CardTitle>Subscription</CardTitle>
          <CardDescription>Loading subscription details...</CardDescription>
        </CardHeader>
        <CardContent>
          <div className="h-40 animate-pulse bg-muted rounded" />
        </CardContent>
      </Card>
    );
  }

  // Free plan or no subscription
  if (!subscription || subscription.plan_tier === 'FREE') {
    return (
      <Card className={className}>
        <CardHeader>
          <CardTitle>Subscription</CardTitle>
          <CardDescription>You are currently on the free plan</CardDescription>
        </CardHeader>
        <CardContent>
          <div className="space-y-4">
            <div className="flex items-center justify-between py-3">
              <span className="text-sm text-muted-foreground">Current Plan</span>
              <Badge variant="secondary">Free</Badge>
            </div>
            <Alert>
              <CheckCircle2 className="h-4 w-4" />
              <AlertDescription>
                Upgrade to unlock more features and higher character limits
              </AlertDescription>
            </Alert>
          </div>
        </CardContent>
      </Card>
    );
  }

  const plan = getPlan(subscription.plan_tier);
  const statusColor = getStatusColor(subscription.status);

  const formatDate = (dateString?: string) => {
    if (!dateString) return 'N/A';
    return new Date(dateString).toLocaleDateString('en-US', {
      month: 'long',
      day: 'numeric',
      year: 'numeric',
    });
  };

  return (
    <>
      <Card className={className}>
        <CardHeader>
          <div className="flex items-center justify-between">
            <div>
              <CardTitle>Subscription</CardTitle>
              <CardDescription>Manage your subscription and billing</CardDescription>
            </div>
            <CreditCard className="h-5 w-5 text-muted-foreground" />
          </div>
        </CardHeader>
        <CardContent className="space-y-4">
          {/* Plan Details */}
          <div className="space-y-3">
            <div className="flex items-center justify-between py-2">
              <span className="text-sm text-muted-foreground">Current Plan</span>
              <span className="font-semibold">{plan.name}</span>
            </div>

            <div className="flex items-center justify-between py-2">
              <span className="text-sm text-muted-foreground">Status</span>
              <Badge variant="outline" className={cn(statusColor)}>
                {formatSubscriptionStatus(subscription.status)}
              </Badge>
            </div>

            <div className="flex items-center justify-between py-2">
              <span className="text-sm text-muted-foreground">Billing Interval</span>
              <span className="font-medium capitalize">{subscription.billing_interval}</span>
            </div>

            {subscription.current_period_end && (
              <div className="flex items-center justify-between py-2">
                <span className="text-sm text-muted-foreground">
                  {subscription.cancel_at_period_end ? 'Expires On' : 'Renews On'}
                </span>
                <div className="flex items-center gap-2">
                  <Calendar className="h-4 w-4 text-muted-foreground" />
                  <span className="font-medium">{formatDate(subscription.current_period_end)}</span>
                </div>
              </div>
            )}

            {subscription.cancel_at_period_end && (
              <Alert variant="destructive">
                <AlertCircle className="h-4 w-4" />
                <AlertDescription>
                  Your subscription will be canceled at the end of the billing period
                </AlertDescription>
              </Alert>
            )}
          </div>

          {/* Actions */}
          <div className="pt-4 border-t space-y-2">
            <Button
              onClick={() => portalMutation.mutate()}
              disabled={portalMutation.isPending}
              variant="default"
              className="w-full"
            >
              {portalMutation.isPending ? (
                <>
                  <Loader2 className="h-4 w-4 mr-2 animate-spin" />
                  Loading...
                </>
              ) : (
                <>
                  <ExternalLink className="h-4 w-4 mr-2" />
                  Manage Billing
                </>
              )}
            </Button>

            {!subscription.cancel_at_period_end && subscription.status === 'active' && (
              <Button
                onClick={() => setShowCancelDialog(true)}
                variant="outline"
                className="w-full"
              >
                Cancel Subscription
              </Button>
            )}
          </div>
        </CardContent>
      </Card>

      {/* Cancel Confirmation Dialog */}
      <Dialog open={showCancelDialog} onOpenChange={setShowCancelDialog}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Cancel Subscription?</DialogTitle>
            <DialogDescription>
              Your subscription will remain active until {formatDate(subscription.current_period_end)}.
              You&apos;ll still have access to all {plan.name} features until then.
            </DialogDescription>
          </DialogHeader>
          <DialogFooter>
            <Button
              variant="outline"
              onClick={() => setShowCancelDialog(false)}
              disabled={cancelMutation.isPending}
            >
              Keep Subscription
            </Button>
            <Button
              variant="destructive"
              onClick={() => cancelMutation.mutate()}
              disabled={cancelMutation.isPending}
            >
              {cancelMutation.isPending ? (
                <>
                  <Loader2 className="h-4 w-4 mr-2 animate-spin" />
                  Canceling...
                </>
              ) : (
                'Cancel Subscription'
              )}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </>
  );
}

function getStatusColor(status: string): string {
  const colorMap: Record<string, string> = {
    active: 'bg-green-100 text-green-800 dark:bg-green-900 dark:text-green-300',
    canceled: 'bg-red-100 text-red-800 dark:bg-red-900 dark:text-red-300',
    past_due: 'bg-yellow-100 text-yellow-800 dark:bg-yellow-900 dark:text-yellow-300',
    trialing: 'bg-blue-100 text-blue-800 dark:bg-blue-900 dark:text-blue-300',
    unpaid: 'bg-red-100 text-red-800 dark:bg-red-900 dark:text-red-300',
  };
  return colorMap[status] || 'bg-gray-100 text-gray-800 dark:bg-gray-800 dark:text-gray-300';
}
