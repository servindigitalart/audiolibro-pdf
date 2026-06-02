import { cn } from '@/lib/utils';

// Warm, premium palettes — deterministic by title hash
const PALETTES = [
  { bg: 'linear-gradient(145deg, #D97706, #92400E)', text: '#FFF8E7' },
  { bg: 'linear-gradient(145deg, #1D4ED8, #1E3A5F)', text: '#EFF6FF' },
  { bg: 'linear-gradient(145deg, #059669, #064E3B)', text: '#ECFDF5' },
  { bg: 'linear-gradient(145deg, #7C3AED, #3B0764)', text: '#F5F3FF' },
  { bg: 'linear-gradient(145deg, #DB2777, #831843)', text: '#FDF2F8' },
  { bg: 'linear-gradient(145deg, #0891B2, #164E63)', text: '#ECFEFF' },
  { bg: 'linear-gradient(145deg, #4F46E5, #1E1B4B)', text: '#EEF2FF' },
  { bg: 'linear-gradient(145deg, #B45309, #78350F)', text: '#FFFBEB' },
  { bg: 'linear-gradient(145deg, #0F766E, #042F2E)', text: '#F0FDFA' },
  { bg: 'linear-gradient(145deg, #6D28D9, #2E1065)', text: '#FAF5FF' },
];

function hashString(s: string): number {
  let h = 0;
  for (const c of s) h = (h * 31 + c.charCodeAt(0)) >>> 0;
  return h;
}

const SIZE_CLASSES = {
  xs: { outer: 'w-8 h-10 rounded',    font: 'text-[6px]' },
  sm: { outer: 'w-10 h-14 rounded-lg', font: 'text-[7px]' },
  md: { outer: 'w-14 h-20 rounded-xl', font: 'text-[9px]' },
  lg: { outer: 'w-20 h-28 rounded-xl', font: 'text-[11px]' },
};

interface Props {
  title:      string;
  size?:      keyof typeof SIZE_CLASSES;
  className?: string;
  imageUrl?:  string;
}

export default function BookCover({ title, size = 'sm', className, imageUrl }: Props) {
  const h       = hashString(title);
  const palette = PALETTES[h % PALETTES.length];
  // Subtle diagonal stripe pattern — unique angle per title
  const angle   = 30 + (h % 5) * 18;
  const { outer, font } = SIZE_CLASSES[size];

  // Split title into up to 2 display lines
  const words = title.trim().split(/\s+/).filter(Boolean);
  const mid   = Math.ceil(words.length / 2);
  const line1 = words.slice(0, mid).join(' ');
  const line2 = words.slice(mid).join(' ');

  // Custom cover image — takes priority over the generated gradient
  if (imageUrl) {
    return (
      <div
        className={cn(
          outer,
          'relative overflow-hidden flex-shrink-0 shadow-md select-none',
          className,
        )}
        aria-hidden="true"
      >
        <img
          src={imageUrl}
          alt=""
          className="absolute inset-0 w-full h-full object-cover"
          loading="lazy"
          decoding="async"
        />
      </div>
    );
  }

  return (
    <div
      className={cn(
        outer,
        'relative overflow-hidden flex-shrink-0 flex flex-col items-center justify-center shadow-md select-none',
        className,
      )}
      style={{ background: palette.bg }}
      aria-hidden="true"
    >
      {/* Subtle stripe overlay */}
      <div
        className="absolute inset-0 opacity-[0.07]"
        style={{
          backgroundImage: `repeating-linear-gradient(${angle}deg, ${palette.text} 0px, ${palette.text} 1px, transparent 1px, transparent 7px)`,
        }}
      />

      {/* Title */}
      <div
        className={cn('relative px-1.5 text-center leading-tight font-bold break-words', font)}
        style={{ color: palette.text }}
      >
        <div className="opacity-95">{line1}</div>
        {line2 && <div className="opacity-70 mt-0.5">{line2}</div>}
      </div>

      {/* Bottom spine accent */}
      <div
        className="absolute bottom-0 inset-x-0 h-[2px] opacity-20"
        style={{ background: palette.text }}
      />
    </div>
  );
}
