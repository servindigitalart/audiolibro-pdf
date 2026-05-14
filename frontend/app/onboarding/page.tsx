/**
 * Onboarding Wizard
 * =================
 * Multi-step activation flow shown once after registration.
 * Goal: reach the "aha moment" (first successful upload) in < 60 seconds.
 *
 * Steps:
 *   1. Welcome — reinforce value prop, reduce buyer's remorse
 *   2. First upload — primary activation event
 *   3. Voice preference — personalisation drives retention
 *   4. Upgrade prompt — shown if user is near free limit, else skipped
 *   5. Done — redirect to dashboard
 *
 * Progress persisted to localStorage so it survives page refresh.
 */

'use client';

import { useState, useEffect, useCallback } from 'react';
import { useRouter } from 'next/navigation';
import { BookOpen, Upload, Mic, Zap, CheckCircle2, ArrowRight, ArrowLeft, X } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Progress } from '@/components/ui/progress';
import { Card, CardContent } from '@/components/ui/card';
import { Badge } from '@/components/ui/badge';
import { useAuthStore } from '@/store/auth-store';
import { track } from '@/lib/analytics';
import { cn } from '@/lib/utils';

// ── Step definitions ──────────────────────────────────────────────────────────

type StepId = 'welcome' | 'upload' | 'voice' | 'upgrade' | 'done';

interface Step {
  id: StepId;
  title: string;
  subtitle: string;
  icon: typeof BookOpen;
}

const STEPS: Step[] = [
  {
    id: 'welcome',
    title: "You're in! Let's get your first audiobook ready.",
    subtitle: 'Sonoro converts your PDFs and EPUBs into natural-sounding audio. It takes about 2 minutes.',
    icon: BookOpen,
  },
  {
    id: 'upload',
    title: 'Upload your first document',
    subtitle: 'Drop in any PDF, EPUB, or TXT file. We\'ll detect chapters and structure automatically.',
    icon: Upload,
  },
  {
    id: 'voice',
    title: 'Choose your narrator voice',
    subtitle: 'Pick a default voice for your conversions. You can always change it per-document.',
    icon: Mic,
  },
  {
    id: 'upgrade',
    title: 'Want more conversions?',
    subtitle: 'The free plan gives you 10,000 characters/month. Upgrade any time to unlock more.',
    icon: Zap,
  },
  {
    id: 'done',
    title: "You're all set!",
    subtitle: 'Your dashboard is ready. Upload documents, track progress, and listen to your audiobooks.',
    icon: CheckCircle2,
  },
];

const STORAGE_KEY = '_onboarding_step';

// ── Step components ───────────────────────────────────────────────────────────

function WelcomeStep({ onNext }: { onNext: () => void }) {
  const { user } = useAuthStore();
  const name = user?.email?.split('@')[0] ?? 'there';

  return (
    <div className="text-center space-y-6">
      <div className="h-20 w-20 rounded-full bg-violet-100 dark:bg-violet-900/30 mx-auto flex items-center justify-center">
        <BookOpen className="h-10 w-10 text-violet-600" />
      </div>
      <div>
        <h2 className="text-2xl font-bold mb-2">Welcome, {name}! 👋</h2>
        <p className="text-muted-foreground max-w-sm mx-auto">
          You now have access to neural text-to-speech conversion. Let's get your first audiobook ready.
        </p>
      </div>

      {/* Value propositions */}
      <div className="grid grid-cols-3 gap-3 max-w-sm mx-auto text-sm">
        {[
          { icon: '⚡', label: 'Minutes not hours' },
          { icon: '🎙️', label: 'Neural TTS voices' },
          { icon: '📚', label: 'Any PDF or EPUB' },
        ].map((v) => (
          <div key={v.label} className="flex flex-col items-center gap-1.5 p-3 rounded-xl bg-muted/50">
            <span className="text-xl">{v.icon}</span>
            <span className="text-xs text-muted-foreground">{v.label}</span>
          </div>
        ))}
      </div>

      <Button
        size="lg"
        className="bg-violet-600 hover:bg-violet-700 text-white w-full max-w-xs mx-auto"
        onClick={onNext}
      >
        Let's go
        <ArrowRight className="ml-2 h-4 w-4" />
      </Button>
      <p className="text-xs text-muted-foreground">Takes about 2 minutes</p>
    </div>
  );
}

