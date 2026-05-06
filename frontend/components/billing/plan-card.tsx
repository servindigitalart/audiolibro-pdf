/**
 * Plan Card Component
 * ==================
 * Individual pricing plan card with features and CTA
 */

'use client';

import { useState } from 'react';
import { Card, CardContent, CardDescription, CardFooter, CardHeader, CardTitle } from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import { Badge } from '@/components/ui/badge';
import { 
  Plan, 
  BillingInterval, 
  formatPrice, 
  calculateYearlySavings,
  comparePlans,
  type PlanTier 
} from '@/lib/billing-service';
import { Check, Loader2, Sparkles } from 'lucide-react';
import { cn } from '@/lib/utils';

interface PlanCardProps {
  plan: Plan;
  currentPlan?: PlanTier;
  billingInterval: BillingInterval;
  onSelectPlan: (tier: PlanTier, interval: BillingInterval) => Promise<void>;
  isPopular?: boolean;
  className?: string;
}

export function PlanCard({
  plan,
  currentPlan,
  billingInterval,
  onSelectPlan,
  isPopular = false,
  className,
}: PlanCardProps) {
  const [isLoading, setIsLoading] = useState(false);

  const isCurrentPlan = currentPlan === plan.tier;
  const price = billingInterval === 'monthly' ? plan.monthlyPrice : plan.yearlyPrice;
  const monthlyCost = billingInterval === 'yearly' ? plan.yearlyPrice / 12 : price;
  const yearlySavings = calculateYearlySavings(plan);
  
  const comparison = currentPlan ? comparePlans(currentPlan, plan.tier) : null;
  
  const getButtonText = () => {
    if (isCurrentPlan) return 'Current Plan';
    if (!currentPlan || currentPlan === 'FREE') return 'Get Started';
    if (comparison === 'upgrade') return 'Upgrade';
    if (comparison === 'downgrade') return 'Downgrade';
    return 'Switch Plan';
  };

  const handleSelect = async () => {
    if (isCurrentPlan) return;
    
    setIsLoading(true);
    try {
      await onSelectPlan(plan.tier, billingInterval);
    } catch (error) {
      console.error('Plan selection failed:', error);
    } finally {
      setIsLoading(false);
    }
  };

  const formatNumber = (num: number) => {
    return new Intl.NumberFormat('en-US').format(num);
  };

  return (
    <Card 
      className={cn(
        'relative flex flex-col',
        isCurrentPlan && 'ring-2 ring-primary',
        isPopular && !isCurrentPlan && 'ring-2 ring-blue-500',
        className
      )}
    >
      {/* Popular Badge */}
      {isPopular && !isCurrentPlan && (
        <div className="absolute -top-3 left-1/2 -translate-x-1/2">
          <Badge className="bg-blue-500 hover:bg-blue-600">
            <Sparkles className="h-3 w-3 mr-1" />
            Most Popular
          </Badge>
        </div>
      )}

      {/* Current Plan Badge */}
      {isCurrentPlan && (
        <div className="absolute -top-3 left-1/2 -translate-x-1/2">
          <Badge variant="default">Current Plan</Badge>
        </div>
      )}

      <CardHeader>
        <CardTitle className="text-2xl">{plan.name}</CardTitle>
        <CardDescription>{plan.description}</CardDescription>
      </CardHeader>

      <CardContent className="flex-1 space-y-6">
        {/* Pricing */}
        <div>
          <div className="flex items-baseline gap-2">
            <span className="text-4xl font-bold">
              {formatPrice(monthlyCost)}
            </span>
            {price > 0 && (
              <span className="text-muted-foreground">/month</span>
            )}
          </div>
          
          {billingInterval === 'yearly' && price > 0 && (
            <div className="mt-2 space-y-1">
              <p className="text-sm text-muted-foreground">
                Billed ${plan.yearlyPrice.toFixed(2)} annually
              </p>
              {yearlySavings > 0 && (
                <p className="text-sm font-medium text-green-600 dark:text-green-400">
                  Save ${yearlySavings.toFixed(2)}/year
                </p>
              )}
            </div>
          )}
        </div>

        {/* Key Metrics */}
        <div className="space-y-2 pt-4 border-t">
          <div className="flex items-center justify-between text-sm">
            <span className="text-muted-foreground">Characters/month</span>
            <span className="font-semibold">{formatNumber(plan.characterQuota)}</span>
          </div>
          <div className="flex items-center justify-between text-sm">
            <span className="text-muted-foreground">Concurrent jobs</span>
            <span className="font-semibold">{plan.maxConcurrentJobs}</span>
          </div>
          <div className="flex items-center justify-between text-sm">
            <span className="text-muted-foreground">Support</span>
            <span className="font-semibold">{plan.supportLevel}</span>
          </div>
        </div>

        {/* Features */}
        <div className="space-y-3 pt-4 border-t">
          {plan.features.map((feature, index) => (
            <div key={index} className="flex items-start gap-3">
              <Check className="h-5 w-5 text-green-600 dark:text-green-400 shrink-0 mt-0.5" />
              <span className="text-sm">{feature}</span>
            </div>
          ))}
        </div>
      </CardContent>

      <CardFooter>
        <Button
          onClick={handleSelect}
          disabled={isCurrentPlan || isLoading}
          variant={isPopular && !isCurrentPlan ? 'default' : 'outline'}
          className="w-full"
          size="lg"
        >
          {isLoading ? (
            <>
              <Loader2 className="h-4 w-4 mr-2 animate-spin" />
              Processing...
            </>
          ) : (
            getButtonText()
          )}
        </Button>
      </CardFooter>
    </Card>
  );
}
