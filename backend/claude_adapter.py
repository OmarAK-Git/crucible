import os
import json
import logging
from anthropic import AsyncAnthropic
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

async def call_claude_adversary(system_prompt: str, user_prompt: str, corpus: str) -> AdversaryResponse:
    """
    Calls the Claude adversary asynchronously using the AsyncAnthropic client.
    Reads ANTHROPIC_API_KEY from environment variables at call time.
    Validates that the output conforms to the structured JSON schema.
    """
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        raise ValueError("ANTHROPIC_API_KEY environment variable is not set. Please configure it in your environment.")
        
    client = AsyncAnthropic(api_key=api_key)
    
    user_content = f"Original Prompt:\n{user_prompt}\n\nCodebase Corpus:\n{corpus}"
    
    response = await client.messages.create(
        model="claude-sonnet-4-5",
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
        
    cleaned_content = clean_json_string(content)
    try:
        data = json.loads(cleaned_content)
        return AdversaryResponse.model_validate(data)
    except Exception as e:
        raise ValueError(f"The Claude — The Defender returned malformed JSON: {e}")
