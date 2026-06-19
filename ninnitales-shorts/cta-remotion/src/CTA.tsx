import React from 'react';
import {
  AbsoluteFill,
  Audio,
  Img,
  interpolate,
  staticFile,
  useCurrentFrame,
  useVideoConfig,
} from 'remotion';

/* ============================================================================
 * EDIT EVERYTHING HERE.
 * - To preview right now with no assets: leave `image` and `music` empty ('').
 *   You'll see gradient backgrounds + the text/animation timing.
 * - When you have assets: drop files into  public/  and put the FILENAME here
 *   (e.g. image: 'parent-away.jpg'). Supports .jpg/.png and .mp4 stills.
 * - 7 seconds total, 30fps = 210 frames. Beats cross-fade automatically.
 * ========================================================================== */
export const CTA_CONFIG = {
  fps: 30,
  durationInSeconds: 7,
  width: 1080,
  height: 1920,

  // One song reused on every video. Drop e.g. 'music.mp3' into public/.
  // Leave '' to preview silently. Royalty-free avoids YouTube Content ID claims.
  music: '',

  // Three beats: the ache -> the magic -> the promise + CTA.
  beats: [
    {
      // 0.0 - 2.6s : THE ACHE
      image: '', // e.g. 'parent-away.jpg' (parent at airport / working late)
      gradient: ['#1b2a4a', '#0d1526'],
      lines: ['POV: you’re away', 'at bedtime again'],
      color: '#ffffff',
    },
    {
      // 2.6 - 5.0s : THE MAGIC
      image: '', // e.g. 'kid-bedtime.jpg' (child in bed, phone glowing warm)
      gradient: ['#3a2a4d', '#1a1230'],
      lines: ['They still hear', 'your voice.'],
      color: '#ffffff',
    },
    {
      // 5.0 - 7.0s : PROMISE + CTA
      image: '', // optional; a warm solid/gradient often reads cleanest here
      gradient: ['#ff8a5c', '#ff5e7e'],
      lines: ['You can’t always be there.', 'Your voice can.'],
      color: '#ffffff',
      brand: 'NinniTales',
      cta: 'Free · Search “NinniTales”',
    },
  ],
};

const FONT =
  '-apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif';

// Beat windows in frames (at 30fps). 12-frame cross-fades between beats.
const BEAT_WINDOWS = [
  {start: 0, end: 84},
  {start: 72, end: 156},
  {start: 144, end: 210},
];
const FADE = 12;

const GradientBg: React.FC<{colors: string[]}> = ({colors}) => (
  <AbsoluteFill
    style={{
      background: `linear-gradient(160deg, ${colors[0]} 0%, ${colors[1]} 100%)`,
    }}
  />
);

// A single beat: background (image or gradient) with slow Ken Burns + text.
const Beat: React.FC<{
  beat: (typeof CTA_CONFIG.beats)[number];
  window: {start: number; end: number};
  isLast?: boolean;
}> = ({beat, window, isLast}) => {
  const frame = useCurrentFrame();
  const local = frame - window.start;
  const span = window.end - window.start;

  // Cross-fade opacity for the whole beat.
  const opacity = interpolate(
    frame,
    [window.start, window.start + FADE, window.end - FADE, window.end],
    [0, 1, 1, 0],
    {extrapolateLeft: 'clamp', extrapolateRight: 'clamp'}
  );

  // Slow Ken Burns zoom on the background.
  const scale = interpolate(local, [0, span], [1.06, 1.16], {
    extrapolateLeft: 'clamp',
    extrapolateRight: 'clamp',
  });

  return (
    <AbsoluteFill style={{opacity}}>
      <AbsoluteFill style={{transform: `scale(${scale})`}}>
        {beat.image ? (
          <Img
            src={staticFile(beat.image)}
            style={{width: '100%', height: '100%', objectFit: 'cover'}}
          />
        ) : (
          <GradientBg colors={beat.gradient} />
        )}
      </AbsoluteFill>

      {/* Readability scrim so white text pops over any image. */}
      <AbsoluteFill
        style={{
          background:
            'linear-gradient(180deg, rgba(0,0,0,0.25) 0%, rgba(0,0,0,0.0) 35%, rgba(0,0,0,0.0) 60%, rgba(0,0,0,0.55) 100%)',
        }}
      />

      <AbsoluteFill
        style={{
          justifyContent: isLast ? 'center' : 'flex-end',
          alignItems: 'center',
          padding: '0 80px 220px 80px',
          textAlign: 'center',
        }}
      >
        {beat.lines.map((line, i) => {
          // Each line rises + fades in, staggered.
          const delay = i * 7;
          const p = interpolate(local, [delay, delay + 16], [0, 1], {
            extrapolateLeft: 'clamp',
            extrapolateRight: 'clamp',
          });
          const y = interpolate(p, [0, 1], [40, 0]);
          return (
            <div
              key={i}
              style={{
                fontFamily: FONT,
                fontWeight: 800,
                fontSize: 96,
                lineHeight: 1.05,
                color: beat.color,
                opacity: p,
                transform: `translateY(${y}px)`,
                textShadow: '0 4px 24px rgba(0,0,0,0.45)',
                letterSpacing: -1,
              }}
            >
              {line}
            </div>
          );
        })}

        {/* Brand + CTA only on the last beat. */}
        {isLast && beat.brand ? (
          <div style={{marginTop: 60}}>
            <div
              style={{
                fontFamily: FONT,
                fontWeight: 900,
                fontSize: 120,
                color: '#ffffff',
                opacity: interpolate(local, [22, 38], [0, 1], {
                  extrapolateLeft: 'clamp',
                  extrapolateRight: 'clamp',
                }),
                textShadow: '0 6px 30px rgba(0,0,0,0.5)',
                letterSpacing: -2,
              }}
            >
              {beat.brand}
            </div>
            {beat.cta ? (
              <div
                style={{
                  fontFamily: FONT,
                  fontWeight: 600,
                  fontSize: 48,
                  marginTop: 16,
                  color: 'rgba(255,255,255,0.95)',
                  opacity: interpolate(local, [30, 46], [0, 1], {
                    extrapolateLeft: 'clamp',
                    extrapolateRight: 'clamp',
                  }),
                }}
              >
                {beat.cta}
              </div>
            ) : null}
          </div>
        ) : null}
      </AbsoluteFill>
    </AbsoluteFill>
  );
};

export const CTA: React.FC = () => {
  const {durationInFrames} = useVideoConfig();

  return (
    <AbsoluteFill style={{backgroundColor: '#000'}}>
      {CTA_CONFIG.beats.map((beat, i) => (
        <Beat
          key={i}
          beat={beat}
          window={BEAT_WINDOWS[i]}
          isLast={i === CTA_CONFIG.beats.length - 1}
        />
      ))}

      {CTA_CONFIG.music ? (
        <Audio
          src={staticFile(CTA_CONFIG.music)}
          // Gentle fade-out over the final ~0.7s.
          volume={(f) =>
            interpolate(f, [durationInFrames - 20, durationInFrames], [1, 0], {
              extrapolateLeft: 'clamp',
              extrapolateRight: 'clamp',
            })
          }
        />
      ) : null}
    </AbsoluteFill>
  );
};
