import json
import re
from types import UnionType
from typing import Any, Type, TypeVar, Union
from xml.etree import ElementTree as ET

from partialjson.json_parser import JSONParser
from pydantic import BaseModel, Field, GetJsonSchemaHandler, create_model
from pydantic_core import CoreSchema, core_schema

parser = JSONParser(strict=False)
parser.on_extra_token = None

T = TypeVar("T", bound=BaseModel)


# Add CodeContent type definition
class XMLSafeString(str):
    """Wraps contents of this param in CDATA so it gets preserved. Used for any content that might contain brackets/xml-like tags that might break the parser.
    Usage:
    class MyModel(BaseModel):
        content: XMLSafeString = Field(..., description="Some content that might contain jsx/html/xml tags")
    """

    @classmethod
    def __get_pydantic_core_schema__(
        cls, source_type: Any, handler: GetJsonSchemaHandler
    ) -> CoreSchema:
        return core_schema.json_or_python_schema(
            json_schema=core_schema.str_schema(),
            python_schema=core_schema.union_schema(
                [
                    core_schema.str_schema(),
                    core_schema.no_info_plain_validator_function(cls.validate),
                ]
            ),
            serialization=core_schema.plain_serializer_function_ser_schema(
                lambda x: x, return_schema=core_schema.str_schema()
            ),
        )

    @classmethod
    def validate(cls, v: Any) -> str:
        return str(v)


def _clean_xml(xml_content: str) -> str:
    """Clean and complete partial XML."""
    xml_content = re.sub(r"^[^<]*", "", xml_content)
    xml_content = re.sub(r"[^>]*$", "", xml_content)

    def wrap_in_cdata(text: str) -> str:
        if re.search(r"[<>&]", text):
            if text.startswith("<![CDATA[") and text.endswith("]]>"):
                return text
            text = text.replace("]]>", "]]]]><![CDATA[>")
            return f"<![CDATA[{text}]]>"
        return text

    def is_code_content(text: str) -> bool:
        code_patterns: list[str] = [
            r"import\s+[{\w]",
            r"class\s+\w+",
            r"function\s+\w+",
            r"const\s+\w+",
            r"let\s+\w+",
            r"var\s+\w+",
            r"return\s+",
            r"=>\s*{",
            r"{\s*[\w'\"]+:",
            r"<[/\w]+>",  # HTML/JSX tags
            r"[{<&]",  # JSON/XML-like content
            r"&[a-zA-Z]+;",  # HTML entities
        ]
        return any(re.search(pattern, text, re.MULTILINE) for pattern in code_patterns)

    def process_code_content(text: str) -> str:
        return wrap_in_cdata(text) if is_code_content(text) else text

    def process_tag_recursively(match: re.Match) -> str:
        tag_name: str = match[1]
        content: str = match[2]

        code_fields: set[str] = {"file_contents", "new_file_contents"}
        if tag_name in code_fields:
            return f"<{tag_name}>{process_code_content(content)}</{tag_name}>"

        if re.search(r"<\w+>", content):
            processed_content = re.sub(
                r"<(\w+)>(.*?)</\1>", process_tag_recursively, content, flags=re.DOTALL
            )
            return f"<{tag_name}>{processed_content}</{tag_name}>"

        return f"<{tag_name}>{process_code_content(content)}</{tag_name}>"

    xml_content = re.sub(
        r"<(\w+)>(.*?)</\1>", process_tag_recursively, xml_content, flags=re.DOTALL
    )

    if not xml_content.strip().startswith("<root>"):
        xml_content = f"<root>{xml_content}</root>"

    return xml_content


def _xml_to_dict(element: ET.Element) -> any:
    result: dict[str, any] | list[any] = {}

    if not element.text and not len(element):
        return {}

    if element.text and element.text.strip():
        text: str = element.text.strip()
        if not len(element):
            return text
        result["_text"] = text

    child_tags: list[str] = [child.tag for child in element]
    tag_counts: dict[str, int] = {tag: child_tags.count(tag) for tag in set(child_tags)}

    for child in element:
        key: str = child.tag
        value: any = _xml_to_dict(child)

        if tag_counts[key] > 1:
            if key not in result:
                result[key] = []
            result[key].append(value)
        else:
            result[key] = value

    return result


