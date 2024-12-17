import types
from typing import List, Literal, Type, Union, get_args

from pydantic import BaseModel, Field


def ADHERE_INSTRUCTIONS_PROMPT(schema: str) -> str:
    return (
        """
You are to provide your output in the following xml-like format EXACTLY as described in the schema provided.
Each field in the schema has a description and a type enclosed in square brackets, denoting that they are metadata.
Format instructions:
<field_name>
[object_type]
[required/optional]
[description]
</field_name>

Basic example:
<EXAMPLE>
<EXAMPLE_SCHEMA>
<thinking>
[type: str]
[optional]
[Chain of thought]
</thinking>
<actions>
# Option 1: CommandAction
<command_action>
<action_type>
[type: Literal["command"]]
[required]
[The type of action to perform]
</action_type>
<command>
[type: str]
[required]
[The command to run]
</command>
</command_action>

OR

# Option 2: CreateAction
<create_action>
<action_type>
[type: Literal["create"]]
[required]
[The type of action to perform]
</action_type>
<new_file_path>
[type: str]
[required]
[The path to the new file to create]
</new_file_path>
<file_contents>
[type: str]
[required]
[The contents of the new file to create]
</file_contents>
</create_action>

OR

# Option 3: EditAction
<edit_action>
<action_type>
[type: Literal["edit"]]
[required]
[The type of action to perform]
</action_type>
<original_file_path>
[type: str]
[required]
[The path to the original file to edit]
</original_file_path>
<new_file_contents>
[type: str]
[required]
[The contents of the edited file]
</new_file_contents>
</edit_action>
</actions>
</EXAMPLE_SCHEMA>

<EXAMPLE_OUTPUT>
<thinking>
First, I need to create a new configuration file. Then, I'll modify an existing source file to use the new configuration.
</thinking>
<actions>
<create_action>
<action_type>create</action_type>
<new_file_path>config/settings.json</new_file_path>
<file_contents>interface Config {
  apiKey: string;
  baseUrl: string;
  timeout: number;
}
const config: Config = {
  apiKey: "your-api-key-here",
  baseUrl: "https://api.example.com",
  timeout: 30
};</file_contents>
</create_action>
<edit_action>
<action_type>edit</action_type>
<original_file_path>src/main.py</original_file_path>
<new_file_contents>import json
def load_config():
    with open('config/settings.json', 'r') as f:
        return json.load(f)
def main():
    config = load_config()
    print(f"Connecting to {config['base_url']}...")
if __name__ == '__main__':
    main()
</new_file_contents>
</edit_action>
</actions>
</EXAMPLE_OUTPUT>
</EXAMPLE>
""".strip()
        + "\n\n"
        + f"""
Requested Response Schema:
{schema}
Make sure to return an instance of the output, NOT the schema itself. Do NOT include any schema metadata (like [type: ...]) in your output.
""".strip()
    )


def ADHERE_INSTRUCTIONS_PROMPT_GENERAL(schema: str) -> str:
    return (
        """
You are to provide your output in the following xml-like format EXACTLY as described in the schema provided.
Each field in the schema has a description, type, and requirement status enclosed in square brackets, denoting that they are metadata.
Format instructions:
<field_name>
[type: object_type]
[required/optional]
[description]
</field_name>

Basic example:
<EXAMPLE>
<EXAMPLE_SCHEMA>
<reasoning>
[type: str]
[optional]
[Detailed thought process explaining the approach]
</reasoning>
<actions>
# Option 1: DirectAction
<direct_action>
<action_type>
[type: Literal["direct"]]
[required]
[Immediate action to be performed]
</action_type>
<instruction>
[type: str]
[required]
[The specific instruction to execute]
</instruction>
<priority>
[type: str]
[optional]
[Priority level of the action]
</priority>
</direct_action>

OR # Option 2: GenerateAction
<generate_action>
<action_type>
[type: Literal["generate"]]
[required]
[Creation of new content/resource]
</action_type>
<resource_identifier>
[type: str]
[required]
[Unique identifier for the new resource]
</resource_identifier>
<resource_content>
[type: str]
[required]
[The content/data to be generated]
</resource_content>
<metadata>
[type: str]
[optional]
[Additional information about the resource]
</metadata>
</generate_action>

OR # Option 3: ModifyAction
<modify_action>
<action_type>
[type: Literal["modify"]]
[required]
[Modification of existing content/resource]
</action_type>
<target_identifier>
[type: str]
[required]
[Identifier of the resource to modify]
</target_identifier>
<updated_content>
[type: str]
[required]
[The modified content/data]
</updated_content>
<backup_needed>
[type: bool]
[optional]
[Whether to create backup before modification]
</backup_needed>
</modify_action>
</actions>
</EXAMPLE_SCHEMA>

<EXAMPLE_OUTPUT>
<reasoning>
To accomplish the task, we'll first generate a new configuration resource with required parameters, then modify an existing resource while ensuring we create a backup.
</reasoning>
<actions>
<generate_action>
<action_type>generate</action_type>
<resource_identifier>resources/config.json</resource_identifier>
<resource_content>{
  "type": "configuration",
  "parameters": {
    "primary": "value1",
    "secondary": "value2",
    "timeout": 30
  }
}</resource_content>
<metadata>Version: 1.0, Environment: Production</metadata>
</generate_action>

<modify_action>
<action_type>modify</action_type>
<target_identifier>resources/main.json</target_identifier>
<updated_content>{
  "type": "resource",
  "dependencies": ["configuration"],
  "properties": {
    "uses_config": true,
    "version": "1.0"
  }
}</updated_content>
<backup_needed>true</backup_needed>
</modify_action>
</actions>
</EXAMPLE_OUTPUT>
</EXAMPLE>
""".strip()
        + "\n\n"
        + f"""
Requested Response Schema:
{schema}

Make sure to return an instance of the output, NOT the schema itself. Do NOT include any schema metadata (like [type: ...]) in your output.
""".strip()
    )

