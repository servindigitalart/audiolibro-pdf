/**
 * Chapter Navigation Component
 * ===========================
 * Navigate between audiobook chapters with visual feedback
 */

'use client';

import { useState } from 'react';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { ScrollArea } from '@/components/ui/scroll-area';
import { BookOpen, Clock, ChevronDown, ChevronUp } from 'lucide-react';
import { cn } from '@/lib/utils';
import type { Chapter } from '@/lib/document-service';

interface ChapterNavigationProps {
  chapters: Chapter[];
  currentChapter?: number | null;
  onChapterSelect: (chapterNumber: number, timestamp: number) => void;
  className?: string;
}

export function ChapterNavigation({
  chapters,
  currentChapter,
  onChapterSelect,
  className,
}: ChapterNavigationProps) {
  const [isExpanded, setIsExpanded] = useState(true);

  const formatDuration = (seconds?: number) => {
    if (!seconds) return 'N/A';
    const hrs = Math.floor(seconds / 3600);
    const mins = Math.floor((seconds % 3600) / 60);
    const secs = Math.floor(seconds % 60);
    
    if (hrs > 0) {
      return `${hrs}h ${mins}m`;
    }
    if (mins > 0) {
      return `${mins}m ${secs}s`;
    }
    return `${secs}s`;
  };

  const getChapterTimestamp = (chapterIndex: number): number => {
    // Calculate cumulative timestamp for chapter
    let timestamp = 0;
    for (let i = 0; i < chapterIndex; i++) {
      timestamp += chapters[i].duration_seconds || 0;
    }
    return timestamp;
  };

  const getConfidenceColor = (score: number): string => {
    if (score >= 0.9) return 'text-green-600 dark:text-green-400';
    if (score >= 0.7) return 'text-yellow-600 dark:text-yellow-400';
    return 'text-orange-600 dark:text-orange-400';
  };

  const sortedChapters = [...chapters].sort((a, b) => a.chapter_number - b.chapter_number);

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

  return (
    <Card className={className}>
      <CardHeader className="pb-3">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-2">
            <BookOpen className="h-5 w-5 text-primary" />
            <CardTitle className="text-lg">
              Chapters
              <span className="ml-2 text-sm font-normal text-muted-foreground">
                ({chapters.length})
              </span>
            </CardTitle>
          </div>
          <Button
            variant="ghost"
            size="sm"
            onClick={() => setIsExpanded(!isExpanded)}
            className="h-8 w-8 p-0"
            aria-label={isExpanded ? 'Collapse chapters' : 'Expand chapters'}
          >
            {isExpanded ? (
              <ChevronUp className="h-4 w-4" />
            ) : (
              <ChevronDown className="h-4 w-4" />
            )}
          </Button>
        </div>
      </CardHeader>

      {isExpanded && (
        <CardContent className="pt-0">
          <ScrollArea className="h-[400px] pr-4">
            <div className="space-y-2">
              {sortedChapters.map((chapter, index) => {
                const isActive = currentChapter === chapter.chapter_number;
                const timestamp = getChapterTimestamp(index);
                
                return (
                  <button
                    key={chapter.id}
                    onClick={() => onChapterSelect(chapter.chapter_number, timestamp)}
                    className={cn(
                      'w-full text-left p-3 rounded-lg border transition-all',
                      'hover:shadow-sm hover:border-primary/50',
                      'focus:outline-none focus:ring-2 focus:ring-primary focus:ring-offset-2',
                      isActive
                        ? 'bg-primary/10 border-primary shadow-sm'
                        : 'bg-card border-border hover:bg-accent'
                    )}
                  >
                    <div className="flex items-start justify-between gap-3">
                      <div className="flex-1 min-w-0 space-y-1">
                        <div className="flex items-center gap-2">
                          <span
                            className={cn(
                              'text-xs font-medium px-2 py-0.5 rounded-full',
                              isActive
                                ? 'bg-primary text-primary-foreground'
                                : 'bg-muted text-muted-foreground'
                            )}
                          >
                            {chapter.chapter_number}
                          </span>
                          {isActive && (
                            <Badge variant="secondary" className="text-xs">
                              Playing
                            </Badge>
                          )}
                        </div>
                        
                        <h4 className={cn(
                          'font-medium line-clamp-2',
                          isActive && 'text-primary'
                        )}>
                          {chapter.title}
                        </h4>
                        
                        <div className="flex flex-wrap items-center gap-2 text-xs text-muted-foreground">
                          <span>
                            Pages {chapter.start_page}–{chapter.end_page}
                          </span>
                          
                          {chapter.duration_seconds && (
                            <>
                              <span>•</span>
                              <div className="flex items-center gap-1">
                                <Clock className="h-3 w-3" />
                                <span>{formatDuration(chapter.duration_seconds)}</span>
                              </div>
                            </>
                          )}
                          
                          {chapter.confidence_score && (
                            <>
                              <span>•</span>
                              <span
                                className={cn(
                                  'font-medium',
                                  getConfidenceColor(chapter.confidence_score)
                                )}
                                title={`Confidence: ${(chapter.confidence_score * 100).toFixed(1)}%`}
                              >
                                {(chapter.confidence_score * 100).toFixed(0)}%
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
          </ScrollArea>
        </CardContent>
      )}
    </Card>
  );
}
