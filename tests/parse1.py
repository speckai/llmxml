from typing import List, TypeVar, Union

from llmxml.parser import parse_xml
from pydantic import BaseModel, Field

T = TypeVar("T", bound=BaseModel)


def test_streaming_by_char_2():
    xml = """<response>
<movies>
<movie>
<title>Avatar</title>
<director>James Cameron</director>
</movie>
<movie>
<title>Avengers: Endgame</title>
<director>Anthony Russo, Joe Russo</director>
</movie>
<movie>
<title>Titanic</title>
<director>James Cameron</director>
</movie>
<movie>
<title>Star Wars: The Force Awakens</title>
<director>J.J. Abrams</director>
</movie>
<movie>
<title>Jurassic World</title>
<director>Colin Trevorrow</director>
</movie>
</movies>
</response>
"""

    class Movie(BaseModel):
        title: Union[str, None] = Field(..., description="The title of the movie")
        director: Union[str, None] = Field(..., description="The director of the movie")

    class Response(BaseModel):
        movies: List[Movie] = Field(
            ..., description="A list of movies that match the query"
        )

    class ResponseObject(BaseModel):
        response: Response = Field(
            ..., description="The response object that contains the movies"
        )

    partial_content = ""
    last_valid_result = None
    for char in xml:
        partial_content += char
        print(partial_content, end="\n-------\n")
        result = parse_xml(ResponseObject, partial_content)

        print(result)

    last_valid_result = result
    assert isinstance(last_valid_result, ResponseObject)


if __name__ == "__main__":
    test_streaming_by_char_2()
