/**
 * Billing Service
 * ==============
 * API service layer for billing and subscription operations
 */

import { apiClient } from './api-client';

// Types
export type PlanTier = 'FREE' | 'BASIC' | 'PRO' | 'ENTERPRISE';
export type BillingInterval = 'monthly' | 'yearly';
export type SubscriptionStatus = 'active' | 'canceled' | 'past_due' | 'trialing' | 'incomplete' | 'incomplete_expired' | 'unpaid';

export interface Plan {
  tier: PlanTier;
  name: string;
  description: string;
  monthlyPrice: number;
  yearlyPrice: number;
  characterQuota: number;
  maxConcurrentJobs: number;
  priorityQueue: boolean;
  supportLevel: string;
  features: string[];
}

export interface Subscription {
  id: string;
  user_id: string;
  plan_tier: PlanTier;
  status: SubscriptionStatus;
  stripe_subscription_id?: string;
  stripe_customer_id?: string;
  current_period_start?: string;
  current_period_end?: string;
  cancel_at_period_end: boolean;
  billing_interval: BillingInterval;
  created_at: string;
  updated_at: string;
}

export interface UsageData {
  characters_used: number;
  character_quota: number;
  documents_processed: number;
  current_period_start: string;
  current_period_end: string;
}

export interface CheckoutRequest {
  plan_tier: PlanTier;
  billing_interval: BillingInterval;
}

export interface CheckoutResponse {
  checkout_url: string;
  session_id: string;
}

// Plan definitions (matching backend)
export const PLANS: Record<PlanTier, Plan> = {
  FREE: {
    tier: 'FREE',
    name: 'Free',
    description: 'Perfect for trying out the service',
    monthlyPrice: 0,
    yearlyPrice: 0,
    characterQuota: 50000,
    maxConcurrentJobs: 1,
    priorityQueue: false,
    supportLevel: 'Community',
    features: [
      '50,000 characters/month',
      '1 concurrent job',
      'Standard queue',
      'Community support',
      'Basic voice quality'
    ]
  },
  BASIC: {
    tier: 'BASIC',
    name: 'Basic',
    description: 'For regular users',
    monthlyPrice: 9.99,
    yearlyPrice: 99.99,
    characterQuota: 500000,
    maxConcurrentJobs: 3,
    priorityQueue: false,
    supportLevel: 'Email',
    features: [
      '500,000 characters/month',
      '3 concurrent jobs',
      'Standard queue',
      'Email support',
      'Standard voice quality',
      'Download audiobooks'
    ]
  },
  PRO: {
    tier: 'PRO',
    name: 'Pro',
    description: 'For power users',
    monthlyPrice: 29.99,
    yearlyPrice: 299.99,
    characterQuota: 2000000,
    maxConcurrentJobs: 10,
    priorityQueue: true,
    supportLevel: 'Priority Email',
    features: [
      '2,000,000 characters/month',
      '10 concurrent jobs',
      'Priority queue',
      'Priority email support',
      'Premium voice quality',
      'Advanced chapter detection',
      'API access',
      'Custom voices (coming soon)'
    ]
  },
  ENTERPRISE: {
    tier: 'ENTERPRISE',
    name: 'Enterprise',
    description: 'For teams and businesses',
    monthlyPrice: 99.99,
    yearlyPrice: 999.99,
    characterQuota: 10000000,
    maxConcurrentJobs: 50,
    priorityQueue: true,
    supportLevel: 'Dedicated',
    features: [
      '10,000,000 characters/month',
      '50 concurrent jobs',
      'Priority queue',
      'Dedicated support',
      'Premium voice quality',
      'Advanced chapter detection',
      'Full API access',
      'Custom voices',
      'White-label options',
      'SLA guarantee'
    ]
  }
};

/**
 * Create a checkout session for a plan
 */
export async function createCheckoutSession(
  planTier: PlanTier,
  billingInterval: BillingInterval
): Promise<CheckoutResponse> {
  const response = await apiClient.post<CheckoutResponse>('/billing/checkout', {
    plan_tier: planTier,
    billing_interval: billingInterval
  });
  return response.data;
}

/**
 * Get current subscription
 */
export async function getSubscription(): Promise<Subscription | null> {
  try {
    const response = await apiClient.get<Subscription>('/billing/subscription');
    return response.data;
  } catch (error) {
    // If no subscription exists (404), return null
    return null;
  }
}

/**
 * Cancel subscription
 */
export async function cancelSubscription(): Promise<void> {
  await apiClient.delete('/billing/subscription');
}

/**
 * Get Stripe customer portal URL
 */
export async function getCustomerPortalUrl(): Promise<string> {
  const response = await apiClient.post<{ portal_url: string }>('/billing/portal');
  return response.data.portal_url;
}

/**
 * Get usage data for current period
 */
export async function getUsageData(): Promise<UsageData> {
  const response = await apiClient.get<UsageData>('/account/usage');
  return response.data;
}

/**
 * Calculate savings for yearly billing
 */
export function calculateYearlySavings(plan: Plan): number {
  const monthlyTotal = plan.monthlyPrice * 12;
  const savings = monthlyTotal - plan.yearlyPrice;
  return savings;
}

/**
 * Format price for display
 */
export function formatPrice(amount: number): string {
  if (amount === 0) return 'Free';
  return `$${amount.toFixed(2)}`;
}

/**
 * Get plan by tier
 */
export function getPlan(tier: PlanTier): Plan {
  return PLANS[tier];
}

/**
 * Check if plan is free
 */
export function isFreePlan(tier: PlanTier): boolean {
  return tier === 'FREE';
}

/**
 * Check if plan is paid
 */
export function isPaidPlan(tier: PlanTier): boolean {
  return tier !== 'FREE';
}

/**
 * Compare plans (for upgrade/downgrade logic)
 */
export function comparePlans(currentTier: PlanTier, newTier: PlanTier): 'upgrade' | 'downgrade' | 'same' {
  const tierOrder: PlanTier[] = ['FREE', 'BASIC', 'PRO', 'ENTERPRISE'];
  const currentIndex = tierOrder.indexOf(currentTier);
  const newIndex = tierOrder.indexOf(newTier);
  
  if (currentIndex === newIndex) return 'same';
  return newIndex > currentIndex ? 'upgrade' : 'downgrade';
}

/**
 * Format subscription status for display
 */
export function formatSubscriptionStatus(status: SubscriptionStatus): string {
  const statusMap: Record<SubscriptionStatus, string> = {
    active: 'Active',
    canceled: 'Canceled',
    past_due: 'Past Due',
    trialing: 'Trial',
    incomplete: 'Incomplete',
    incomplete_expired: 'Expired',
    unpaid: 'Unpaid'
  };
  return statusMap[status] || status;
}