function UploadStep({ onNext }: { onNext: () => void }) {
  const router = useRouter();
  const handleUploadNow = () => {
    track('onboarding_step', { step_id: 'upload', action: 'upload_now' });
    router.push('/documents');
  };

  return (
    <div className="space-y-6">
      <div className="border-2 border-dashed border-violet-300 dark:border-violet-700 rounded-xl p-10 text-center bg-violet-50/50 dark:bg-violet-950/20">
        <Upload className="h-10 w-10 text-violet-500 mx-auto mb-3" />
        <p className="font-medium mb-1">Drop your document here</p>
        <p className="text-sm text-muted-foreground mb-4">PDF, EPUB, or TXT — up to 50MB</p>
        <Button
          className="bg-violet-600 hover:bg-violet-700 text-white"
          onClick={handleUploadNow}
        >
          Choose file
        </Button>
      </div>

      <div className="flex items-center gap-3 text-sm text-muted-foreground">
        <div className="h-px flex-1 bg-border" />
        <span>or</span>
        <div className="h-px flex-1 bg-border" />
      </div>

      <Button variant="outline" className="w-full" onClick={onNext}>
        Skip for now, I'll upload later
      </Button>
    </div>
  );
}

const VOICES = [
  { id: 'en-US-Neural2-D', label: 'Male (US)', sample: 'Deep, authoritative narrator' },
  { id: 'en-US-Neural2-F', label: 'Female (US)', sample: 'Clear, professional narrator' },
  { id: 'en-GB-Neural2-A', label: 'Female (UK)', sample: 'Warm, engaging narrator' },
  { id: 'en-GB-Neural2-B', label: 'Male (UK)', sample: 'Rich, storytelling voice' },
];

function VoiceStep({ onNext }: { onNext: () => void }) {
  const [selected, setSelected] = useState(VOICES[0].id);

  const handleContinue = () => {
    track('onboarding_step', { step_id: 'voice', voice: selected });
    // In production: POST to /api/v1/account/preferences { preferred_voice: selected }
    onNext();
  };

  return (
    <div className="space-y-4">
      <div className="grid gap-2">
        {VOICES.map((v) => (
          <button
            key={v.id}
            onClick={() => setSelected(v.id)}
            className={cn(
              'flex items-center gap-3 p-3.5 rounded-xl border text-left transition-all',
              selected === v.id
                ? 'border-violet-500 bg-violet-50 dark:bg-violet-950/30'
                : 'border-border hover:border-violet-300',
            )}
          >
            <div
              className={cn(
                'h-8 w-8 rounded-full border-2 flex items-center justify-center shrink-0',
                selected === v.id ? 'border-violet-500' : 'border-muted',
              )}
            >
              <Mic className={cn('h-4 w-4', selected === v.id ? 'text-violet-500' : 'text-muted-foreground')} />
            </div>
            <div>
              <p className="font-medium text-sm">{v.label}</p>
              <p className="text-xs text-muted-foreground">{v.sample}</p>
            </div>
            {selected === v.id && (
              <CheckCircle2 className="ml-auto h-4 w-4 text-violet-500 shrink-0" />
            )}
          </button>
        ))}
      </div>
      <Button
        className="w-full bg-violet-600 hover:bg-violet-700 text-white"
        onClick={handleContinue}
      >
        Save preference
        <ArrowRight className="ml-2 h-4 w-4" />
      </Button>
    </div>
  );
}

function UpgradeStep({ onNext, onSkip }: { onNext: () => void; onSkip: () => void }) {
  const router = useRouter();
  return (
    <div className="space-y-5">
      <div className="grid grid-cols-2 gap-3 text-sm">
        {/* Free */}
        <div className="rounded-xl border p-4 space-y-2">
          <Badge variant="secondary">Free</Badge>
          <p className="font-semibold text-lg">$0</p>
          <ul className="space-y-1 text-muted-foreground">
            <li>✓ 10K characters/mo</li>
            <li>✓ 5 conversions</li>
            <li>✓ 100MB storage</li>
          </ul>
        </div>
        {/* Pro */}
        <div className="rounded-xl border-2 border-violet-500 p-4 space-y-2 bg-violet-50 dark:bg-violet-950/30">
          <Badge className="bg-violet-600 text-white">Pro</Badge>
          <p className="font-semibold text-lg">$29<span className="text-sm font-normal text-muted-foreground">/mo</span></p>
          <ul className="space-y-1 text-muted-foreground">
            <li>✓ 500K characters/mo</li>
            <li>✓ 200 conversions</li>
            <li>✓ 10GB storage</li>
            <li>✓ Priority queue</li>
          </ul>
        </div>
      </div>

      <Button
        className="w-full bg-violet-600 hover:bg-violet-700 text-white"
        onClick={() => {
          track('upgrade_intent', { source: 'onboarding' });
          router.push('/billing');
        }}
      >
        <Zap className="mr-2 h-4 w-4" />
        Upgrade to Pro
      </Button>
      <Button variant="ghost" className="w-full text-muted-foreground" onClick={onSkip}>
        Continue on free plan
      </Button>
    </div>
  );
}

