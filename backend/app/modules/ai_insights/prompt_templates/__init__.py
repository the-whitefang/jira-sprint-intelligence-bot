"""Prompt templates for Gemini integration."""

from .entity_prompt import ENTITY_EXTRACTION_PROMPT
from .intent_prompt import INTENT_DETECTION_PROMPT
from .response_prompt import RESPONSE_GENERATION_PROMPT

__all__ = ["INTENT_DETECTION_PROMPT", "ENTITY_EXTRACTION_PROMPT", "RESPONSE_GENERATION_PROMPT"]
