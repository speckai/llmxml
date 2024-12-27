from enum import Enum
import re
import types
from typing import List, Literal, Type, Union, get_args, get_origin
from pydantic import BaseModel, Field
from pydantic.fields import FieldInfo

from llmxml.prompting import _process_field

def generate_base_instructions() -> str:
    return """
You are to provide your output in the following xml-like format EXACTLY as described in the schema provided.
Each field in the schema has a description, type, and requirement status enclosed in square brackets, denoting that they are metadata.
Format instructions:
<field_name>
[type: object_type]
[required/optional]
[description if available]
[enum values if applicable]
</field_name>

If the field is a list, you create a new <field_name> for each item in the list.
""".strip()

class Priority(Enum):
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"

class ResourceType(Enum):
    CONFIG = "configuration"
    DATA = "data"
    TEMPLATE = "template"

class DirectAction(BaseModel):
    action_type: Literal["direct"] = Field(..., description="Immediate action to be performed")
    instruction: str = Field(..., description="The specific instruction to execute")
    priority: Priority = Field(..., description="Priority level of the action")

class GenerateAction(BaseModel):
    action_type: Literal["generate"] = Field(..., description="Creation of new content/resource")
    resource_identifier: str = Field(..., description="Unique identifier for the new resource")
    resource_type: ResourceType = Field(..., description="Type of resource being generated")
    resource_content: str = Field(..., description="The content/data to be generated")
    metadata: str | None = Field(None, description="Additional information about the resource")

class ModifyAction(BaseModel):
    action_type: Literal["modify"] = Field(..., description="Modification of existing content/resource")
    target_identifier: str = Field(..., description="Identifier of the resource to modify")
    updated_content: str = Field(..., description="The modified content/data")
    backup_needed: bool | None = Field(None, description="Whether to create backup before modification")

class ExampleSchema(BaseModel):
    reasoning: str | None = Field(None, description="Detailed thought process explaining the approach")
    actions: list[Union[DirectAction, GenerateAction, ModifyAction]] = Field(..., description="The actions to perform")

def generate_example_output() -> str:
    example = ExampleSchema(
        reasoning="To accomplish the task, we'll first generate a new configuration resource with required parameters, then modify an existing resource while ensuring we create a backup.",
        actions=[
            GenerateAction(
                action_type="generate",
                resource_identifier="resources/config.json",
                resource_type=ResourceType.CONFIG,
                resource_content='''{
  "type": "configuration",
  "parameters": {
    "primary": "value1",
    "secondary": "value2",
    "timeout": 30
  }
}''',
                metadata="Version: 1.0, Environment: Production"
            ),
            DirectAction(
                action_type="direct",
                instruction="Update system cache",
                priority=Priority.HIGH
            )
        ]
    )
    return generate_example(example)

def ADHERE_INSTRUCTIONS_PROMPT(schema: str) -> str:
    return "\n\n".join([
        generate_base_instructions(),
        "Basic example:",
        "<EXAMPLE>",
        "<EXAMPLE_SCHEMA>",
        _generate_template_string(ExampleSchema),
        "</EXAMPLE_SCHEMA>",
        "",
        "<EXAMPLE_OUTPUT>",
        generate_example_output(),
        "</EXAMPLE_OUTPUT>",
        "</EXAMPLE>",
        "",
        "Requested Response Schema:",
        schema,
        "",
        "Make sure to return an instance of the output, NOT the schema itself. Do NOT include any schema metadata (like [type: ...]) in your output."
    ]).strip()

def _generate_template_string(model: Type[BaseModel]) -> str:
    """
    Generates a template string from a Pydantic model's fields.
    :param model: The Pydantic model to process
    :return: Combined template string of processed fields
    """
    fields: dict[str, FieldInfo] = model.model_fields
    field_prompts = [_process_field(name, info) for name, info in fields.items()]
    return "\n".join(field_prompts)

def generate_prompt_template(model: Type[BaseModel], include_instructions: bool = True) -> str:
    """
    Generates a prompt template from a Pydantic model.
    :param model: The Pydantic model to generate a prompt template for.
    :param include_instructions: Whether to include instructions in the template.
    :return: A string representation of the prompt template.
    """
    template = _generate_template_string(model)
    
    if include_instructions:
        return f"<response_instructions>\n{ADHERE_INSTRUCTIONS_PROMPT(template)}\n</response_instructions>"
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
        response: list[SomeField] = Field(..., description="The response to the query")

    example_response = ExampleResponse(response=[SomeField.A, SomeField.B])

    example = generate_example(example_response)
    print(example)
    example_prompt = generate_prompt_template(ExampleResponse)

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