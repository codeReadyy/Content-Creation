import React from 'react';
import {Composition} from 'remotion';
import {CTA, CTA_CONFIG} from './CTA';

export const RemotionRoot: React.FC = () => {
  return (
    <Composition
      id="CTA"
      component={CTA}
      durationInFrames={Math.round(CTA_CONFIG.durationInSeconds * CTA_CONFIG.fps)}
      fps={CTA_CONFIG.fps}
      width={CTA_CONFIG.width}
      height={CTA_CONFIG.height}
    />
  );
};