def _process_dict_for_model(data: dict, model: Type[BaseModel]) -> dict:
    """Match dictionary to model field types."""
    processed: dict = {}
    model_fields = model.model_fields

    def _reconstruct_text(value: dict) -> str:
        """Reconstruct text from dictionary parts."""
        if not isinstance(value, dict):
            return str(value)

        parts: list[str] = []
        if "_text" in value:
            parts.append(value["_text"])

        for key, content in value.items():
            if key not in ["_text", "_tail"]:
                if isinstance(content, dict):
                    parts.append(_reconstruct_text(content))
                elif isinstance(content, list):
                    parts.extend(_reconstruct_text(item) for item in content)
                else:
                    parts.append(str(content))

        if "_tail" in value:
            parts.append(value["_tail"])

        return "".join(parts)

    def flatten_dict_values(d: Union[dict, list]) -> list:
        """Flatten nested dictionaries into a list."""
        flattened = []
        if isinstance(d, dict):
            values = d.values()
        else:
            values = d

        for v in values:
            if isinstance(v, dict):
                if len(v) == 1 and isinstance(next(iter(v.values())), dict):
                    flattened.append(next(iter(v.values())))
                else:
                    flattened.append(v)
            elif isinstance(v, list):
                flattened.extend(v)
            else:
                flattened.append(v)
        return flattened

    def _process_list_field(field_value: any, item_type: Type) -> list:
        """Process field value as a list with given item type."""
        if isinstance(field_value, dict):
            values = []
            if len(field_value) == 1 and isinstance(
                next(iter(field_value.values())), list
            ):
                values = next(iter(field_value.values()))
            else:
                for key, value in field_value.items():
                    if isinstance(value, list):
                        values.extend(value)
                    elif isinstance(value, dict):
                        values.append(value)
                    else:
                        values.append({key: value})
            field_value = values
        elif not isinstance(field_value, list):
            field_value = [field_value]

        processed_items = []
        for item in field_value:
            if hasattr(item_type, "model_fields"):
                try:
                    processed_item = _process_dict_for_model(item, item_type)
                    model_instance = item_type(**processed_item)
                    processed_items.append(model_instance)
                except Exception:
                    continue
            else:
                processed_items.append(item)
        return processed_items

    def _process_field_value(
        field_value: any, field_info: any, field_name: str = None
    ) -> any:
        """Process field value according to type and annotation."""

        if isinstance(field_value, dict) and len(field_value) == 0:
            if (
                hasattr(field_info.annotation, "__origin__")
                and field_info.annotation.__origin__ is Union
            ):
                if type(None) in field_info.annotation.__args__:
                    return None
            elif hasattr(field_info.annotation, "__args__"):
                if type(None) in field_info.annotation.__args__:
                    return None

        if field_value is None or field_value == "":
            if hasattr(field_info.annotation, "model_fields"):
                return {}
            elif (
                hasattr(field_info.annotation, "__origin__")
                and field_info.annotation.__origin__ is list
            ):
                return []
            return None

        if isinstance(field_value, dict) and (
            "_text" in field_value or "_tail" in field_value
        ):
            return _reconstruct_text(field_value)

        if hasattr(field_info.annotation, "__args__"):
            if (
                hasattr(field_info.annotation, "__origin__")
                and field_info.annotation.__origin__ is dict
            ) or any(
                hasattr(arg, "__origin__") and arg.__origin__ is dict
                for arg in field_info.annotation.__args__
            ):
                try:
                    if isinstance(field_value, str):
                        return json.loads(field_value)
                    return field_value
                except json.JSONDecodeError:
                    return parser.parse(field_value)

        if (
            getattr(field_info.annotation, "__origin__", None) is list
            and len(field_info.annotation.__args__) > 0
        ):
            if isinstance(field_value, dict) and len(field_value) == 1:
                key = next(iter(field_value.keys()))
                if isinstance(field_value[key], list):
                    field_value = field_value[key]
            processed_list = _process_list_field(
                field_value, field_info.annotation.__args__[0]
            )
            return [
                item.model_dump() if hasattr(item, "model_dump") else item
                for item in processed_list
            ]

        if hasattr(field_info.annotation, "__origin__"):
            if field_info.annotation.__origin__ is Union:
                for arg in field_info.annotation.__args__:
                    if hasattr(arg, "__origin__") and arg.__origin__ is list:
                        if isinstance(field_value, dict):
                            return [field_value]

        if hasattr(field_info.annotation, "model_fields"):
            if isinstance(field_value, str):
                return field_value

            processed_nested: dict = {}
            for (
                nested_field_name,
                nested_field_info,
            ) in field_info.annotation.model_fields.items():
                if nested_field_name in field_value:
                    nested_value = field_value[nested_field_name]
                    processed_nested[nested_field_name] = _process_field_value(
                        nested_value, nested_field_info, nested_field_name
                    )

                    if type(nested_field_info.annotation) is UnionType:
                        list_args = [
                            arg
                            for arg in nested_field_info.annotation.__args__
                            if hasattr(arg, "__origin__") and arg.__origin__ is list
                        ]
                        if list_args:
                            processed_nested[nested_field_name] = flatten_dict_values(
                                processed_nested[nested_field_name]
                            )
                else:
                    if (
                        hasattr(nested_field_info.annotation, "__origin__")
                        and nested_field_info.annotation.__origin__ is list
                    ):
                        processed_nested[nested_field_name] = []
                    elif hasattr(nested_field_info.annotation, "model_fields"):
                        processed_nested[nested_field_name] = {}

            try:
                model = field_info.annotation(**processed_nested)
                return model.model_dump()
            except Exception:
                partial_model = _create_partial_model(
                    field_info.annotation, processed_nested
                )
                model = partial_model(**processed_nested)
                return model.model_dump()

        return field_value

    for field_name, field_info in model_fields.items():
        if field_name in data:
            processed[field_name] = _process_field_value(
                data[field_name], field_info, field_name
            )
        else:
            if (
                hasattr(field_info.annotation, "__origin__")
                and field_info.annotation.__origin__ is list
            ):
                processed[field_name] = []

    return processed


