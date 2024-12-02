import json
from pathlib import Path
from typing import Any, Dict, List, Literal, Type, TypeVar, Union

from llmxml.parser import parse_xml
from pydantic import BaseModel, Field

T = TypeVar("T", bound=BaseModel)


# Action models from tests
class CreateAction(BaseModel):
    action_type: Literal["create"] = Field(
        ..., description="The type of action to perform"
    )
    new_file_path: str = Field(..., description="The path to the new file to create")
    file_contents: str = Field(
        ..., description="The contents of the new file to create"
    )


class EditAction(BaseModel):
    action_type: Literal["edit"] = Field(...)
    original_file_path: str = Field(
        ..., description="The path to the original file to edit"
    )
    new_file_contents: str = Field(..., description="The contents of the edited file")


class CommandAction(BaseModel):
    action_type: Literal["command"] = Field(
        ..., description="The type of action to perform"
    )
    command: str = Field(..., description="The command to run")


class Action(BaseModel):
    thinking: str = Field(default="", description="The thinking to perform")
    actions: List[Union[CreateAction, EditAction, CommandAction]] = Field(
        default_factory=list, description="The actions to perform"
    )


def load_test_file(filename: str) -> str:
    """Load test file content."""
    test_dir = Path(__file__).parent / "test_files"
    with open(test_dir / filename, "r") as f:
        return f.read()


def test_complete_response():
    """Test parsing a complete response with multiple actions."""
    xml = load_test_file("complete.xml")
    result = parse_xml(Action, xml)

    # More detailed assertions
    assert result.thinking.strip() != ""
    assert "Component Structure:" in result.thinking
    assert "Implementation Details:" in result.thinking

    # Validate first action (CreateAction)
    create_action = result.actions[0]
    assert create_action.new_file_path.endswith(".tsx")
    assert "import" in create_action.file_contents
    assert "SearchBar" in create_action.file_contents

    # Validate second action (CommandAction)
    command_action = result.actions[1]
    assert "npm install" in command_action.command
    assert "lodash" in command_action.command

    # Validate third action (EditAction)
    edit_action = result.actions[2]
    assert edit_action.original_file_path.endswith(".tsx")
    assert "SearchBar" in edit_action.new_file_contents


def test_partial_response():
    """Test parsing a partial response with incomplete action."""
    xml = load_test_file("partial.xml")
    result = parse_xml(Action, xml)

    # Validate thinking section
    assert "Component Structure:" in result.thinking
    assert "Implementation Details:" in result.thinking

    # Validate the single action
    assert len(result.actions) == 1
    action = result.actions[0]
    assert isinstance(action, CreateAction)
    assert action.new_file_path == "components/PlaylistGrid.tsx"
    assert "PlaylistGrid" in action.file_contents
    assert "grid" in action.file_contents.lower()


def test_streaming_response():
    """Test parsing a streaming response that's cut off mid-element."""
    xml = load_test_file("streaming.xml")
    result = parse_xml(Action, xml)

    # Validate thinking structure
    assert "Component Structure:" in result.thinking
    assert "Implementation Details:" in result.thinking
    assert all(
        item in result.thinking for item in ["Play/pause button", "Volume control"]
    )

    # Validate partial action
    assert len(result.actions) == 1
    action = result.actions[0]
    assert isinstance(action, CreateAction)
    assert action.new_file_path == "components/PlayerControls.tsx"
    assert "PlayerControls" in action.file_contents


def test_empty_response():
    """Test parsing an empty response."""
    xml = ""
    result = parse_xml(Action, xml)
    print(result.model_dump_json(indent=2))
    assert result.thinking == ""
    assert len(result.actions) == 0


def test_small_response_1():
    xml = """<response>

    """

    class Response(BaseModel):
        movies: list[str] = Field(..., description="A list of movies")

    class ResponseObject(BaseModel):
        response: Response = Field(..., description="The response object")

    result = parse_xml(ResponseObject, xml)
    assert result.response.movies == []


def test_small_response_2():
    xml = """<response>
<
    """

    class Response(BaseModel):
        movies: list[str] = Field(..., description="A list of movies")

    class ResponseObject(BaseModel):
        response: Response = Field(..., description="The response object")

    result = parse_xml(ResponseObject, xml)
    assert result.response.movies == []


def test_small_response_3():
    xml = """<response>
<movies>
<movie>
<title>
Avatar
</title>
<director>
James Cameron
</director>
</movie>
<movie>
<title>
Avengers: Endgame
</title>
<director>
Anthony Russo, Joe Russo
</director>
</movie>
<movie>
<title>
Titanic
</title>
<director>
James Cameron
</director>
</movie>
<movie>
<title>
Star Wars: The Force Awakens
</title>
<director>
J.J. Abrams
</director>
</movie>
<movie>
<title>
Jurassic World
</title>
<director>
Colin Trevorrow
</director>
</movie>
</movies>
</response>
    """

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

    result = parse_xml(ResponseObject, xml)
    assert len(result.response.movies) == 5
    assert result.response.movies[0].title == "Avatar"
    assert result.response.movies[1].title == "Avengers: Endgame"
    assert result.response.movies[2].title == "Titanic"
    assert result.response.movies[3].title == "Star Wars: The Force Awakens"
    assert result.response.movies[4].title == "Jurassic World"


# TODO: Fix this test
# def test_small_response_4():
#     xml = """<response>
# <movies>
# <movie>
# <title>Avatar
#     """

#     class Movie(BaseModel):
#         title: str = Field(..., description="The title of the movie")
#         director: str = Field(..., description="The director of the movie")

#     class Response(BaseModel):
#         movies: list[Movie] = Field(
#             ..., description="A list of movies that match the query"
#         )

