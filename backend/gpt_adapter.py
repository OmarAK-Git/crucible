import os
import json
import logging
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

async def call_gpt_adversary(system_prompt: str, user_prompt: str, corpus: str) -> AdversaryResponse:
    """
    Calls the GPT adversary asynchronously using the AsyncOpenAI client.
    Reads OPENAI_API_KEY from environment variables at call time.
    Validates that the output conforms to the structured JSON schema.
    """
    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        raise ValueError("OPENAI_API_KEY environment variable is not set. Please configure it in your environment.")
        
    client = AsyncOpenAI(api_key=api_key)
    
    user_content = f"Original Prompt:\n{user_prompt}\n\nCodebase Corpus:\n{corpus}"
    
    response = await client.chat.completions.create(
        model="gpt-4o",
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_content}
        ],
        response_format={"type": "json_object"}
    )
    
    content = response.choices[0].message.content
    usage = response.usage
    if usage:
        input_tokens = usage.prompt_tokens
        output_tokens = usage.completion_tokens
        logger.info(f"GPT — The Challenger token usage: input={input_tokens}, output={output_tokens}")
        print(f"GPT — The Challenger token usage: input={input_tokens}, output={output_tokens}")
        
    cleaned_content = clean_json_string(content)
    try:
        data = json.loads(cleaned_content)
        return AdversaryResponse.model_validate(data)
    except Exception as e:
        raise ValueError(f"The GPT — The Challenger returned malformed JSON: {e}")
