/**
 * Chapter Navigation Component
 * ===========================
 * Navigate between audiobook chapters on desktop (sidebar list) and mobile
 * (bottom sheet triggered by a Chapters button).
 *
 * Label rules:
 *  - Single chapter: shows "Complete audiobook" — no navigation.
 *  - Multiple chapters with detection_method != null: use chapter title.
 *  - Multiple chapters without real detection (fallback): label as "Part N".
 */

'use client';

import { useState } from 'react';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { ScrollArea } from '@/components/ui/scroll-area';
import {
  Sheet,
  SheetContent,
  SheetHeader,
  SheetTitle,
  SheetTrigger,
} from '@/components/ui/sheet';
import { BookOpen, Clock, ChevronDown, ChevronUp, List } from 'lucide-react';
import { cn } from '@/lib/utils';
import { track } from '@/lib/analytics';
import type { Chapter } from '@/lib/document-service';

interface ChapterNavigationProps {
  chapters: Chapter[];
  currentChapter?: number | null;
  onChapterSelect: (chapterNumber: number, timestamp: number) => void;
  className?: string;
}

function formatDuration(seconds?: number): string {
  if (!seconds) return '';
  const h = Math.floor(seconds / 3600);
  const m = Math.floor((seconds % 3600) / 60);
  const s = Math.floor(seconds % 60);
  if (h > 0) return `${h}h ${m}m`;
  if (m > 0) return `${m}m ${s}s`;
  return `${s}s`;
}

function isFallbackChapter(ch: Chapter): boolean {
  // A chapter is a fallback (no real structure detection) when:
  // - detection_method is null/undefined, OR
  // - the title is exactly "Chapter N" (generated placeholder)
  return !ch.detection_method || /^Chapter \d+$/.test(ch.title);
}

function chapterLabel(ch: Chapter, isFallback: boolean): string {
  if (isFallback) return `Part ${ch.chapter_number}`;
  return ch.title;
}

function getTimestamp(ch: Chapter, allChapters: Chapter[]): number {
  // Prefer explicit start_time_seconds from backend (set after TTS)
  if (ch.start_time_seconds != null) return ch.start_time_seconds;

  // Fall back to cumulative duration sum
  const sorted = [...allChapters].sort((a, b) => a.chapter_number - b.chapter_number);
  let cum = 0;
  for (const c of sorted) {
    if (c.chapter_number === ch.chapter_number) return cum;
    cum += c.duration_seconds ?? 0;
  }
  return 0;
}

// ── Chapter list rows (shared between desktop sidebar and mobile sheet) ────────

interface ChapterListProps {
  chapters: Chapter[];
  currentChapter?: number | null;
  onSelect: (ch: Chapter, ts: number) => void;
  allFallback: boolean;
}

function ChapterList({ chapters, currentChapter, onSelect, allFallback }: ChapterListProps) {
  const sorted = [...chapters].sort((a, b) => a.chapter_number - b.chapter_number);

  return (
    <div className="space-y-1.5">
      {sorted.map(ch => {
        const isActive = currentChapter === ch.chapter_number;
        const fallback = allFallback || isFallbackChapter(ch);
        const label = chapterLabel(ch, fallback);
        const ts = getTimestamp(ch, chapters);
        const dur = formatDuration(ch.duration_seconds);

        return (
          <button
            key={ch.id}
            onClick={() => onSelect(ch, ts)}
            className={cn(
              'w-full text-left p-3 rounded-lg border transition-all',
              'hover:shadow-sm hover:border-primary/50',
              'focus:outline-none focus:ring-2 focus:ring-primary focus:ring-offset-2',
              isActive
                ? 'bg-primary/10 border-primary shadow-sm'
                : 'bg-card border-border hover:bg-accent',
            )}
          >
            <div className="flex items-start justify-between gap-2">
              <div className="flex-1 min-w-0 space-y-0.5">
                <div className="flex items-center gap-2">
                  <span className={cn(
                    'text-xs font-medium px-2 py-0.5 rounded-full shrink-0',
                    isActive ? 'bg-primary text-primary-foreground' : 'bg-muted text-muted-foreground',
                  )}>
                    {fallback ? `Part ${ch.chapter_number}` : ch.chapter_number}
                  </span>
                  {isActive && (
                    <Badge variant="secondary" className="text-xs">Playing</Badge>
                  )}
                </div>

                {!fallback && (
                  <p className={cn('font-medium text-sm line-clamp-2', isActive && 'text-primary')}>
                    {label}
                  </p>
                )}

                <div className="flex flex-wrap items-center gap-2 text-xs text-muted-foreground">
                  <span>pp. {ch.start_page}–{ch.end_page}</span>
                  {dur && (
                    <>
                      <span>·</span>
                      <span className="flex items-center gap-0.5">
                        <Clock className="h-3 w-3" />{dur}
                      </span>
                    </>
                  )}
                </div>
              </div>
            </div>
          </button>
        );
      })}
    </div>
  );
}

