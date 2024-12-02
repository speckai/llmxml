import json
import re
from typing import Type, TypeVar, Union, get_type_hints
from xml.etree import ElementTree as ET

from pydantic import BaseModel, create_model

T = TypeVar("T", bound=BaseModel)


def _clean_xml(xml_content: str) -> str:
    """Clean and complete partial XML if needed."""
    # Strip content before first < and after last >
    xml_content = re.sub(r"^[^<]*", "", xml_content)
    xml_content = re.sub(r"[^>]*$", "", xml_content)

    def wrap_in_cdata(text: str) -> str:
        if re.search(r"[<>]", text):
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

    # Process all tags recursively
    xml_content = re.sub(
        r"<(\w+)>(.*?)</\1>", process_tag_recursively, xml_content, flags=re.DOTALL
    )

    # Wrap multiple root elements in a single root if needed
    if not xml_content.strip().startswith("<root>"):
        xml_content = f"<root>{xml_content}</root>"

    return xml_content


def _xml_to_dict(element: ET.Element) -> any:
    result: dict[str, any] = {}

    if element.text and element.text.strip():
        text: str = element.text.strip()
        if not len(element):
            return text
        result["_text"] = text

    child_tags: list[str] = [child.tag for child in element]
    tag_counts: dict[str, int] = {tag: child_tags.count(tag) for tag in set(child_tags)}

    # Handle children
    for child in element:
        key: str = child.tag
        value: any = _xml_to_dict(child)

        # If this tag appears multiple times, make it a list
        if tag_counts[key] > 1:
            if key not in result:
                result[key] = []
            result[key].append(value)
        else:
            result[key] = value

    # If this is the root element, flatten it
    if element.tag == "root":
        return {k: v for k, v in result.items() if not k.startswith("_")}

    # If we only have text content, return it directly
    return result["_text"] if len(result) == 1 and "_text" in result else result


def _process_dict_for_model(data: dict, model: Type[BaseModel]) -> dict:
    """Process dictionary to match model field types."""
    processed: dict = {}
    model_fields = model.model_fields

    def _reconstruct_text(value: dict) -> str:
        """Recursively reconstruct text content from a dictionary of text parts."""
        if not isinstance(value, dict):
            return str(value)

        parts: list[str] = []
        if "_text" in value:
            parts.append(value["_text"])

        # Handle nested divs and other elements
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

    def _process_field_value(
        field_value: any, field_info: any, field_name: str = None
    ) -> any:
        """Process a field value according to its type and annotation."""
        if field_value is None:
            return None

        # Handle lists
        if (
            getattr(field_info.annotation, "__origin__", None) is list
            and len(field_info.annotation.__args__) > 0
        ):
            item_type = field_info.annotation.__args__[0]

            # Convert to list if not already
            if isinstance(field_value, dict):
                # Extract values from dict
                values: list[any] = []
                for v in field_value.values():
                    if isinstance(v, list):
                        values.extend(v)
                    else:
                        values.append(v)
                field_value = values
            elif not isinstance(field_value, list):
                field_value = [field_value]

            # Handle Union type in list
            if getattr(item_type, "__origin__", None) == Union:
                processed_items: list[any] = []
                for item in field_value:
                    # Try each possible type in the Union
                    for possible_type in item_type.__args__:
                        try:
                            if hasattr(possible_type, "model_fields"):
                                # Check if we have all required fields
                                has_all_fields: bool = True
                                for (
                                    field_name,
                                    field_info,
                                ) in possible_type.model_fields.items():
                                    if (
                                        field_info.is_required()
                                        and field_name not in item
                                    ):
                                        has_all_fields = False
                                        break

                                if has_all_fields:
                                    processed: dict = _process_dict_for_model(
                                        item, possible_type
                                    )
                                    model_instance = possible_type(**processed)
                                    processed_items.append(model_instance)
                                    break
                        except Exception:
                            continue
                return processed_items
            # Handle regular model type in list
            elif hasattr(item_type, "model_fields"):
                processed_items: list[any] = []
                for item in field_value:
                    try:
                        processed: dict = _process_dict_for_model(item, item_type)
                        model_instance = item_type(**processed)
                        processed_items.append(model_instance)
                    except Exception:
                        continue
                return processed_items
            else:
                return field_value

        # Handle single Union type
        if (
            hasattr(field_info.annotation, "__origin__")
            and field_info.annotation.__origin__ == Union
        ):
            # Try each possible type in the Union
            for possible_type in field_info.annotation.__args__:
                try:
                    if hasattr(possible_type, "model_fields"):
                        processed: dict = _process_dict_for_model(
                            field_value, possible_type
                        )
                        return possible_type(**processed)
                    elif possible_type is str and isinstance(field_value, (str, dict)):
                        return (
                            _reconstruct_text(field_value)
                            if isinstance(field_value, dict)
                            else field_value
                        )
                except Exception:
                    continue
            return None

        # Handle nested models
        if hasattr(field_info.annotation, "model_fields"):
            if isinstance(field_value, str):
                return field_value
            processed: dict = _process_dict_for_model(
                field_value, field_info.annotation
            )
            return field_info.annotation(**processed)

        # Handle text content in dictionary
        if isinstance(field_value, dict) and (
            "_text" in field_value or "_tail" in field_value or "div" in field_value
        ):
            return _reconstruct_text(field_value)

        # Handle JSON strings in data fields
        if (
            field_name == "data"
            and isinstance(field_value, str)
            and field_value.strip().startswith("{")
        ):
            try:
                return json.loads(field_value)
            except json.JSONDecodeError:
                return field_value

        return field_value

    for field_name, field_info in model_fields.items():
        if field_name in data:
            processed[field_name] = _process_field_value(
                data[field_name], field_info, field_name
            )

    return processed


