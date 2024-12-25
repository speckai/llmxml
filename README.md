# llmxml - XML parsing for LLM outputs

[![MIT License](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE.md)
[![PyPI package](https://badge.fury.io/py/llmxml.svg)](https://badge.fury.io/py/llmxml)

**Sponsored by [Speck](https://speck.sh)**
[![Speck](https://speck.sh/_next/image?url=%2Fspeck-icon.png&w=16&q=75)](https://speck.sh/)

XML outputs are a common format for LLM outputs, but they are not always easy to parse. This package provides a way to parse XML outputs into Pydantic models.

This supports nested models, lists, and unions as well as partial parsing for streamed responses. llmxml also supports generating a prompt template for the XML schema to pass to the LLM.

![Parser Demo](assets/parser.gif)

## Usage

### Parsing XML

```python
from llmxml import parse_xml, generate_prompt_template
from pydantic import BaseModel, Field

class Movie(BaseModel):
    title: str = Field(..., description="The title of the movie")
    director: str = Field(..., description="The director of the movie")

class Response(BaseModel):
    movies: list[Movie] = Field(
        ..., description="A list of movies that match the query"
    )

class ResponseObject(BaseModel):
    response: Response = Field(
        ..., description="The response object that contains the movies"
    )

xml: str = """
<response>
    <movies>
        <movie>
            <title>The Matrix</title>
            <director>The Wachowskis</director>
        </movie>
    </movies>
</response>
"""

result: ResponseObject = parse_xml(ResponseObject, xml)
print(result)
```

Output:

```
response=Response(movies=[Movie(title='The Matrix', director='The Wachowskis')])
```

### Generating a prompt template

```python
prompt: str = generate_prompt_template(
    model=Response, include_instructions=True  # Default is true
)
print(prompt)
```

Output:

```
<response_instructions>
You are to understand the content and provide the parsed objects in xml that match the following xml_schema:

Make sure to return an instance of the XML, not the schema itself

Each field in the field_schema has a description and a type.
Example:
<field_name>
[type]
[description]
</field_name>

Schema:
<movies>
[type: list]
[A list of movies]
</movies>
</response_instructions>
```

## Development
### Running tests
```
$ uv run -m pytest -n auto tests/test_parser.py
```

## License

This project is licensed under the MIT License. See the [LICENSE](LICENSE) file for details.
