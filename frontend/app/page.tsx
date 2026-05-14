/**
 * Landing Page
 * ============
 * Public marketing page with hero, features, pricing preview, and CTA.
 * Authenticated users are redirected to /dashboard.
 *
 * Conversion flow:
 *   Hero CTA → /register → onboarding → first upload (activation event)
 */

'use client';

import { useEffect, useState } from 'react';
import { useRouter } from 'next/navigation';
import Link from 'next/link';
import { useQuery } from '@tanstack/react-query';
import {
  BookOpen, Zap, Shield, Clock, CheckCircle2,
  ArrowRight, Star, Play, Users, BarChart3
} from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Badge } from '@/components/ui/badge';
import { Card, CardContent } from '@/components/ui/card';
import { Separator } from '@/components/ui/separator';
import { useAuthStore } from '@/store/auth-store';
import { fetchTierCatalog, TIER_META, fmtChars, fmtStorage, fmtApiCalls, annualMonthlyRate, annualDiscountPct, type TierConfig } from '@/lib/pricing-service';
import { track, page } from '@/lib/analytics';
import { cn } from '@/lib/utils';

// ── Feature highlights ────────────────────────────────────────────────────────

const FEATURES = [
  {
    icon: Zap,
    title: 'Instant conversion',
    body: 'Upload your PDF or EPUB and get a studio-quality audiobook in minutes, not hours.',
  },
  {
    icon: BookOpen,
    title: 'Smart chapter detection',
    body: 'Our engine automatically detects chapters, headings, and structure for natural narration.',
  },
  {
    icon: Shield,
    title: 'Neural TTS voices',
    body: 'Google Neural2 voices that sound human. Pro and Enterprise plans get neural voices by default.',
  },
  {
    icon: Clock,
    title: 'No waiting rooms',
    body: 'Pro users skip the queue entirely. Your books process first, every time.',
  },
];

// ── Testimonials ──────────────────────────────────────────────────────────────

const TESTIMONIALS = [
  {
    name: 'Sarah M.',
    role: 'Author',
    body: "Converted all 12 books in my series in one afternoon. The voice quality is incredible.",
    stars: 5,
  },
  {
    name: 'David K.',
    role: 'Podcast producer',
    body: "We use Sonoro for every episode brief. 10x faster than manual recording.",
    stars: 5,
  },
  {
    name: 'Priya R.',
    role: 'Educator',
    body: "My students love having textbook chapters they can listen to on the commute.",
    stars: 5,
  },
];

// ── Pricing card ──────────────────────────────────────────────────────────────

type Interval = 'monthly' | 'yearly';