def _extract_partial_content(
    xml_str: str, expected_type: Type[BaseModel | str]
) -> dict:
    """Extract valid content from partial or malformed XML."""
    result: dict = {}

    tag_pattern: re.Pattern = re.compile(
        r"<(\w+)(?:>([^<]*(?:(?!</\1>)<[^<]*)*?)(?:</\1>|$)|[^>]*$)", re.DOTALL
    )
    matches: re.Iterator = tag_pattern.finditer(xml_str)

    def get_field_type(tag: str) -> Type[BaseModel | str]:
        """Get expected type for a field based on model fields."""
        if hasattr(expected_type, "model_fields") and tag in expected_type.model_fields:
            field_info = expected_type.model_fields[tag]
            if hasattr(field_info.annotation, "model_fields"):
                return field_info.annotation
            if (
                hasattr(field_info.annotation, "__origin__")
                and field_info.annotation.__origin__ is list
                and hasattr(field_info.annotation, "__args__")
                and hasattr(field_info.annotation.__args__[0], "model_fields")
            ):
                return field_info.annotation.__args__[0]
        return str

    for match in matches:
        tag_name: str = match.group(1)
        content: str = match.group(2) if match.group(2) is not None else ""
        content = content.strip()

        if not tag_name or not content:
            continue

        field_type = get_field_type(tag_name)

        if re.search(r"<\w+>", content):
            nested_content: dict = _extract_partial_content(content, field_type)
            if nested_content:
                if tag_name in result:
                    if not isinstance(result[tag_name], list):
                        result[tag_name] = [result[tag_name]]
                    if isinstance(nested_content, dict):
                        result[tag_name].append(nested_content)
                    else:
                        result[tag_name].extend(
                            nested_content
                            if isinstance(nested_content, list)
                            else [nested_content]
                        )
                else:
                    result[tag_name] = nested_content
        else:
            content = content.strip()
            if content.startswith("<"):
                continue

            if tag_name in result:
                if not isinstance(result[tag_name], list):
                    result[tag_name] = [result[tag_name]]
                result[tag_name].append(content)
            else:
                result[tag_name] = content

    return result


