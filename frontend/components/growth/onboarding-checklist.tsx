/**
 * OnboardingChecklist
 * ====================
 * Progress tracker shown on the dashboard for new users.
 * Drives activation by making the "aha moment" concrete and measurable.
 *
 * Steps:
 *   1. Create account ✓ (always complete by the time this renders)
 *   2. Upload first document
 *   3. Listen to your first audiobook
 *   4. Set up preferences
 *
 * Stored in localStorage so it persists across sessions.
 * Dismissed when all steps complete or user explicitly closes it.
 */

'use client';

import { useState, useEffect } from 'react';
import { CheckCircle2, Circle, ChevronRight, X } from 'lucide-react';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import { Progress } from '@/components/ui/progress';
import { useRouter } from 'next/navigation';
import { track } from '@/lib/analytics';
import { cn } from '@/lib/utils';

interface Step {
  id: string;
  label: string;
  description: string;
  href?: string;
  action?: string;
}

const STEPS: Step[] = [
  {
    id: 'registered',
    label: 'Create your account',
    description: 'You\'re in!',
  },
  {
    id: 'first_upload',
    label: 'Upload your first document',
    description: 'PDF, EPUB or TXT — we handle the rest.',
    href: '/documents',
    action: 'Upload document',
  },
  {
    id: 'first_listen',
    label: 'Listen to your audiobook',
    description: 'Play back a completed conversion.',
    href: '/documents',
    action: 'Go to documents',
  },
  {
    id: 'preferences',
    label: 'Set your voice preference',
    description: 'Choose a TTS voice that sounds right to you.',
    href: '/settings',
    action: 'Open settings',
  },
];

const STORAGE_KEY = '_onboarding_steps';
const DISMISSED_KEY = '_onboarding_dismissed';

function loadCompleted(): Set<string> {
  if (typeof window === 'undefined') return new Set(['registered']);
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    return raw ? new Set(JSON.parse(raw)) : new Set(['registered']);
  } catch {
    return new Set(['registered']);
  }
}

function saveCompleted(completed: Set<string>): void {
  localStorage.setItem(STORAGE_KEY, JSON.stringify([...completed]));
}

export function markOnboardingStep(stepId: string): void {
  const completed = loadCompleted();
  if (!completed.has(stepId)) {
    completed.add(stepId);
    saveCompleted(completed);
  }
}

interface OnboardingChecklistProps {
  className?: string;
}

export function OnboardingChecklist({ className }: OnboardingChecklistProps) {
  const [completed, setCompleted] = useState<Set<string>>(new Set(['registered']));
  const [dismissed, setDismissed] = useState(false);
  const router = useRouter();

  useEffect(() => {
    setCompleted(loadCompleted());
    setDismissed(localStorage.getItem(DISMISSED_KEY) === '1');
  }, []);

  const completedCount = STEPS.filter((s) => completed.has(s.id)).length;
  const pct = Math.round((completedCount / STEPS.length) * 100);
  const allDone = completedCount === STEPS.length;

  useEffect(() => {
    if (allDone) {
      track('onboarding_complete', { steps_completed: completedCount });
    }
  }, [allDone, completedCount]);

  if (dismissed) return null;
  // Don't show if all done for 2+ sessions (banner purpose fulfilled)
  if (allDone && localStorage.getItem('_onboarding_done_session') === '2') return null;

  const handleStepClick = (step: Step) => {
    track('onboarding_step', { step_id: step.id });
    if (step.href) router.push(step.href);
  };

  const handleDismiss = () => {
    localStorage.setItem(DISMISSED_KEY, '1');
    setDismissed(true);
  };

  return (
    <Card className={cn('border-violet-200 dark:border-violet-800', className)}>
      <CardHeader className="pb-3 flex flex-row items-start justify-between">
        <div>
          <CardTitle className="text-base">Get started</CardTitle>
          <p className="text-xs text-muted-foreground mt-0.5">
            Complete these steps to get the most out of Sonoro
          </p>
        </div>
        <button
          onClick={handleDismiss}
          className="text-muted-foreground hover:text-foreground transition-colors -mt-1"
          aria-label="Dismiss checklist"
        >
          <X className="h-4 w-4" />
        </button>
      </CardHeader>

      <CardContent className="space-y-4">
        {/* Progress */}
        <div className="space-y-1">
          <div className="flex justify-between text-xs text-muted-foreground">
            <span>{completedCount} of {STEPS.length} complete</span>
            <span>{pct}%</span>
          </div>
          <Progress value={pct} className="h-1.5" />
        </div>

        {/* Steps */}
        <ul className="space-y-2">
          {STEPS.map((step) => {
            const isDone = completed.has(step.id);
            const isNext = !isDone && STEPS.findIndex((s) => !completed.has(s.id)) === STEPS.indexOf(step);

            return (
              <li
                key={step.id}
                className={cn(
                  'flex items-center gap-3 p-2.5 rounded-lg text-sm transition-colors',
                  isDone ? 'opacity-60' : isNext ? 'bg-violet-50 dark:bg-violet-950/30' : '',
                )}
              >
                {isDone ? (
                  <CheckCircle2 className="h-4 w-4 text-green-500 shrink-0" />
                ) : (
                  <Circle className={cn('h-4 w-4 shrink-0', isNext ? 'text-violet-500' : 'text-muted-foreground')} />
                )}

                <div className="flex-1 min-w-0">
                  <p className={cn('font-medium', isDone && 'line-through')}>{step.label}</p>
                  <p className="text-xs text-muted-foreground truncate">{step.description}</p>
                </div>

                {!isDone && step.href && isNext && (
                  <Button
                    variant="ghost"
                    size="sm"
                    className="h-7 text-xs text-violet-700 dark:text-violet-300 shrink-0"
                    onClick={() => handleStepClick(step)}
                  >
                    {step.action}
                    <ChevronRight className="ml-1 h-3 w-3" />
                  </Button>
                )}
              </li>
            );
          })}
        </ul>
      </CardContent>
    </Card>
  );
}
