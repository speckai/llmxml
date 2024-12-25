import json
from enum import Enum, StrEnum
from pathlib import Path
from typing import Type, TypeVar, Union

from pydantic import BaseModel, Field
from rich.console import Console

from llmxml import parse_xml

T = TypeVar("T", bound=BaseModel)


console = Console()


def load_test_file(filename: str) -> str:
    """Load test file content."""
    test_dir = Path(__file__).parent / "test_files"
    with open(test_dir / filename, "r") as f:
        return f.read()


def validate_parsed_model(parsed: BaseModel, model_class: Type[T]) -> None:
    """Helper function to validate parsed models"""
    assert (
        isinstance(parsed, model_class)
        or type(parsed).__name__.startswith(f"Partial{model_class.__name__}")
    ), f"Expected {model_class.__name__} or Partial{model_class.__name__}, got {type(parsed).__name__}"
    json_str = parsed.model_dump_json()
    assert json.loads(json_str), "Model should be JSON serializable"


class FileOperation(StrEnum):
    OPEN = "open"
    EDIT = "edit"
    CREATE = "create"


class FileAction(BaseModel):
    thinking: str = Field(..., description="The thinking to perform")
    file_operation: FileOperation = Field(..., description="The operation to perform")


class ChunkInfo(BaseModel):
    file_path: str = Field(..., description="The path of the file")
    content: str = Field(..., description="The content of the chunk")


# class SearchResultType(StrEnum):
#     BASIC_TEXT = "basic_text"
#     IMAGE = "image"
#     VIDEO = "video"


class SearchResultType(Enum):
    BASIC_TEXT = 1
    IMAGE = 2
    VIDEO = 3


class SearchResult(BaseModel):
    chunk_id: str = Field(..., description="The id of the chunk")
    chunk_info: ChunkInfo = Field(..., description="The info of the chunk")
    vector_similarity_score: float = Field(
        ..., description="The similarity score of the chunk"
    )
    search_result_type: SearchResultType = Field(
        ..., description="The type of search result"
    )


class EnumSearchResponse(BaseModel):
    objective: str = Field(..., description="Idk")
    search_results: list[SearchResult] = Field(..., description="The search results")


class TestFileAction:
    def test_enum_basic(self):
        xml = load_test_file("enum_basic.xml")
        result: FileAction = parse_xml(xml, FileAction)
        assert result.file_operation == FileOperation.OPEN

    def test_enum_nested(self):
        xml = load_test_file("enum_nested.xml")
        result: EnumSearchResponse = parse_xml(xml, EnumSearchResponse)
        assert result.search_results[0].search_result_type == SearchResultType.IMAGE
        assert result.search_results[1].search_result_type == SearchResultType.VIDEO

    import time

    def test_enum_nested_streaming(self):
        xml = load_test_file("enum_nested.xml")
        partial_content = ""
        last_valid_result = None

        for char in xml:
            partial_content += char
            result = parse_xml(partial_content, EnumSearchResponse)
            validate_parsed_model(result, EnumSearchResponse)
            last_valid_result = result

        assert last_valid_result is not None
        assert isinstance(last_valid_result, EnumSearchResponse)
        assert len(last_valid_result.search_results) == 2
        assert (
            last_valid_result.search_results[0].search_result_type
            == SearchResultType.IMAGE
        )
        assert (
            last_valid_result.search_results[1].search_result_type
            == SearchResultType.VIDEO
        )


class BasicResponse(BaseModel):
    thinking: str = Field(..., description="The thinking to perform")
    movies: list[str] = Field(..., description="The movies to do idk")


class TestBasicResponse:
    def test_basic_response(self):
        xml = load_test_file("basic_response.xml")
        result: BasicResponse = parse_xml(xml, BasicResponse)
        assert result.thinking.strip() != ""
        assert len(result.movies) > 0

    def test_basic_response_streaming(self):
        xml = load_test_file("basic_response.xml")
        partial_content = ""
        last_valid_result = None
        for char in xml:
            partial_content += char
            result = parse_xml(partial_content, BasicResponse)
            validate_parsed_model(result, BasicResponse)
            last_valid_result = result

        assert last_valid_result is not None
        assert isinstance(last_valid_result, BasicResponse)
        assert last_valid_result.thinking.strip() != ""
        assert len(last_valid_result.movies) > 0