def _extract_partial_content(xml_str: str) -> dict:
    """Extract valid content from partial or malformed XML."""
    result: dict = {}

    # Find all top-level tags and their content
    tag_pattern: re.Pattern = re.compile(r"<(\w+)>(.*?)(?:</\1>|$)", re.DOTALL)
    matches: re.Iterator = tag_pattern.finditer(xml_str)

    for match in matches:
        tag_name: str = match.group(1)
        content: str = match.group(2).strip()

        # For nested content, try to parse it recursively
        if re.search(r"<\w+>", content):
            nested_content: dict = _extract_partial_content(content)
            if nested_content:
                # If this tag appears multiple times, convert to list
                if tag_name in result:
                    if not isinstance(result[tag_name], list):
                        result[tag_name] = [result[tag_name]]
                    result[tag_name].append(nested_content)
                else:
                    # Check if the nested content itself contains a list
                    result[tag_name] = (
                        next(iter(nested_content.values()))
                        if len(nested_content) == 1
                        and isinstance(next(iter(nested_content.values())), list)
                        else nested_content
                    )
        elif tag_name in result:
            if not isinstance(result[tag_name], list):
                result[tag_name] = [result[tag_name]]
            result[tag_name].append(content)
        else:
            result[tag_name] = content

    return result


def _create_partial_model(model: Type[BaseModel], data: dict) -> BaseModel:
    """Create a partial model with all fields optional."""
    model_name: str = model.__name__
    partial_name: str = f"Partial{model_name}"

    # Make all fields optional for partial model
    fields: dict = {}
    for field, type_ in get_type_hints(model).items():
        # Get default empty value based on type
        if type_ is str:
            default = ""
        elif type_ is list or (
            hasattr(type_, "__origin__") and type_.__origin__ is list
        ):
            default = []
        elif type_ is dict:
            default = {}
        elif type_ is int:
            default = 0
        elif type_ is float:
            default = 0.0
        elif type_ is bool:
            default = False
        else:
            default = None

        if type_ is any:
            fields[field] = (type_, default)
        elif hasattr(type_, "__origin__"):
            if type_.__origin__ is list:
                # For list types, handle the element type
                element_type = type_.__args__[0]
                if (
                    hasattr(element_type, "__origin__")
                    and element_type.__origin__ == Union
                ):
                    # For Union types in lists, create a new Union with all types optional
                    union_types = element_type.__args__
                    partial_types: list = []
                    for union_type in union_types:
                        if hasattr(union_type, "model_fields"):
                            partial_union_type = _create_partial_model(union_type, {})
                            partial_types.append(partial_union_type)
                        else:
                            partial_types.append(union_type)
                    fields[field] = (list[Union[tuple(partial_types)]], default)
                else:
                    fields[field] = (list[element_type], default)
            elif type_.__origin__ == Union:
                # For direct Union types, create a new Union with all types optional
                union_types = type_.__args__
                partial_types: list = []
                for union_type in union_types:
                    if hasattr(union_type, "model_fields"):
                        partial_union_type = _create_partial_model(union_type, {})
                        partial_types.append(partial_union_type)
                    else:
                        partial_types.append(union_type)
                fields[field] = (Union[tuple(partial_types)], default)
        else:
            fields[field] = (type_ | None, default)

    return create_model(partial_name, __base__=BaseModel, **fields)


def parse_xml(model: Type[T], xml_str: str) -> T:
    """Parse XML string into a Pydantic model.

    Takes an XML string and converts it into a Pydantic model instance. The XML structure
    should match the model's field definitions. Handles both complete and partial XML content.

    Args:
        model: The Pydantic model class to parse into
        xml_str: The XML string to parse

    Returns:
        An instance of the provided model populated with the XML data

    Raises:
        ET.ParseError: If the XML is malformed and cannot be parsed
    """
    if not xml_str.strip():
        return _create_partial_model(model, {})()

    # Try to parse as complete XML first
    cleaned_xml: str = _clean_xml(xml_str)
    try:
        root: ET.Element = ET.fromstring(cleaned_xml)
        data: dict = _xml_to_dict(root)
    except ET.ParseError:
        # If that fails, try to extract partial content
        # print(f"Failed to parse XML: {str(e)}")
        # TODO: Handle this better
        data = _extract_partial_content(xml_str)

    # Process the data according to the model's fields
    processed_data: dict = _process_dict_for_model(data, model)

    # Create and return the model instance
    if not processed_data:
        return _create_partial_model(model, {})()

    try:
        return model(**processed_data)
    except Exception:
        # If validation fails, return a partial model
        partial_model = _create_partial_model(model, processed_data)
        return partial_model(**processed_data)


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