#     class ResponseObject(BaseModel):
#         response: Response = Field(
#             ..., description="The response object that contains the movies"
#         )

#     result = parse_xml(ResponseObject, xml)
#     print(result.response.movies)
#     assert len(result.response.movies) == 1
#     assert result.response.movies[0].title == "Avatar"
#     assert result.response.movies[0].director == ""


def test_code_blocks():
    """Test parsing response with code blocks containing XML-like content."""
    xml = load_test_file("complete.xml")
    result = parse_xml(Action, xml)
    assert isinstance(result, Action)
    assert isinstance(result.actions[0], CreateAction)
    assert "<div" in result.actions[0].file_contents


def test_details():
    """Test parsing a response with details."""

    class Details(BaseModel):
        name: str = Field(...)
        title: str = Field(...)
        age: int = Field(...)
        birth_date: str = Field(...)
        birth_place: str = Field(...)
        nationality: str = Field(...)
        occupation: str = Field(...)

    xml = load_test_file("details.xml")
    result = parse_xml(Details, xml)

    # Additional validations
    assert len(result.birth_date.split("-")) == 3  # Validate date format
    assert result.age > 0
    assert "," in result.birth_place  # City, State format
    assert result.occupation.count(",") <= 1  # At most one comma in occupation


def test_movies():
    """Test parsing a response with a list of movies."""

    class Movies(BaseModel):
        movies: List[str] = Field(default_factory=list)

    xml = load_test_file("movies.xml")
    result = parse_xml(Movies, xml)
    assert len(result.movies) == 10
    assert "Forrest Gump" in result.movies


def test_custom_model():
    """Test that parser works with custom model structures."""

    class Result(BaseModel):
        type: str = Field(...)
        data: Dict[str, Any] = Field(...)

    class CustomResponse(BaseModel):
        status: str = Field(...)
        result: Result = Field(...)

    xml = load_test_file("custom.xml")
    result = parse_xml(CustomResponse, xml)

    # Validate nested structure
    assert result.status in ["success", "error"]
    assert result.result.type == "playlist_update"
    assert isinstance(result.result.data, dict)
    assert "tracks" in result.result.data
    assert isinstance(result.result.data["tracks"], list)
    assert len(result.result.data["tracks"]) > 0

    # Validate track structure
    track = result.result.data["tracks"][0]
    assert all(key in track for key in ["id", "title", "artist"])


def test_nested_structures():
    """Test parsing deeply nested structures."""
    xml = load_test_file("complete.xml")
    result = parse_xml(Action, xml)
    assert "import" in result.actions[0].file_contents


def validate_parsed_model(parsed: BaseModel, model_class: Type[T]) -> None:
    """Helper function to validate parsed models"""
    assert (
        isinstance(parsed, model_class)
        or type(parsed).__name__.startswith(f"Partial{model_class.__name__}")
    ), f"Expected {model_class.__name__} or Partial{model_class.__name__}, got {type(parsed).__name__}"
    # Validate model can be serialized/deserialized
    json_str = parsed.model_dump_json()
    assert json.loads(json_str), "Model should be JSON serializable"


def test_search_response():
    search_file: str = load_test_file("search.xml")

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
        search_results: list[SearchResult] = Field(
            ..., description="The search results"
        )

    parsed = parse_xml(SearchResponse, search_file)
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


def test_action_file():
    action_file: str = load_test_file("action.xml")

    class Action(BaseModel):
        action_type: str = Field(..., description="The type of action")
        new_file_path: str = Field(..., description="The path of the new file")
        file_contents: str = Field(..., description="The contents of the new file")

    class ActionResponse(BaseModel):
        thinking: str = Field(..., description="The thinking of the action")
        actions: list[Action] = Field(..., description="The actions to take")

    parsed = parse_xml(ActionResponse, action_file)
    validate_parsed_model(parsed, ActionResponse)

    # Validate specific fields
    assert parsed.thinking, "Thinking should not be empty"
    assert len(parsed.actions) > 0, "Should have at least one action"

    for action in parsed.actions:
        assert action.action_type in [
            "new_file",
            "modify_file",
            "delete_file",
        ], "Invalid action type"
        assert action.new_file_path.endswith(
            (".tsx", ".ts", ".js", ".jsx")
        ), "Invalid file extension"
        assert action.file_contents, "File contents should not be empty"


def test_streaming_action_by_char():
    """Test parsing an action file by reading it character by character."""
    action_file: str = load_test_file("action.xml")

    class Action(BaseModel):
        action_type: str = Field(..., description="The type of action")
        new_file_path: str = Field(..., description="The path of the new file")
        file_contents: str = Field(..., description="The contents of the new file")

    class ActionResponse(BaseModel):
        thinking: str = Field(..., description="The thinking of the action")
        actions: list[Action] = Field(..., description="The actions to take")

    # Read and parse file character by character
    partial_content = ""
    last_valid_result = None

    for char in action_file:
        partial_content += char
        result = parse_xml(ActionResponse, partial_content)
        if result is not None:
            validate_parsed_model(result, ActionResponse)
            # Only update last_valid_result if we have a complete model
            if isinstance(result, ActionResponse):
                last_valid_result = result

    assert last_valid_result is not None, "Should have at least one valid parse"
    assert isinstance(
        last_valid_result, ActionResponse
    ), "Final result should be a complete model"

    # Validate the final result matches full parse
    full_parse = parse_xml(ActionResponse, action_file)
    assert isinstance(
        full_parse, ActionResponse
    ), "Full parse should be a complete model"
    assert (
        last_valid_result.model_dump() == full_parse.model_dump()
    ), "Streaming parse should match full parse"


if __name__ == "__main__":
    import pytest

    pytest.main([__file__, "-v"])