class CreateAction(BaseModel):
    new_file_path: str = Field(..., description="The path to the new file to create")
    file_contents: str = Field(
        ..., description="The contents of the new file to create"
    )


class EditAction(BaseModel):
    original_file_path: str = Field(
        ..., description="The path to the original file to edit"
    )
    new_file_contents: str = Field(..., description="The contents of the edited file")


class CommandAction(BaseModel):
    command: str = Field(..., description="The command to run")


class CodeAction(BaseModel):
    thinking: str = Field(default="", description="The thinking to perform")
    actions: list[Union[CreateAction, EditAction, CommandAction]] = Field(
        default_factory=list, description="The actions to perform"
    )


class TestActions:
    def test_complete_response(self):
        # Test parsing a complete response with multiple actions
        xml = load_test_file("complete.xml")
        result = parse_xml(xml, CodeAction)

        assert result.thinking.strip() != ""
        assert "Component Structure:" in result.thinking
        assert "Implementation Details:" in result.thinking

        create_action = result.actions[0]
        assert create_action.new_file_path.endswith(".tsx")
        assert "import" in create_action.file_contents
        assert "SearchBar" in create_action.file_contents

        command_action = result.actions[1]
        assert "npm install" in command_action.command
        assert "lodash" in command_action.command

        edit_action = result.actions[2]
        assert edit_action.original_file_path.endswith(".tsx")
        assert "SearchBar" in edit_action.new_file_contents

    def test_complete_response_streaming(self):
        xml = load_test_file("complete.xml")
        partial_content = ""
        last_valid_result = None
        for char in xml:
            partial_content += char
            result = parse_xml(partial_content, CodeAction)

            validate_parsed_model(result, CodeAction)
            last_valid_result = result

        assert last_valid_result is not None
        assert isinstance(last_valid_result, CodeAction)
        assert len(last_valid_result.actions) > 0

    def test_partial_response(self):
        # Test parsing a partial response with incomplete action
        xml = load_test_file("partial.xml")
        result = parse_xml(xml, CodeAction)

        assert "Component Structure:" in result.thinking
        assert "Implementation Details:" in result.thinking

        assert len(result.actions) == 1
        action = result.actions[0]
        assert isinstance(action, CreateAction)
        assert action.new_file_path == "components/PlaylistGrid.tsx"
        assert "PlaylistGrid" in action.file_contents
        assert "grid" in action.file_contents.lower()

    def test_partial_response_streaming(self):
        xml = load_test_file("partial.xml")
        partial_content = ""
        last_valid_result = None
        for char in xml:
            partial_content += char
            result = parse_xml(partial_content, CodeAction)
            validate_parsed_model(result, CodeAction)
            last_valid_result = result

        assert last_valid_result is not None
        assert isinstance(last_valid_result, CodeAction)
        assert len(last_valid_result.actions) == 1

    def test_streaming_response(self):
        # Test parsing a streaming response that's cut off mid-element
        xml = load_test_file("streaming.xml")
        result = parse_xml(xml, CodeAction)

        assert "Component Structure:" in result.thinking
        assert "Implementation Details:" in result.thinking
        assert all(
            item in result.thinking for item in ["Play/pause button", "Volume control"]
        )

        assert len(result.actions) == 1
        action = result.actions[0]
        assert isinstance(action, CreateAction)
        assert action.new_file_path == "components/PlayerControls.tsx"
        assert "PlayerControls" in action.file_contents

    def test_streaming_response_streaming(self):
        xml = load_test_file("streaming.xml")
        partial_content = ""
        last_valid_result = None

        for char in xml:
            partial_content += char
            result = parse_xml(partial_content, CodeAction)
            validate_parsed_model(result, CodeAction)
            last_valid_result = result

        assert last_valid_result is not None
        assert isinstance(last_valid_result, CodeAction)
        assert len(last_valid_result.actions) == 1

    def test_empty_response(self):
        # Test parsing an empty response.
        xml = ""
        result = parse_xml(xml, CodeAction)
        assert result.thinking == ""
        assert len(result.actions) == 0


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