def _get_type_info(field_info) -> str:
    """Extract and format the type information from a field."""
    if (
        hasattr(field_info.annotation, "__name__")
        and field_info.annotation.__name__ == "XMLSafeString"
    ):
        return "type: str"

    if (
        hasattr(field_info.annotation, "__origin__")
        and field_info.annotation.__origin__ is Union
    ) or (isinstance(field_info.annotation, types.UnionType)):
        subtypes = get_args(field_info.annotation)
        type_names = [
            t.__name__ if hasattr(t, "__name__") else str(t).replace("NoneType", "None")
            for t in subtypes
        ]
        return f"type: {' | '.join(type_names)}"

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
                # Convert CamelCase to snake_case for the model name
                model_name = "".join(
                    ["_" + c.lower() if c.isupper() else c for c in subtype.__name__]
                ).lstrip("_")
                subtype_fields.append(
                    f"\n# Option {idx}: {subtype.__name__}"
                    + f"\n<{model_name}>"
                    + "\n"
                    + "\n".join(
                        _process_field(name, info) for name, info in subfields.items()
                    )
                    + f"\n</{model_name}>"
                    + "\n"
                )
        if field_info.description:
            return (
                f"<{field_name}>\n[{type_info}]\n[{field_info.description}]"
                + "\nOR\n".join(subtype_fields)
                + f"\n</{field_name}>"
            )
        else:
            return (
                f"<{field_name}>\n[{type_info}]"
                + "\nOR\n".join(subtype_fields)
                + f"\n</{field_name}>"
            )
    return ""


def _process_field(field_name: str, field_info) -> str:
    """Process a single field and return its XML representation."""
    type_info = _get_type_info(field_info)
    required_info = "required" if field_info.is_required() else "optional"
    description = field_info.description or f"Description of {field_name}"

    # Handle list types
    if (
        hasattr(field_info.annotation, "__origin__")
        and field_info.annotation.__origin__ is list
    ):
        # Get the type of items in the list
        item_type = get_args(field_info.annotation)[0]

        # If the list contains Pydantic models, show the structure of a single item
        if isinstance(item_type, type) and issubclass(item_type, BaseModel):
            nested_fields = item_type.model_fields
            item_name = item_type.__name__.lower()
            nested_prompts = [
                _process_field(name, info) for name, info in nested_fields.items()
            ]
            return (
                f"<{field_name}>\n[{type_info}]\n[{required_info}]\n[{description}]\n"
                f"<{item_name}>\n" + "\n".join(nested_prompts) + f"\n</{item_name}>\n"
                f"</{field_name}>"
            )

        # Handle other list types including List[Union[...]]
        nested_result = _process_nested_union_list(field_name, field_info, type_info)
        if nested_result:
            return nested_result

    # Handle nested Pydantic models
    if isinstance(field_info.annotation, type) and issubclass(
        field_info.annotation, BaseModel
    ):
        nested_fields = field_info.annotation.model_fields
        nested_prompts = [
            _process_field(name, info) for name, info in nested_fields.items()
        ]
        return (
            f"<{field_name}>\n[{type_info}]\n[{required_info}]\n[{description}]\n"
            + "\n".join(nested_prompts)
            + f"\n</{field_name}>"
        )

    return f"<{field_name}>\n[{type_info}]\n[{required_info}]\n[{description}]\n</{field_name}>"


def generate_prompt_template(
    model: Type[BaseModel], include_instructions: bool = True
) -> str:
    """Generates a prompt template from a Pydantic model."""
    # Process each field and join with double newlines
    fields = model.model_fields
    field_prompts = [_process_field(name, info) for name, info in fields.items()]
    template = "\n".join(field_prompts)

    if include_instructions:
        return f"<response_instructions>\n{ADHERE_INSTRUCTIONS_PROMPT_GENERAL(template)}\n</response_instructions>"
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

    x = generate_prompt_template(ResponseObject)
    print(x)
