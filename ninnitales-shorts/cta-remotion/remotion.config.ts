import {Config} from '@remotion/cli/config';

Config.setVideoImageFormat('jpeg');
Config.setOverwriteOutput(true);
// Vertical Shorts output. Codec h264 is the default and what YouTube wants.
Config.setCodec('h264');
