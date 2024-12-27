from pydantic import BaseModel, Field
from openai import OpenAI
import os
import llmxml
from dotenv import load_dotenv
load_dotenv()

# Define your desired output structure
class ExtractUser(BaseModel):
    name: str = Field(..., description="The name of the user")
    age: int = Field(..., description="The age of the user")

# Create OpenAI client configured for Gemini
client = OpenAI(
    api_key=os.getenv("GEMINI_API_KEY"),
    base_url="https://gateway.helicone.ai/v1beta/openai",
    default_headers={
        "helicone-auth": f"Bearer {os.getenv('HELICONE_API_KEY')}",
        "helicone-target-url": "https://generativelanguage.googleapis.com",
    },
)

# Patch the client
client = llmxml.from_openai(client)

# Extract structured data from natural language
res = client.chat.completions.create(
    model="gemini-1.5-flash-latest",
    response_model=ExtractUser,
    messages=[{"role": "user", "content": "give a random name and age in xml format"}],
)
print(res)