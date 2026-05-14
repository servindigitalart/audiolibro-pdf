/**
 * Utility function tests — pure functions, no DOM/network needed.
 */
import { describe, it, expect } from 'vitest';
import { fmtFileSize, fmtDuration, fmtDate, fmtRelative, fmtChars, fmtPrice, pct } from '@/lib/utils';

describe('fmtFileSize', () => {
  it('formats bytes',     () => expect(fmtFileSize(512)).toBe('512 B'));
  it('formats KB',        () => expect(fmtFileSize(2048)).toBe('2.0 KB'));
  it('formats MB',        () => expect(fmtFileSize(3 * 1024 * 1024)).toBe('3.0 MB'));
});

describe('fmtDuration', () => {
  it('formats seconds',           () => expect(fmtDuration(75)).toBe('1:15'));
  it('formats hours',             () => expect(fmtDuration(3661)).toBe('1:01:01'));
  it('pads minutes under 10',     () => expect(fmtDuration(65)).toBe('1:05'));
});

describe('fmtChars', () => {
  it('thousands',  () => expect(fmtChars(10_000)).toBe('10K'));
  it('millions',   () => expect(fmtChars(2_000_000)).toBe('2M'));
  it('sub-K',      () => expect(fmtChars(500)).toBe('500'));
});

describe('fmtPrice', () => {
  it('free',          () => expect(fmtPrice(0)).toBe('Free'));
  it('integer',       () => expect(fmtPrice(9)).toBe('$9/mo'));
  it('decimal',       () => expect(fmtPrice(9.99)).toBe('$9.99/mo'));
  it('yearly suffix', () => expect(fmtPrice(99, 'yr')).toBe('$99/yr'));
});

describe('pct', () => {
  it('50% usage',      () => expect(pct(50, 100)).toBe(50));
  it('clamps at 100',  () => expect(pct(200, 100)).toBe(100));
  it('zero limit',     () => expect(pct(5, 0)).toBe(0));
  it('exact 80%',      () => expect(pct(80, 100)).toBe(80));
});
