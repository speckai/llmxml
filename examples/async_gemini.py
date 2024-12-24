import instructor
from pydantic import BaseModel, Field
from openai import AsyncOpenAI
import asyncio
import os
from dotenv import load_dotenv
import llmxml
load_dotenv()

# Define your desired output structure
class ExtractUser(BaseModel):
    name: str = Field(..., description="The name of the user")
    age: int = Field(..., description="The age of the user")


client = AsyncOpenAI(
    api_key=os.getenv("GEMINI_API_KEY"),
    base_url="https://gateway.helicone.ai/v1beta/openai",
    default_headers={
        "helicone-auth": f"Bearer {os.getenv('HELICONE_API_KEY')}",
        "helicone-target-url": "https://generativelanguage.googleapis.com",
    },
)

# Patch the OpenAI client correctly using instructor.apatch
client = llmxml.from_openai(client)

# Extract structured data from natural language
async def extract_user(text: str) -> ExtractUser:
    return await client.chat.completions.create(
        # model="gpt-4o-mini",
        model="gemini-1.5-flash-latest",
        messages=[{"role": "user", "content": text}],
        response_model=ExtractUser,
    )

# Example of using asyncio.gather for concurrent processing
async def main():
    dataset = [
        "give a random name and age in xml format",
        "give another random name and age in xml format",
        "give one more random name and age in xml format"
    ]
    
    # Create tasks for concurrent execution
    tasks = [extract_user(text) for text in dataset]
    
    # Execute tasks concurrently and get results
    results = await asyncio.gather(*tasks)
    
    # Print results
    for result in results:
        print(result)

# Run the async function
if __name__ == "__main__":
    asyncio.run(main())