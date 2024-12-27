from pydantic import BaseModel, Field
from anthropic import AsyncAnthropic
import asyncio
import os
from dotenv import load_dotenv
import llmxml
load_dotenv()

class ExtractUser(BaseModel):
    name: str = Field(..., description="The name of the user")
    age: int = Field(..., description="The age of the user")

client = llmxml.from_anthropic(AsyncAnthropic(api_key=os.getenv("ANTHROPIC_API_KEY")))

async def extract_user(text: str) -> ExtractUser:
    return await client.messages.create(
        model="claude-3-haiku-20240307",
        max_tokens=1024,
        messages=[{"role": "user", "content": text}],
        response_model=ExtractUser,
    )

async def main():
    dataset = [
        "give a random name and age in xml format",
        "give another random name and age in xml format",
        "give one more random name and age in xml format"
    ]
    
    tasks = [extract_user(text) for text in dataset]
    
    results = await asyncio.gather(*tasks)
    
    for result in results:
        print(result)

if __name__ == "__main__":
    asyncio.run(main())