class TestMovies:
    def test_movies_response(self):
        xml = """<response>
<movies>
<movie>
<title>Avatar</title>
<director>James Cameron</director>
</movie>
<movie>
<title>Avengers: Endgame</title>
<director>Anthony and Joe Russo</director>
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
        result = parse_xml(xml, ResponseObject)
        assert len(result.response.movies) == 5
        assert result.response.movies[0].title == "Avatar"

    def test_movies_response_streaming(self):
        xml = """<response>
<movies>
<movie>
<title>Avatar</title>
<director>James Cameron</director>
</movie>
<movie>
<title>Avengers: Endgame</title>
<director>Anthony and Joe Russo</director>
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
        partial_content = ""
        last_valid_result = None
        for char in xml:
            partial_content += char
            result = parse_xml(partial_content, ResponseObject)

            validate_parsed_model(result, ResponseObject)
            last_valid_result = result

        assert last_valid_result is not None
        assert isinstance(last_valid_result, ResponseObject)
        assert len(last_valid_result.response.movies) == 5

    def test_empty_movies(self):
        xml = """<response>"""
        result = parse_xml(xml, ResponseObject)
        assert result.response.movies == []


class Details(BaseModel):
    name: str = Field(...)
    title: str = Field(...)
    age: int = Field(...)
    birth_date: str = Field(...)
    birth_place: str = Field(...)
    nationality: str = Field(...)
    occupation: str = Field(...)


class TestDetails:
    def test_details(self):
        """Test parsing a response with details."""
        xml = load_test_file("details.xml")
        result = parse_xml(xml, Details)

        assert len(result.birth_date.split("-")) == 3
        assert result.age > 0
        assert "," in result.birth_place
        assert result.occupation.count(",") <= 1

    def test_details_streaming(self):
        xml = load_test_file("details.xml")
        partial_content = ""
        last_valid_result = None
        for char in xml:
            partial_content += char
            result = parse_xml(partial_content, Details)

            validate_parsed_model(result, Details)
            last_valid_result = result

        assert last_valid_result is not None
        assert isinstance(last_valid_result, Details)
        assert len(last_valid_result.birth_date.split("-")) == 3


class ChunkInfo(BaseModel):
    file_path: str = Field(..., description="The path of the file")
    content: str = Field(..., description="The content of the chunk")


class SearchResult(BaseModel):
    chunk_id: str = Field(..., description="The id of the chunk")
    chunk_info: ChunkInfo = Field(..., description="The info of the chunk")
    vector_similarity_score: float = Field(
        ..., description="The similarity score of the chunk"
    )


class SearchResponse(BaseModel):
    objective: str = Field(..., description="Idk")
    search_results: list[SearchResult] = Field(..., description="The search results")


class TestSearch:
    def test_search_response(self):
        search_file: str = load_test_file("search.xml")
        parsed = parse_xml(search_file, SearchResponse)
        validate_parsed_model(parsed, SearchResponse)

        # Validate specific fields
        assert parsed.objective, "Objective should not be empty"
        assert len(parsed.search_results) > 0, "Should have at least one search result"

        for result in parsed.search_results:
            assert (
                0 <= result.vector_similarity_score <= 1
            ), "Similarity score should be between 0 and 1"
            assert result.chunk_info.file_path, "File path should not be empty"
            assert result.chunk_info.content, "Content should not be empty"

    def test_search_response_streaming(self):
        search_file: str = load_test_file("search.xml")
        partial_content = ""
        last_valid_result = None
        for char in search_file:
            partial_content += char
            result = parse_xml(partial_content, SearchResponse)
            validate_parsed_model(result, SearchResponse)
            last_valid_result = result

        assert last_valid_result is not None
        assert isinstance(last_valid_result, SearchResponse)
        assert last_valid_result.objective
        assert len(last_valid_result.search_results) > 0


if __name__ == "__main__":
    import pytest

    pytest.main([__file__, "-v"])
