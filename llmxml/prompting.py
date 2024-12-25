import re
import types
from enum import Enum
from typing import Literal, Type, Union, get_args, get_origin

from pydantic import BaseModel, Field
from pydantic.fields import FieldInfo


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


def _get_type_info(field_info: FieldInfo) -> str:
    """
    Extract and format the type information from a field.
    :param field_info: The field info to extract type information from.
    :return: A string representation of the type information.
    """
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


def _process_nested_union_list(
    field_name: str, field_info: FieldInfo, type_info: str
) -> str:
    """
    Process fields that are list[Union[...]] or list[X|Y|Z] types with nested fields.
    :param field_name: The name of the field to process.
    :param field_info: The field info to process.
    :param type_info: The type information to use.
    :return: An XML string representation of the field.
    """
    args = get_args(field_info.annotation)[0]
    # Check for both typing.Union and Python 3.10+ builtin union (types.UnionType)
    if (hasattr(args, "__origin__") and args.__origin__ is Union) or (
        isinstance(args, types.UnionType)
    ):
        subtypes = get_args(args)
        subtype_fields = []
        for idx, subtype in enumerate(subtypes, 1):
            if isinstance(subtype, type) and issubclass(subtype, BaseModel):
                subfields = subtype.model_fields
                # Convert CamelCase to snake_case for the model name
                model_name = "".join(
                    [f"_{c.lower()}" if c.isupper() else c for c in subtype.__name__]
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
        description = field_info.description or f"Description of {field_name}"
        return (
            f"<{field_name}>\n[{type_info}]\n[{description}]"
            + "\nOR\n".join(subtype_fields)
            + f"\n</{field_name}>"
        )

    return ""  # Default return if it's not a nested union list


def _process_field(field_name: str, field_info: FieldInfo) -> str:
    """
    Process a single field and return its XML representation.
    :param field_name: The name of the field to process.
    :param field_info: The field info to process.
    :return: An XML string representation of the field.
    """
    type_info: str = _get_type_info(field_info)
    required_info: str = "required" if field_info.is_required() else "optional"
    description: str = field_info.description or f"Description of {field_name}"

    if (
        hasattr(field_info.annotation, "__origin__")
        and field_info.annotation.__origin__ is list
    ):
        item_type: type = get_args(field_info.annotation)[0]

        if isinstance(item_type, type) and issubclass(item_type, BaseModel):
            nested_fields: dict[str, FieldInfo] = item_type.model_fields
            item_name: str = item_type.__name__.lower()
            nested_prompts: list[str] = [
                _process_field(name, info) for name, info in nested_fields.items()
            ]
            return (
                f"<{field_name}>\n[{type_info}]\n[{required_info}]\n[{description}]\n"
                f"<{item_name}>\n" + "\n".join(nested_prompts) + f"\n</{item_name}>\n"
                f"</{field_name}>"
            )

        nested_result: str = _process_nested_union_list(
            field_name, field_info, type_info
        )
        if nested_result:
            return nested_result

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
    """
    Generates a prompt template from a Pydantic model.
    :param model: The Pydantic model to generate a prompt template for.
    :param include_instructions: Whether to include instructions in the prompt template.
    :return: A string representation of the prompt template.
    """
    fields: dict[str, FieldInfo] = model.model_fields
    field_prompts: list[str] = [
        _process_field(name, info) for name, info in fields.items()
    ]
    template: str = "\n".join(field_prompts)

    if include_instructions:
        return f"<response_instructions>\n{ADHERE_INSTRUCTIONS_PROMPT_GENERAL(template)}\n</response_instructions>"
    return template


def generate_example(instance: BaseModel) -> str:
    """
    Generates an XML representation of the given Pydantic model instance,
    reusing its actual field values (rather than sample placeholders).
    :param instance: The Pydantic model instance to generate an example for.
    :return: An XML string representation of the instance.
    """

    def _camel_to_snake(name: str) -> str:
        """Convert a CamelCase string to snake_case.
        :param name: The string to convert.
        :return: A snake_case string.
        """
        return re.sub(r"(?!^)([A-Z]+)", r"_\1", name).lower()

    def _to_str(value: any) -> str:
        """Converts any primitive value to string.
        :param value: The value to convert to string.
        :return: A string representation of the value.
        """
        return "" if value is None else str(value)

    def _generate_field_xml(field_name: str, value: any, annotation: type) -> str:
        """
        Produce <field_name>...</field_name>, interpreting type annotation if needed.
        :param field_name: The name of the field to produce XML for.
        :param value: The value of the field to produce XML for.
        :param annotation: The type annotation of the field to produce XML for.
        :return: An XML string representation of the field.
        """
        origin: type = get_origin(annotation)

        def _to_str(val: any) -> str:
            return "" if val is None else str(val)

        if origin is Union or isinstance(annotation, types.UnionType):
            union_args: tuple = (
                annotation.__args__
                if isinstance(annotation, types.UnionType)
                else get_args(annotation)
            )
            if value is None:
                return f"<{field_name}></{field_name}>"
            for arg in union_args:
                if arg is not type(None) and isinstance(value, arg):
                    return _generate_field_xml(field_name, value, arg)
            return f"<{field_name}>{_to_str(value)}</{field_name}>"

        if origin is list:
            (inner_type,) = get_args(annotation)
            if value is None:
                value = []
            xml_pieces: list[str] = []
            for item in value:
                xml_pieces.append(_generate_field_xml(field_name, item, inner_type))

            return "\n".join(xml_pieces)

        if isinstance(annotation, type) and issubclass(annotation, BaseModel):
            if value is None:
                # If the value is None, just output empty tags for the nested model
                model_tag: str = re.sub(
                    r"(?!^)([A-Z]+)", r"_\1", annotation.__name__
                ).lower()
                return f"<{field_name}>\n<{model_tag}></{model_tag}>\n</{field_name}>"
            return f"<{field_name}>\n{_generate_model_xml(value)}\n</{field_name}>"

        if isinstance(annotation, type) and issubclass(annotation, Enum):
            return (
                f"<{field_name}>{_to_str(value.value if value else '')}</{field_name}>"
            )

        return f"<{field_name}>{_to_str(value)}</{field_name}>"

    def _generate_model_xml(model_instance: Type[BaseModel]) -> str:
        """
        Recursively generate the XML from a model instance.
        The top-level tag for this sub-block is the snake-cased name of the instance's class.
        :param model_instance: The Pydantic model instance to generate an example for.
        :return: An XML string representation of the instance.
        """
        model_tag: str = _camel_to_snake(model_instance.__class__.__name__)
        lines: list[str] = [f"<{model_tag}>"]
        for field_name, field_info in model_instance.model_fields.items():
            annotation = field_info.annotation
            value = getattr(model_instance, field_name, None)
            lines.append(_generate_field_xml(field_name, value, annotation))
        lines.append(f"</{model_tag}>")
        return "\n".join(lines)

    if isinstance(instance, type) and issubclass(instance, BaseModel):
        raise TypeError(
            "generate_example() expected a Pydantic model instance, not the class. "
            "Create an instance first, then pass it in."
        )

    return _generate_model_xml(instance)


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
        actions: list[Union[CreateAction, EditAction, CommandAction]] = Field(
            default_factory=list, description="The actions to perform"
        )

    print(generate_prompt_template(Action))

    action = Action(
        thinking="First, I need to create a new configuration file. Then, I'll modify an existing source file to use the new configuration.",
        actions=[
            CreateAction(
                action_type="create",
                new_file_path="config/settings.json",
                file_contents='interface Config { apiKey: string; baseUrl: string; timeout: number; } const config: Config = { apiKey: "your-api-key-here", baseUrl: "https://api.example.com", timeout: 30 };',
            ),
            EditAction(
                action_type="edit",
                original_file_path="src/main.py",
                new_file_contents='import json\n\ndef load_config():\n    with open("config/settings.json", "r") as f:\n        return json.load(f)\n\ndef main():\n    config = load_config()\n    print(f"Connecting to {config[\'baseUrl\']}...")\n\nif __name__ == "__main__":\n    main()',
            ),
        ],
    )

    example = generate_example(action)
    print(example)

    class SomeField(Enum):
        A = "A"
        B = "B"

    class ExampleResponse(BaseModel):
        response: SomeField = Field(..., description="The response to the query")

    example_response = ExampleResponse(response=SomeField.A)

    example = generate_example(example_response)
    print(example)

    # prompt_template = generate_prompt_template(Action)
    # print(prompt_template)

    # class Movie(BaseModel):
    #     title: str = Field(..., description="The title of the movie")
    #     director: str = Field(..., description="The director of the movie")

    # class Response(BaseModel):
    #     movies: list[Movie] = Field(
    #         ..., description="A list of movies that match the query"
    #     )

    # class ResponseObject(BaseModel):
    #     response: Response = Field(
    #         ..., description="The response object that contains the movies"
    #     )

    # x = generate_prompt_template(ResponseObject)
    # print(x)
