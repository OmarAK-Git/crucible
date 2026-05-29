"""

DEV MODELS — using cheap tier for Phase 3 development.
Swap to claude-sonnet-4-5 / gpt-5 for gate verification and demos.
See CRUCIBLE_SPEC.md Phase 3 gate criterion 2.

"""
import os
import json
import logging
from typing import Any, Union, Optional
from openai import AsyncOpenAI
from .schemas import AdversaryResponse

logger = logging.getLogger(__name__)

def clean_json_string(text: str) -> str:
    """
    Finds the first JSON object (enclosed in curly braces) in the text.
    Handles extra text before or after the JSON block.
    """
    text = text.strip()
    start = text.find("{")
    if start == -1:
        return text
        
    brace_count = 0
    in_string = False
    escape = False
    
    for idx in range(start, len(text)):
        char = text[idx]
        
        if in_string:
            if char == '\\' and not escape:
                escape = True
            elif char == '"' and not escape:
                in_string = False
            else:
                escape = False
        else:
            if char == '"':
                in_string = True
                escape = False
            elif char == '{':
                brace_count += 1
            elif char == '}':
                brace_count -= 1
                if brace_count == 0:
                    return text[start:idx+1]
                    
    return text

async def call_gpt_adversary(
    system_prompt: str,
    user_prompt: str,
    corpus: str,
    response_model: Any = AdversaryResponse,
    raw_text: bool = False,
    model: Optional[str] = None
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
    
    MODEL_MAPPING = {
        "gpt-4o-mini": "gpt-4o-mini",
        "gpt-nano": "gpt-4o-mini",
        "gpt-5": "gpt-4o",
        "gpt-5.5": "gpt-4o"
    }
    if model:
        model = MODEL_MAPPING.get(model, model)
    else:
        env_model = os.environ.get("CRUCIBLE_GPT_MODEL")
        if env_model:
            model = env_model
        else:
            model = "gpt-4o"
            
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
        logger.error(f"GPT JSON parsing failed. Raw response: {content}")
        print(f"GPT JSON parsing failed. Raw response: {content}")
        raise ValueError(f"The GPT — The Challenger returned malformed JSON: {e}")
