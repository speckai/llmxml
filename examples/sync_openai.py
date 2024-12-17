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

# Patch the OpenAI client
client = llmxml.from_openai(OpenAI(api_key=os.getenv("OPENAI_API_KEY")))

# Extract structured data from natural language
res = client.chat.completions.create(
    model="gpt-4o-mini",
    response_model=ExtractUser,
    messages=[{"role": "user", "content": "give a random name and age in xml format"}],
)
print(res)