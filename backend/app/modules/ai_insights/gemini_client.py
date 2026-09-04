"""Gemini AI API Client."""

from __future__ import annotations

import json
import logging
from typing import TypeVar, Type

import google.generativeai as genai
from google.generativeai.types import GenerationConfig
from pydantic import BaseModel
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type

from app.core.config import Settings
from app.core.exceptions import ExternalServiceException

logger = logging.getLogger(__name__)

T = TypeVar("T", bound=BaseModel)

class GeminiClient:
    """Wrapper around the Google Generative AI client."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        genai.configure(api_key=settings.GEMINI_API_KEY)
        self._model_name = settings.GEMINI_MODEL
        
    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=10),
        retry=retry_if_exception_type(Exception),
        reraise=True
    )
    async def generate_structured_response(
        self, prompt: str, schema: Type[T]
    ) -> T:
        """Call Gemini and force a structured JSON response matching a Pydantic schema."""
        model = genai.GenerativeModel(self._model_name)
        
        # In Gemini API (via google.generativeai), we can pass response_schema
        # for structured output if supported by the model.
        config = GenerationConfig(
            response_mime_type="application/json",
            response_schema=schema,
            max_output_tokens=self._settings.GEMINI_MAX_OUTPUT_TOKENS,
            temperature=0.0  # structured data works best with lowest temp
        )
        
        try:
            response = await model.generate_content_async(
                prompt,
                generation_config=config,
                request_options={"timeout": self._settings.GEMINI_TIMEOUT_SECONDS}
            )
            
            if not response.text:
                raise ExternalServiceException("Empty response from Gemini")
                
            return schema.model_validate_json(response.text)
            
        except Exception as e:
            logger.error("gemini_structured_call_failed", extra={"error": str(e)})
            raise ExternalServiceException(f"Failed to generate structured response from Gemini: {str(e)}")

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=10),
        retry=retry_if_exception_type(Exception),
        reraise=True
    )
    async def generate_text(self, prompt: str) -> str:
        """Call Gemini for a free-form natural language response."""
        model = genai.GenerativeModel(self._model_name)
        
        config = GenerationConfig(
            max_output_tokens=self._settings.GEMINI_MAX_OUTPUT_TOKENS,
            temperature=0.4
        )
        
        try:
            response = await model.generate_content_async(
                prompt,
                generation_config=config,
                request_options={"timeout": self._settings.GEMINI_TIMEOUT_SECONDS}
            )
            
            if not response.text:
                raise ExternalServiceException("Empty response from Gemini")
                
            return response.text
            
        except Exception as e:
            logger.error("gemini_text_call_failed", extra={"error": str(e)})
            raise ExternalServiceException(f"Failed to generate text response from Gemini: {str(e)}")

    async def generate_text_stream(self, prompt: str):
        """Call Gemini for a free-form natural language response, streaming chunks."""
        model = genai.GenerativeModel(self._model_name)
        
        config = GenerationConfig(
            max_output_tokens=self._settings.GEMINI_MAX_OUTPUT_TOKENS,
            temperature=0.4
        )
        
        try:
            response = await model.generate_content_async(
                prompt,
                generation_config=config,
                request_options={"timeout": self._settings.GEMINI_TIMEOUT_SECONDS},
                stream=True
            )
            
            async for chunk in response:
                if chunk.text:
                    yield chunk.text
                    
        except Exception as e:
            logger.error("gemini_stream_call_failed", extra={"error": str(e)})
            raise ExternalServiceException(f"Failed to stream response from Gemini: {str(e)}")

