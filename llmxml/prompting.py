from typing import List, Literal, Type, Union, get_args

from pydantic import BaseModel, Field

ADHERE_INSTRUCTIONS_PROMPT = """
You are to understand the content and provide your output in the following xml-like format EXACTLY as described in the field_schema.

Each field in the field_schema has a description and a type.
Example:
<field_name>
[type]
[description]
</field_name>

Schema:
""".strip()


def _get_type_info(field_info) -> str:
    """Extract and format the type information from a field."""
    if hasattr(field_info.annotation, "__origin__"):
        origin = field_info.annotation.__origin__
        if origin is Literal:
            allowed_values = get_args(field_info.annotation)
            return f"type: Literal[{', '.join(map(str, allowed_values))}]"
        elif origin is list:
            args = get_args(field_info.annotation)[0]
            if hasattr(args, "__origin__") and args.__origin__ is Union:
                subtypes = get_args(args)
                type_names = [t.__name__ for t in subtypes]
                return f"type: list of {', '.join(map(repr, type_names))}"
    return f"type: {field_info.annotation.__name__}"


def _process_nested_union_list(field_name: str, field_info, type_info: str) -> str:
    """Process fields that are List[Union[...]] types with nested fields."""
    args = get_args(field_info.annotation)[0]
    if hasattr(args, "__origin__") and args.__origin__ is Union:
        subtypes = get_args(args)
        subtype_fields = []
        for idx, subtype in enumerate(subtypes, 1):
            if isinstance(subtype, type) and issubclass(subtype, BaseModel):
                subfields = subtype.model_fields
                subtype_fields.append(
                    f"\n# Option {idx}: {subtype.__name__}"
                    + "\n"
                    + "\n".join(
                        _process_field(name, info) for name, info in subfields.items()
                    )
                    + "\n"
                )
        description = field_info.description or f"Description of {field_name}"
        return (
            f"<{field_name}>\n[{type_info}]\n[{description}]"
            + "\nOR\n".join(subtype_fields)
            + f"\n</{field_name}>"
        )
    return ""


def _process_field(field_name: str, field_info) -> str:
    """Process a single field and return its XML representation."""
    type_info = _get_type_info(field_info)

    # Handle List[Union[...]] types with nested fields
    if (
        hasattr(field_info.annotation, "__origin__")
        and field_info.annotation.__origin__ is list
    ):
        nested_result = _process_nested_union_list(field_name, field_info, type_info)
        if nested_result:
            return nested_result

    description = field_info.description or f"Description of {field_name}"
    return f"<{field_name}>\n[{type_info}]\n[{description}]\n</{field_name}>"


def generate_prompt_template(
    model: Type[BaseModel], include_instructions: bool = True
) -> str:
    """Generates a prompt template from a Pydantic model."""
    # Process each field and join with double newlines
    fields = model.model_fields
    field_prompts = [_process_field(name, info) for name, info in fields.items()]
    template = "\n\n".join(field_prompts)

    if include_instructions:
        return f"<response_instructions>\n{ADHERE_INSTRUCTIONS_PROMPT}\n{template}\n</response_instructions>"
    return template


if __name__ == "__main__":
    # Example usage:

    class CreateAction(BaseModel):
        action_type: Literal["create"] = Field(
            ..., description="The type of action to perform"
        )
        new_file_path: str = Field(
            ..., description="The path to the new file to create"
        )
        file_contents: str = Field(
            ..., description="The contents of the new file to create"
        )

    prompt_template = generate_prompt_template(CreateAction)
    # print(prompt_template)

    class CreateAction(BaseModel):
        action_type: Literal["create"] = Field(
            ..., description="The type of action to perform"
        )
        new_file_path: str = Field(
            ..., description="The path to the new file to create"
        )
        file_contents: str = Field(
            ..., description="The contents of the new file to create"
        )

    class EditAction(BaseModel):
        action_type: Literal["edit"] = Field(...)
        original_file_path: str = Field(
            ..., description="The path to the original file to edit"
        )
        new_file_contents: str = Field(
            ..., description="The contents of the edited file"
        )

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

    prompt_template = generate_prompt_template(Action)
    print(prompt_template)