def _create_partial_model(model: Type[BaseModel], data: dict) -> Type[BaseModel]:
    """Create a partial model with all fields optional."""
    if model.__name__.startswith("Partial"):
        return model

    model_name: str = model.__name__
    partial_name: str = f"Partial{model_name}"

    fields: dict = {}
    for field, field_info in model.model_fields.items():
        print(f"{field=} {field_info.annotation=}")
        if field_info.annotation is str:
            default = ""
        elif field_info.annotation is list or (
            hasattr(field_info.annotation, "__origin__")
            and field_info.annotation.__origin__ is list
        ):
            default = []
            if hasattr(field_info.annotation, "__args__"):
                item_type = field_info.annotation.__args__[0]
                if hasattr(item_type, "model_fields"):
                    nested_partial = _create_partial_model(item_type, {})
                    field_info.annotation = list[nested_partial]
        elif field_info.annotation is dict:
            default = {}
        elif field_info.annotation is int:
            default = 0
        elif field_info.annotation is float:
            default = 0.0
        elif field_info.annotation is bool:
            default = False
        elif hasattr(field_info.annotation, "model_fields"):
            nested_partial = _create_partial_model(field_info.annotation, {})
            default = nested_partial()
            field_info.annotation = nested_partial
        else:
            default = None

        fields[field] = (field_info.annotation | None, default)

    return create_model(partial_name, __base__=BaseModel, **fields)


def parse_xml(model: Type[T], xml_str: str) -> T:
    if not xml_str.strip():
        return _create_partial_model(model, {})()

    cleaned_xml: str = _clean_xml(xml_str)

    try:
        root: ET.Element = ET.fromstring(cleaned_xml)
        data: dict = _xml_to_dict(root)
    except ET.ParseError:
        data = _extract_partial_content(xml_str, model)

    processed_data: dict = _process_dict_for_model(data, model)

    if not processed_data:
        return _create_partial_model(model, {})()

    try:
        return model(**processed_data)
    except Exception as _e:
        empty_processed_data: dict = {}
        for field_name, field_info in model.model_fields.items():
            if hasattr(field_info.annotation, "model_fields"):
                nested_partial = _create_partial_model(field_info.annotation, {})
                empty_processed_data[field_name] = nested_partial()
            elif (
                hasattr(field_info.annotation, "__origin__")
                and field_info.annotation.__origin__ is list
            ):
                empty_processed_data[field_name] = []
            else:
                empty_processed_data[field_name] = None

        partial_model = _create_partial_model(model, empty_processed_data)
        instance = partial_model()

        for field_name, value in empty_processed_data.items():
            setattr(instance, field_name, value)
        return instance


if __name__ == "__main__":
    from pathlib import Path
    from typing import Literal

    import black
    from pydantic import Field
    from rich.console import Console
    from rich.live import Live

    def read_test_file(file_name: str) -> str:
        file_parent = Path(__file__).parent
        with open(file_parent / "tests" / "test_files" / file_name, "r") as file:
            return file.read()

    action_file: str = read_test_file("action.xml")
    console: Console = Console()

    class NewFileAction(BaseModel):
        action_type: Literal["new_file"]
        new_file_path: str = Field(..., description="The path of the new file")
        file_contents: str = Field(..., description="The contents of the new file")

    class RunCommandAction(BaseModel):
        action_type: Literal["run_command"]
        command: str = Field(..., description="The command to run")

    class ActionResponse(BaseModel):
        thinking: str = Field(..., description="The thinking of the action")
        actions: list[Union[NewFileAction, RunCommandAction]] = Field(
            ..., description="The actions to take"
        )

    partial_content: str = ""
    last_valid_result: ActionResponse | None = None

    with Live(console=console, refresh_per_second=120) as live:
        for char in action_file:
            partial_content += char
            result = parse_xml(ActionResponse, partial_content)
            pretty_result = black.format_str(
                repr(result), mode=black.FileMode(line_length=40)
            )
            live.update(pretty_result)
