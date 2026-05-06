/**
 * Usage Page
 * =========
 * Usage statistics and quota management page (placeholder)
 */

'use client';

import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { BarChart3 } from 'lucide-react';

export default function UsagePage() {
  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-3xl font-bold tracking-tight">Usage</h1>
        <p className="text-muted-foreground mt-2">
          Track your usage and quotas
        </p>
      </div>

      <Card>
        <CardHeader>
          <div className="flex items-center gap-2">
            <BarChart3 className="h-5 w-5" />
            <CardTitle>Usage Statistics</CardTitle>
          </div>
          <CardDescription>
            Monitor your API usage, quotas, and costs
          </CardDescription>
        </CardHeader>
        <CardContent>
          <p className="text-sm text-muted-foreground">
            Usage tracking coming in BLOCK 8D...
          </p>
        </CardContent>
      </Card>
    </div>
  );
}
