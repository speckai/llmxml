from typing import List, Literal, Union

from pydantic import BaseModel, Field

from llmxml.prompting import generate_example, generate_prompt_template


class CreateAction(BaseModel):
    action_type: Literal["create"] = Field(
        ..., description="The type of action to perform"
    )
    new_file_path: str = Field(..., description="The path to the new file to create")
    file_contents: str = Field(
        ..., description="The contents of the new file to create"
    )


class EditAction(BaseModel):
    action_type: Literal["edit"] = Field(
        ..., description="The type of action to perform"
    )
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


def test_simple_model_prompt():
    """Test prompt generation for a simple model with basic fields."""
    expected = (
        "<action_type>\n[type: Literal[create]]\n[required]\n[The type of action to perform]\n</action_type>\n"
        "<new_file_path>\n[type: str]\n[required]\n[The path to the new file to create]\n</new_file_path>\n"
        "<file_contents>\n[type: str]\n[required]\n[The contents of the new file to create]\n</file_contents>"
    )
    result = generate_prompt_template(CreateAction, include_instructions=False)
    assert result == expected


def test_complex_model_with_nested_types():
    """Test prompt generation for a model with nested types and unions."""
    result = generate_prompt_template(Action)

    # Check for main fields
    assert "<thinking>" in result
    assert "[type: str]" in result
    assert "[The thinking to perform]" in result

    # Check for nested types in actions field
    assert "<actions>" in result
    assert "type: list of" in result
    assert "'CreateAction', 'EditAction', 'CommandAction'" in result

    # Check for nested model fields
    assert "<action_type>" in result
    assert "<new_file_path>" in result
    assert "<original_file_path>" in result
    assert "<command>" in result


def test_default_description():
    """Test prompt generation handles missing descriptions properly."""

    class SimpleModel(BaseModel):
        field_without_description: str = Field(...)

    result = generate_prompt_template(SimpleModel)
    assert "Description of field_without_description" in result


def test_literal_type_handling():
    """Test proper handling of Literal types."""

    class LiteralModel(BaseModel):
        status: Literal["active", "inactive"] = Field(...)

    result = generate_prompt_template(LiteralModel)
    assert "type: Literal[active, inactive]" in result


def test_empty_model():
    """Test handling of empty models."""

    class EmptyModel(BaseModel):
        pass

    result = generate_prompt_template(EmptyModel, include_instructions=False)
    assert result == ""


def test_optional_fields():
    """Test prompt generation for a model with optional fields."""

    class ModelWithOptional(BaseModel):
        required_field: str = Field(..., description="A required field")
        optional_field: str | None = Field(None, description="An optional field")

    result = generate_prompt_template(ModelWithOptional, include_instructions=False)
    print(result)
    print("---")
    expected = (
        "<required_field>\n[type: str]\n[required]\n[A required field]\n</required_field>\n"
        "<optional_field>\n[type: str | NoneType]\n[optional]\n[An optional field]\n</optional_field>"
    )
    print(expected)
    assert result == expected


def test_example_generation():
    example_action = Action(
        thinking="Thinking about the action",
        actions=[
            CreateAction(
                action_type="create",
                new_file_path="file.txt",
                file_contents="Hello, world!",
            )
        ],
    )

    generated_example: str = generate_example(example_action)
    assert generated_example is not None
    assert generated_example != ""


if __name__ == "__main__":
    test_optional_fields()