function PricingCard({
  config,
  interval,
}: {
  config: TierConfig;
  interval: Interval;
}) {
  const router = useRouter();
  const meta = TIER_META[config.tier];
  const price = interval === 'yearly' ? annualMonthlyRate(config) : config.monthly_price_usd;
  const discount = annualDiscountPct(config);
  const isFree = config.monthly_price_usd === 0;

  const handleCTA = () => {
    track('upgrade_intent', {
      source: 'landing_pricing',
      target_tier: config.tier,
      interval,
    });
    router.push('/register');
  };

  const featureLines = [
    `${fmtChars(config.limits.monthly_chars)} characters/month`,
    `${config.limits.monthly_jobs} conversions/month`,
    fmtStorage(config.limits.storage_mb) + ' storage',
    fmtApiCalls(config.limits.daily_api_calls),
    `${config.limits.concurrent_jobs} concurrent job${config.limits.concurrent_jobs !== 1 ? 's' : ''}`,
    ...config.features.slice(0, 3).map(f => f.replace(/_/g, ' ')),
  ];

  return (
    <div
      className={cn(
        'relative rounded-2xl border p-6 flex flex-col gap-5 transition-all',
        meta.highlight
          ? 'border-violet-500 bg-gradient-to-b from-violet-50 to-white dark:from-violet-950/40 dark:to-background shadow-xl shadow-violet-100/50 dark:shadow-none scale-[1.02]'
          : 'border-border bg-card',
      )}
    >
      {meta.badge && (
        <div className="absolute -top-3.5 inset-x-0 flex justify-center">
          <Badge className="bg-violet-600 text-white px-3 text-xs">{meta.badge}</Badge>
        </div>
      )}

      <div>
        <p className="font-bold text-lg">{meta.name}</p>
        <p className="text-sm text-muted-foreground mt-0.5">{meta.tagline}</p>
      </div>

      <div className="flex items-baseline gap-1">
        <span className="text-4xl font-extrabold">
          {isFree ? 'Free' : `$${price.toFixed(price % 1 === 0 ? 0 : 2)}`}
        </span>
        {!isFree && <span className="text-muted-foreground text-sm">/month</span>}
        {interval === 'yearly' && !isFree && discount > 0 && (
          <Badge variant="secondary" className="ml-2 text-xs">
            Save {discount}%
          </Badge>
        )}
      </div>

      <ul className="space-y-2.5 flex-1">
        {featureLines.map((f) => (
          <li key={f} className="flex items-start gap-2 text-sm">
            <CheckCircle2 className="h-4 w-4 text-green-500 mt-0.5 shrink-0" />
            <span className="capitalize">{f}</span>
          </li>
        ))}
      </ul>

      <Button
        className={cn(
          'w-full',
          meta.highlight
            ? 'bg-violet-600 hover:bg-violet-700 text-white'
            : 'variant-outline',
        )}
        variant={meta.highlight ? 'default' : 'outline'}
        onClick={handleCTA}
      >
        {isFree ? 'Start free' : 'Get started'}
        <ArrowRight className="ml-2 h-4 w-4" />
      </Button>
    </div>
  );
}

// ── Page ──────────────────────────────────────────────────────────────────────

