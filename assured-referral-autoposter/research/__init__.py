"""
Research layer for AssuredReferral AutoPoster.
Gathers trending signals and synthesizes content briefs before carousel generation.
"""

from research.trending import gather_all_signals
from research.synthesizer import synthesize_brief

__all__ = ["gather_all_signals", "synthesize_brief"]
