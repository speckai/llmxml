from pydantic import BaseModel, Field
from anthropic import Anthropic
import os
import llmxml
from dotenv import load_dotenv
load_dotenv()

# Define your desired output structure
class ExtractUser(BaseModel):
    name: str = Field(..., description="The name of the user")
    age: int = Field(..., description="The age of the user")

# Create and patch the Anthropic client
client = llmxml.from_anthropic(Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY")))

# Extract structured data from natural language
res = client.messages.create(
    model="claude-3-haiku-20240307",
    max_tokens=1024,
    response_model=ExtractUser,
    messages=[{"role": "user", "content": "give a random name and age in xml format"}],
)
print(res)