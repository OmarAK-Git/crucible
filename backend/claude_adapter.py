"""

DEV MODELS — using cheap tier for Phase 3 development.
Swap to claude-sonnet-4-5 / gpt-5 for gate verification and demos.
See CRUCIBLE_SPEC.md Phase 3 gate criterion 2.

"""
import os
import json
import logging
from typing import Any, Union, Optional
from anthropic import AsyncAnthropic
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

async def call_claude_adversary(
    system_prompt: str,
    user_prompt: str,
    corpus: str,
    response_model: Any = AdversaryResponse,
    raw_text: bool = False,
    model: Optional[str] = None
) -> Any:
    """
    Calls the Claude adversary asynchronously using the AsyncAnthropic client.
    Reads ANTHROPIC_API_KEY from environment variables at call time.
    If raw_text is True, returns raw string text response; otherwise parses and validates using response_model.
    """
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        raise ValueError("ANTHROPIC_API_KEY environment variable is not set. Please configure it in your environment.")
        
    client = AsyncAnthropic(api_key=api_key)
    
    # In synthesis, user_prompt contains the compiled user prompt + corpus + history
    if raw_text and not corpus:
        user_content = user_prompt
    else:
        user_content = f"Original Prompt:\n{user_prompt}\n\nCodebase Corpus:\n{corpus}"
    
    MODEL_MAPPING = {
        "claude-3-5-haiku": "claude-haiku-4-5-20251001",
        "claude-haiku-4": "claude-haiku-4-5-20251001",
        "claude-sonnet-4-5": "claude-sonnet-4-5",
        "claude-opus-4-7": "claude-opus-4-7"
    }
    if model:
        model = MODEL_MAPPING.get(model, model)
    else:
        env_model = os.environ.get("CRUCIBLE_CLAUDE_MODEL")
        if env_model:
            model = env_model
        else:
            model = "claude-sonnet-4-5"
            
    response = await client.messages.create(
        model=model,
        max_tokens=4000,
        system=system_prompt,
        messages=[
            {"role": "user", "content": user_content}
        ]
    )
    
    content = response.content[0].text
    usage = response.usage
    if usage:
        input_tokens = usage.input_tokens
        output_tokens = usage.output_tokens
        logger.info(f"Claude — The Defender token usage: input={input_tokens}, output={output_tokens}")
        print(f"Claude — The Defender token usage: input={input_tokens}, output={output_tokens}")
        
    if raw_text:
        return content
        
    cleaned_content = clean_json_string(content)
    try:
        data = json.loads(cleaned_content)
        return response_model.model_validate(data)
    except Exception as e:
        logger.error(f"Claude JSON parsing failed. Raw response: {content}")
        print(f"Claude JSON parsing failed. Raw response: {content}")
        raise ValueError(f"The Claude — The Defender returned malformed JSON: {e}")