function DoneStep() {
  const router = useRouter();
  return (
    <div className="text-center space-y-6">
      <div className="h-20 w-20 rounded-full bg-green-100 dark:bg-green-900/30 mx-auto flex items-center justify-center">
        <CheckCircle2 className="h-10 w-10 text-green-600" />
      </div>
      <div>
        <h2 className="text-2xl font-bold mb-2">You're all set! 🎉</h2>
        <p className="text-muted-foreground max-w-sm mx-auto">
          Your account is configured. Head to your dashboard to start converting documents.
        </p>
      </div>
      <Button
        size="lg"
        className="bg-violet-600 hover:bg-violet-700 text-white w-full max-w-xs mx-auto"
        onClick={() => router.push('/dashboard')}
      >
        Go to dashboard
        <ArrowRight className="ml-2 h-4 w-4" />
      </Button>
    </div>
  );
}

// ── Wizard ────────────────────────────────────────────────────────────────────

export default function OnboardingPage() {
  const router = useRouter();
  const { user, isAuthenticated, isLoading } = useAuthStore();
  const [stepIndex, setStepIndex] = useState(0);

  const visibleSteps = STEPS.filter((s) => s.id !== 'done');

  useEffect(() => {
    if (!isLoading && !isAuthenticated) router.replace('/login');
  }, [isAuthenticated, isLoading, router]);

  useEffect(() => {
    const saved = sessionStorage.getItem(STORAGE_KEY);
    if (saved) setStepIndex(Math.min(parseInt(saved, 10), STEPS.length - 1));
  }, []);

  const currentStep = STEPS[stepIndex];

  const advance = useCallback(() => {
    const next = Math.min(stepIndex + 1, STEPS.length - 1);
    setStepIndex(next);
    sessionStorage.setItem(STORAGE_KEY, String(next));
    track('onboarding_step', { step_id: STEPS[next].id, step_index: next });

    if (STEPS[next].id === 'done') {
      track('onboarding_complete', {});
      sessionStorage.removeItem(STORAGE_KEY);
    }
  }, [stepIndex]);

  const goBack = () => setStepIndex((i) => Math.max(i - 1, 0));

  const skip = () => {
    track('onboarding_complete', { skipped: true });
    sessionStorage.removeItem(STORAGE_KEY);
    router.push('/dashboard');
  };

  if (isLoading) return null;

  const progressPct = ((stepIndex) / (STEPS.length - 1)) * 100;

  return (
    <div className="min-h-screen bg-background flex items-center justify-center p-4">
      <div className="w-full max-w-md">
        {/* Header */}
        <div className="flex items-center justify-between mb-6">
          <div className="flex items-center gap-2 font-bold">
            <BookOpen className="h-5 w-5 text-violet-600" />
            <span>Sonoro</span>
          </div>
          <button
            onClick={skip}
            className="text-muted-foreground hover:text-foreground transition-colors flex items-center gap-1 text-sm"
          >
            Skip setup
            <X className="h-4 w-4" />
          </button>
        </div>

        {/* Progress */}
        {currentStep.id !== 'done' && (
          <div className="mb-6 space-y-1.5">
            <div className="flex justify-between text-xs text-muted-foreground">
              <span>Step {stepIndex + 1} of {visibleSteps.length}</span>
              <span>{Math.round(progressPct)}% complete</span>
            </div>
            <Progress value={progressPct} className="h-1.5" />
          </div>
        )}

        {/* Step card */}
        <Card>
          <CardContent className="pt-8 pb-6 px-6">
            {/* Step icon + title */}
            {currentStep.id !== 'welcome' && currentStep.id !== 'done' && (
              <div className="text-center mb-6">
                <h2 className="text-xl font-bold mb-1">{currentStep.title}</h2>
                <p className="text-sm text-muted-foreground">{currentStep.subtitle}</p>
              </div>
            )}

            {/* Step content */}
            {currentStep.id === 'welcome' && <WelcomeStep onNext={advance} />}
            {currentStep.id === 'upload'  && <UploadStep onNext={advance} />}
            {currentStep.id === 'voice'   && <VoiceStep onNext={advance} />}
            {currentStep.id === 'upgrade' && <UpgradeStep onNext={advance} onSkip={advance} />}
            {currentStep.id === 'done'    && <DoneStep />}
          </CardContent>
        </Card>

        {/* Back nav */}
        {stepIndex > 0 && currentStep.id !== 'done' && (
          <button
            onClick={goBack}
            className="mt-4 text-sm text-muted-foreground hover:text-foreground transition-colors flex items-center gap-1 mx-auto"
          >
            <ArrowLeft className="h-3.5 w-3.5" />
            Back
          </button>
        )}
      </div>
    </div>
  );
}