// ── Main export ────────────────────────────────────────────────────────────────

export function ChapterNavigation({
  chapters,
  currentChapter,
  onChapterSelect,
  className,
}: ChapterNavigationProps) {
  const [isExpanded, setIsExpanded] = useState(true);

  if (chapters.length === 0) {
    return (
      <Card className={className}>
        <CardContent className="p-6 text-center text-muted-foreground">
          <BookOpen className="h-12 w-12 mx-auto mb-3 opacity-50" />
          <p>No chapters detected</p>
        </CardContent>
      </Card>
    );
  }

  // Single chapter → show "Complete audiobook" without nav
  if (chapters.length === 1) {
    return (
      <Card className={className}>
        <CardContent className="p-6 text-center text-muted-foreground space-y-2">
          <BookOpen className="h-10 w-10 mx-auto opacity-50" />
          <p className="font-medium">Complete audiobook</p>
          {chapters[0].duration_seconds && (
            <p className="text-sm">{formatDuration(chapters[0].duration_seconds)}</p>
          )}
        </CardContent>
      </Card>
    );
  }

  // Determine if all chapters are fallback (no real structure)
  const allFallback = chapters.every(isFallbackChapter);

  const handleSelect = (ch: Chapter, ts: number) => {
    track('chapter_selected', {
      chapter_number: ch.chapter_number,
      detection_method: ch.detection_method ?? 'fallback',
    });
    onChapterSelect(ch.chapter_number, ts);
  };

  const panelTitle = allFallback ? 'Parts' : 'Chapters';

  return (
    <>
      {/* ── Desktop sidebar ───────────────────────────────────────────────── */}
      <Card className={cn('hidden lg:block', className)}>
        <CardHeader className="pb-3">
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-2">
              <BookOpen className="h-5 w-5 text-primary" />
              <CardTitle className="text-lg">
                {panelTitle}
                <span className="ml-2 text-sm font-normal text-muted-foreground">
                  ({chapters.length})
                </span>
              </CardTitle>
            </div>
            <Button
              variant="ghost"
              size="sm"
              onClick={() => {
                if (!isExpanded) track('chapter_panel_opened', { via: 'desktop_expand' });
                setIsExpanded(!isExpanded);
              }}
              className="h-8 w-8 p-0"
              aria-label={isExpanded ? 'Collapse chapters' : 'Expand chapters'}
            >
              {isExpanded ? <ChevronUp className="h-4 w-4" /> : <ChevronDown className="h-4 w-4" />}
            </Button>
          </div>
        </CardHeader>

        {isExpanded && (
          <CardContent className="pt-0">
            <ScrollArea className="h-[400px] pr-2">
              <ChapterList
                chapters={chapters}
                currentChapter={currentChapter}
                onSelect={handleSelect}
                allFallback={allFallback}
              />
            </ScrollArea>
          </CardContent>
        )}
      </Card>

      {/* ── Mobile sheet trigger ──────────────────────────────────────────── */}
      <div className="lg:hidden">
        <Sheet>
          <SheetTrigger asChild>
            <Button
              variant="outline"
              size="sm"
              onClick={() => track('chapter_panel_opened', { via: 'mobile_sheet' })}
              className="w-full"
            >
              <List className="h-4 w-4 mr-2" />
              {panelTitle}
              {currentChapter != null && (
                <span className="ml-2 text-muted-foreground">
                  · {allFallback ? `Part ${currentChapter}` : `#${currentChapter}`}
                </span>
              )}
            </Button>
          </SheetTrigger>
          <SheetContent side="bottom" className="h-[70vh] rounded-t-2xl">
            <SheetHeader className="pb-4">
              <SheetTitle className="flex items-center gap-2">
                <BookOpen className="h-5 w-5 text-primary" />
                {panelTitle} ({chapters.length})
              </SheetTitle>
            </SheetHeader>
            <ScrollArea className="h-full pb-8">
              <ChapterList
                chapters={chapters}
                currentChapter={currentChapter}
                onSelect={handleSelect}
                allFallback={allFallback}
              />
            </ScrollArea>
          </SheetContent>
        </Sheet>
      </div>
    </>
  );
}