export default function LandingPage() {
  const router = useRouter();
  const { isAuthenticated, isLoading } = useAuthStore();
  const [interval, setInterval] = useState<Interval>('yearly');

  // Redirect authenticated users
  useEffect(() => {
    if (!isLoading && isAuthenticated) {
      router.replace('/dashboard');
    }
  }, [isAuthenticated, isLoading, router]);

  useEffect(() => {
    page('/');
  }, []);

  const { data: catalog } = useQuery({
    queryKey: ['tier-catalog'],
    queryFn: fetchTierCatalog,
    staleTime: 300_000,
  });

  const tiers = catalog ?? [];

  if (isLoading) {
    return (
      <div className="flex h-screen items-center justify-center">
        <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-violet-600" />
      </div>
    );
  }

  if (isAuthenticated) return null; // redirect in progress

  return (
    <div className="min-h-screen bg-background">
      {/* ── Nav ─────────────────────────────────────────────────────────────── */}
      <nav className="sticky top-0 z-50 border-b bg-background/80 backdrop-blur-md">
        <div className="max-w-6xl mx-auto px-4 flex items-center justify-between h-14">
          <Link href="/" className="flex items-center gap-2 font-bold text-lg">
            <BookOpen className="h-5 w-5 text-violet-600" />
            Sonoro
          </Link>
          <div className="flex items-center gap-3">
            <Button variant="ghost" size="sm" asChild>
              <Link href="/login">Sign in</Link>
            </Button>
            <Button
              size="sm"
              className="bg-violet-600 hover:bg-violet-700 text-white"
              asChild
              onClick={() => track('upgrade_intent', { source: 'nav_cta' })}
            >
              <Link href="/register">Start free</Link>
            </Button>
          </div>
        </div>
      </nav>

      {/* ── Hero ────────────────────────────────────────────────────────────── */}
      <section className="max-w-6xl mx-auto px-4 pt-20 pb-16 text-center">
        <Badge variant="secondary" className="mb-4 text-sm">
          ✨ Neural TTS powered by Google Cloud
        </Badge>
        <h1 className="text-5xl sm:text-6xl font-extrabold tracking-tight leading-tight mb-6">
          Turn any book into{' '}
          <span className="bg-gradient-to-r from-violet-600 to-purple-600 bg-clip-text text-transparent">
            an audiobook
          </span>
          <br />in minutes
        </h1>
        <p className="text-xl text-muted-foreground max-w-2xl mx-auto mb-8">
          Upload a PDF, EPUB, or TXT file. Sonoro's AI detects chapters, applies natural
          narration, and delivers studio-quality audio — automatically.
        </p>
        <div className="flex flex-col sm:flex-row items-center justify-center gap-3">
          <Button
            size="lg"
            className="bg-violet-600 hover:bg-violet-700 text-white h-12 px-8 text-base"
            asChild
            onClick={() => track('upgrade_intent', { source: 'hero_cta' })}
          >
            <Link href="/register">
              Start for free
              <ArrowRight className="ml-2 h-5 w-5" />
            </Link>
          </Button>
          <Button variant="outline" size="lg" className="h-12 px-8 text-base gap-2" asChild>
            <Link href="#pricing">
              <Play className="h-4 w-4" />
              See pricing
            </Link>
          </Button>
        </div>
        <p className="mt-4 text-sm text-muted-foreground">
          No credit card required · 10,000 characters free every month
        </p>
      </section>

      {/* ── Social proof strip ───────────────────────────────────────────────── */}
      <section className="border-y bg-muted/30 py-8">
        <div className="max-w-6xl mx-auto px-4 flex flex-wrap items-center justify-center gap-8 text-sm text-muted-foreground">
          <div className="flex items-center gap-2">
            <Users className="h-4 w-4" />
            <span><strong className="text-foreground">2,000+</strong> active users</span>
          </div>
          <Separator orientation="vertical" className="h-5 hidden sm:block" />
          <div className="flex items-center gap-2">
            <BarChart3 className="h-4 w-4" />
            <span><strong className="text-foreground">500K+</strong> books converted</span>
          </div>
          <Separator orientation="vertical" className="h-5 hidden sm:block" />
          <div className="flex items-center gap-1.5">
            {Array.from({ length: 5 }).map((_, i) => (
              <Star key={i} className="h-4 w-4 fill-yellow-400 text-yellow-400" />
            ))}
            <span className="ml-1"><strong className="text-foreground">4.9</strong> / 5</span>
          </div>
        </div>
      </section>

      {/* ── Features ────────────────────────────────────────────────────────── */}
      <section className="max-w-6xl mx-auto px-4 py-20">
        <div className="text-center mb-12">
          <h2 className="text-3xl font-bold mb-3">Everything you need</h2>
          <p className="text-muted-foreground max-w-xl mx-auto">
            Sonoro handles the hard parts — you just upload and listen.
          </p>
        </div>
        <div className="grid md:grid-cols-2 lg:grid-cols-4 gap-6">
          {FEATURES.map((f) => {
            const Icon = f.icon;
            return (
              <Card key={f.title}>
                <CardContent className="pt-6">
                  <div className="h-10 w-10 rounded-lg bg-violet-100 dark:bg-violet-900/30 flex items-center justify-center mb-4">
                    <Icon className="h-5 w-5 text-violet-600 dark:text-violet-400" />
                  </div>
                  <p className="font-semibold mb-1.5">{f.title}</p>
                  <p className="text-sm text-muted-foreground">{f.body}</p>
                </CardContent>
              </Card>
            );
          })}
        </div>
      </section>

      {/* ── Pricing ─────────────────────────────────────────────────────────── */}
      <section id="pricing" className="max-w-6xl mx-auto px-4 py-20">
        <div className="text-center mb-10">
          <h2 className="text-3xl font-bold mb-3">Simple, transparent pricing</h2>
          <p className="text-muted-foreground mb-6">
            Start free. Upgrade when you need more.
          </p>
          {/* Billing toggle */}
          <div className="inline-flex items-center gap-1 p-1 bg-muted rounded-lg text-sm">
            <button
              onClick={() => setInterval('monthly')}
              className={cn(
                'px-4 py-1.5 rounded-md transition-all',
                interval === 'monthly' ? 'bg-background shadow font-medium' : 'text-muted-foreground',
              )}
            >
              Monthly
            </button>
            <button
              onClick={() => setInterval('yearly')}
              className={cn(
                'px-4 py-1.5 rounded-md transition-all flex items-center gap-2',
                interval === 'yearly' ? 'bg-background shadow font-medium' : 'text-muted-foreground',
              )}
            >
              Annual
              <Badge className="bg-green-500/20 text-green-700 dark:text-green-400 text-xs px-1.5 py-0">
                Save 20%
              </Badge>
            </button>
          </div>
        </div>

        {tiers.length > 0 ? (
          <div className="grid md:grid-cols-2 lg:grid-cols-4 gap-6 items-start">
            {tiers.map((cfg) => (
              <PricingCard key={cfg.tier} config={cfg} interval={interval} />
            ))}
          </div>
        ) : (
          /* Skeleton while catalog loads */
          <div className="grid md:grid-cols-2 lg:grid-cols-4 gap-6">
            {Array.from({ length: 4 }).map((_, i) => (
              <div key={i} className="h-96 rounded-2xl border bg-muted/30 animate-pulse" />
            ))}
          </div>
        )}
      </section>

      {/* ── Testimonials ────────────────────────────────────────────────────── */}
      <section className="bg-muted/30 border-y py-20">
        <div className="max-w-6xl mx-auto px-4">
          <h2 className="text-3xl font-bold text-center mb-10">Loved by creators</h2>
          <div className="grid md:grid-cols-3 gap-6">
            {TESTIMONIALS.map((t) => (
              <Card key={t.name} className="bg-background">
                <CardContent className="pt-6 space-y-4">
                  <div className="flex">
                    {Array.from({ length: t.stars }).map((_, i) => (
                      <Star key={i} className="h-4 w-4 fill-yellow-400 text-yellow-400" />
                    ))}
                  </div>
                  <p className="text-sm text-muted-foreground italic">"{t.body}"</p>
                  <div>
                    <p className="font-semibold text-sm">{t.name}</p>
                    <p className="text-xs text-muted-foreground">{t.role}</p>
                  </div>
                </CardContent>
              </Card>
            ))}
          </div>
        </div>
      </section>

      {/* ── Final CTA ───────────────────────────────────────────────────────── */}
      <section className="max-w-6xl mx-auto px-4 py-24 text-center">
        <h2 className="text-4xl font-extrabold mb-4">
          Start converting books today
        </h2>
        <p className="text-muted-foreground text-lg mb-8 max-w-xl mx-auto">
          Free plan. No credit card. Your first 10,000 characters every month at zero cost.
        </p>
        <Button
          size="lg"
          className="bg-violet-600 hover:bg-violet-700 text-white h-12 px-10 text-base"
          asChild
          onClick={() => track('upgrade_intent', { source: 'footer_cta' })}
        >
          <Link href="/register">
            Get started for free
            <ArrowRight className="ml-2 h-5 w-5" />
          </Link>
        </Button>
      </section>

      {/* ── Footer ──────────────────────────────────────────────────────────── */}
      <footer className="border-t py-8">
        <div className="max-w-6xl mx-auto px-4 flex flex-col sm:flex-row items-center justify-between gap-4 text-sm text-muted-foreground">
          <div className="flex items-center gap-2">
            <BookOpen className="h-4 w-4 text-violet-600" />
            <span className="font-medium text-foreground">Sonoro</span>
            <span>© {new Date().getFullYear()}</span>
          </div>
          <div className="flex gap-6">
            <Link href="/login" className="hover:text-foreground transition-colors">Sign in</Link>
            <Link href="/register" className="hover:text-foreground transition-colors">Register</Link>
            <Link href="#pricing" className="hover:text-foreground transition-colors">Pricing</Link>
          </div>
        </div>
      </footer>
    </div>
  );
}
