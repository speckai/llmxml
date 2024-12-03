import json
from pathlib import Path
from typing import Any, Dict, List, Literal, Type, TypeVar, Union

from pydantic import BaseModel, Field

from llmxml.parser import XMLSafeString, parse_xml

T = TypeVar("T", bound=BaseModel)


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
    # Validate model can be serialized/deserialized
    json_str = parsed.model_dump_json()
    assert json.loads(json_str), "Model should be JSON serializable"


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


class CodeAction(BaseModel):
    thinking: str = Field(default="", description="The thinking to perform")
    actions: List[Union[CreateAction, EditAction, CommandAction]] = Field(
        default_factory=list, description="The actions to perform"
    )


class TestActions:
    def test_complete_response(self):
        """Test parsing a complete response with multiple actions."""
        xml = load_test_file("complete.xml")
        result = parse_xml(CodeAction, xml)

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

    def test_complete_response_streaming(self):
        xml = load_test_file("complete.xml")
        partial_content = ""
        last_valid_result = None
        for char in xml:
            partial_content += char
            result = parse_xml(CodeAction, partial_content)
            if result is not None:
                validate_parsed_model(result, CodeAction)
                last_valid_result = result

        assert last_valid_result is not None
        assert isinstance(last_valid_result, CodeAction)
        assert len(last_valid_result.actions) > 0

    def test_partial_response(self):
        """Test parsing a partial response with incomplete action."""
        xml = load_test_file("partial.xml")
        result = parse_xml(CodeAction, xml)

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

    def test_partial_response_streaming(self):
        xml = load_test_file("partial.xml")
        partial_content = ""
        last_valid_result = None
        for char in xml:
            partial_content += char
            result = parse_xml(CodeAction, partial_content)
            if result is not None:
                validate_parsed_model(result, CodeAction)
                last_valid_result = result

        assert last_valid_result is not None
        assert isinstance(last_valid_result, CodeAction)
        assert len(last_valid_result.actions) == 1

    def test_streaming_response(self):
        """Test parsing a streaming response that's cut off mid-element."""
        xml = load_test_file("streaming.xml")
        result = parse_xml(CodeAction, xml)

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

    def test_streaming_response_streaming(self):
        xml = load_test_file("streaming.xml")
        partial_content = ""
        last_valid_result = None
        for char in xml:
            partial_content += char
            result = parse_xml(CodeAction, partial_content)
            if result is not None:
                validate_parsed_model(result, CodeAction)
                last_valid_result = result

        assert last_valid_result is not None
        assert isinstance(last_valid_result, CodeAction)
        assert len(last_valid_result.actions) == 1

    def test_empty_response(self):
        """Test parsing an empty response."""
        xml = ""
        result = parse_xml(CodeAction, xml)
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
        result = parse_xml(ResponseObject, xml)
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
            result = parse_xml(ResponseObject, partial_content)
            if result is not None:
                validate_parsed_model(result, ResponseObject)
                last_valid_result = result

        assert last_valid_result is not None
        assert isinstance(last_valid_result, ResponseObject)
        assert len(last_valid_result.response.movies) == 5

    def test_empty_movies(self):
        xml = """<response>"""
        result = parse_xml(ResponseObject, xml)
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
        result = parse_xml(Details, xml)

        # Additional validations
        assert len(result.birth_date.split("-")) == 3  # Validate date format
        assert result.age > 0
        assert "," in result.birth_place  # City, State format
        assert result.occupation.count(",") <= 1  # At most one comma in occupation

    def test_details_streaming(self):
        xml = load_test_file("details.xml")
        partial_content = ""
        last_valid_result = None
        for char in xml:
            partial_content += char
            result = parse_xml(Details, partial_content)
            if result is not None:
                validate_parsed_model(result, Details)
                last_valid_result = result

        assert last_valid_result is not None
        assert isinstance(last_valid_result, Details)
        assert len(last_valid_result.birth_date.split("-")) == 3


class Result(BaseModel):
    type: str = Field(...)
    data: Dict[str, Any] = Field(...)


class CustomResponse(BaseModel):
    status: str = Field(...)
    result: Result = Field(...)


class TestCustom:
    def test_custom_model(self):
        """Test that parser works with custom model structures."""
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

    def test_custom_model_streaming(self):
        xml = load_test_file("custom.xml")
        partial_content = ""
        last_valid_result = None

        for char in xml:
            partial_content += char
            result = parse_xml(CustomResponse, partial_content)
            if result is not None:
                validate_parsed_model(result, CustomResponse)
                last_valid_result = result

        assert last_valid_result is not None
        assert isinstance(last_valid_result, CustomResponse)
        assert last_valid_result.status in ["success", "error"]
        assert last_valid_result.result.type == "playlist_update"
        assert isinstance(last_valid_result.result.data, dict)
        assert "tracks" in last_valid_result.result.data
        assert isinstance(last_valid_result.result.data["tracks"], list)
        assert len(last_valid_result.result.data["tracks"]) > 0


class ChunkInfo(BaseModel):
    file_path: str = Field(..., description="The path of the file")
    content: XMLSafeString = Field(..., description="The content of the chunk")


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

    def test_search_response_streaming(self):
        search_file: str = load_test_file("search.xml")
        partial_content = ""
        last_valid_result = None
        for char in search_file:
            partial_content += char
            result = parse_xml(SearchResponse, partial_content)
            if result is not None:
                validate_parsed_model(result, SearchResponse)
                last_valid_result = result

        assert last_valid_result is not None
        assert isinstance(last_valid_result, SearchResponse)
        assert last_valid_result.objective
        assert len(last_valid_result.search_results) > 0


if __name__ == "__main__":
    import pytest

    pytest.main([__file__, "-v"])
