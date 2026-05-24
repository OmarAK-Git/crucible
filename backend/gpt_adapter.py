"""

DEV MODELS — using cheap tier for Phase 3 development.
Swap to claude-sonnet-4-5 / gpt-5 for gate verification and demos.
See CRUCIBLE_SPEC.md Phase 3 gate criterion 2.

"""
import os
import json
import logging
from typing import Any, Union
from openai import AsyncOpenAI
from .schemas import AdversaryResponse

logger = logging.getLogger(__name__)

def clean_json_string(text: str) -> str:
    """
    Strips markdown code block backticks if present.
    """
    text = text.strip()
    if text.startswith("```"):
        first_newline = text.find("\n")
        if first_newline != -1:
            text = text[first_newline:].strip()
        if text.endswith("```"):
            text = text[:-3].strip()
    return text

async def call_gpt_adversary(
    system_prompt: str,
    user_prompt: str,
    corpus: str,
    response_model: Any = AdversaryResponse,
    raw_text: bool = False
) -> Any:
    """
    Calls the GPT adversary asynchronously using the AsyncOpenAI client.
    Reads OPENAI_API_KEY from environment variables at call time.
    If raw_text is True, returns raw string text response; otherwise parses and validates using response_model.
    """
    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        raise ValueError("OPENAI_API_KEY environment variable is not set. Please configure it in your environment.")
        
    client = AsyncOpenAI(api_key=api_key)
    
    if raw_text and not corpus:
        user_content = user_prompt
    else:
        user_content = f"Original Prompt:\n{user_prompt}\n\nCodebase Corpus:\n{corpus}"
    
    model = os.environ.get("CRUCIBLE_GPT_MODEL", "gpt-5")
    kwargs = {
        "model": model,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_content}
        ]
    }
    if not raw_text:
        kwargs["response_format"] = {"type": "json_object"}
        
    response = await client.chat.completions.create(**kwargs)
    
    content = response.choices[0].message.content
    usage = response.usage
    if usage:
        input_tokens = usage.prompt_tokens
        output_tokens = usage.completion_tokens
        logger.info(f"GPT — The Challenger token usage: input={input_tokens}, output={output_tokens}")
        print(f"GPT — The Challenger token usage: input={input_tokens}, output={output_tokens}")
        
    if raw_text:
        return content
        
    cleaned_content = clean_json_string(content)
    try:
        data = json.loads(cleaned_content)
        return response_model.model_validate(data)
    except Exception as e:
        raise ValueError(f"The GPT — The Challenger returned malformed JSON: {e}")
