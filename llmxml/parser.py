import json
import re
from typing import Type, TypeVar, Union
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

    # Handle empty elements
    if not element.text and not len(element):
        return {}

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

    def flatten_dict_values(d: dict) -> list:
        """Helper function to flatten nested dictionaries into a list."""
        flattened = []
        for v in d.values():
            if isinstance(v, dict):
                # If value is a dict, check if it's a wrapper (like 'movie')
                if len(v) == 1 and isinstance(next(iter(v.values())), dict):
                    # It's a wrapper, add the inner content
                    flattened.append(next(iter(v.values())))
                else:
                    # Regular dict, add as is
                    flattened.append(v)
            elif isinstance(v, list):
                flattened.extend(v)
            else:
                flattened.append(v)
        return flattened

    def _process_list_field(field_value: any, item_type: Type) -> list:
        """Process a field value as a list with given item type."""
        # Convert to list if not already
        if isinstance(field_value, dict):
            # Handle nested structures by flattening them
            values = []
            for key, value in field_value.items():
                if isinstance(value, dict):
                    # Add the value directly instead of dict_values
                    values.append(value)
                elif isinstance(value, list):
                    values.extend(value)
                else:
                    values.append({key: value})
            field_value = values
        elif not isinstance(field_value, list):
            field_value = [field_value]

        # Process each item in the list according to its type
        processed_items = []
        for item in field_value:
            if hasattr(item_type, "model_fields"):
                try:
                    # If item is a dict with a single key that matches our type name,
                    # use its value instead
                    if isinstance(item, dict) and len(item) == 1:
                        key = next(iter(item.keys()))
                        if key.lower() == item_type.__name__.lower():
                            item = item[key]
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
        """Process a field value according to its type and annotation."""
        # Handle empty or None values
        if field_value is None or field_value == "":
            # For nested models, return empty dict
            if hasattr(field_info.annotation, "model_fields"):
                return {}
            # For list types, return empty list
            elif (
                hasattr(field_info.annotation, "__origin__")
                and field_info.annotation.__origin__ is list
            ):
                return []
            return None

        # Handle text content in dictionary first
        if isinstance(field_value, dict) and (
            "_text" in field_value or "_tail" in field_value
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

        # Handle lists
        if (
            getattr(field_info.annotation, "__origin__", None) is list
            and len(field_info.annotation.__args__) > 0
        ):
            return _process_list_field(field_value, field_info.annotation.__args__[0])

        # Handle case where value is a dict but should be a list
        print(field_info.annotation)
        print(type(field_info.annotation))
        print(hasattr(field_info.annotation, "__origin__"))
        if hasattr(field_info.annotation, "__origin__"):
            print(field_info.annotation.__origin__)
            if field_info.annotation.__origin__ is Union:
                print(f"Union types: {field_info.annotation.__args__}")
                # Check if any of the Union types is a List
                for arg in field_info.annotation.__args__:
                    if hasattr(arg, "__origin__"):
                        print("origin:", arg.__origin__)
                    if hasattr(arg, "__origin__") and arg.__origin__ is list:
                        # If field_value is a dict, wrap it in a list
                        print("LIST!")
                        if isinstance(field_value, dict):
                            return [field_value]

        # Handle nested models
        if hasattr(field_info.annotation, "model_fields"):
            if isinstance(field_value, str):
                return field_value

            # Process nested fields recursively
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
                else:
                    # Initialize missing fields
                    if (
                        hasattr(nested_field_info.annotation, "__origin__")
                        and nested_field_info.annotation.__origin__ is list
                    ):
                        processed_nested[nested_field_name] = []
                    elif hasattr(nested_field_info.annotation, "model_fields"):
                        processed_nested[nested_field_name] = {}

            try:
                return field_info.annotation(**processed_nested)
            except Exception:
                # If validation fails, try creating a partial model
                partial_model = _create_partial_model(
                    field_info.annotation, processed_nested
                )
                print(processed_nested)
                return partial_model(**processed_nested)

        return field_value

    # Process each field in the model
    for field_name, field_info in model_fields.items():
        if field_name in data:
            processed[field_name] = _process_field_value(
                data[field_name], field_info, field_name
            )
        else:
            # Initialize missing list fields with empty lists
            if (
                hasattr(field_info.annotation, "__origin__")
                and field_info.annotation.__origin__ is list
            ):
                processed[field_name] = []

    return processed


def _extract_partial_content(xml_str: str) -> dict:
    """Extract valid content from partial or malformed XML."""
    result: dict = {}

    # Find all top-level tags and their content
    tag_pattern: re.Pattern = re.compile(
        r"<(\w+)(?:>([^<]*(?:(?!</\1>)<[^<]*)*?)(?:</\1>|$)|[^>]*$)", re.DOTALL
    )
    matches: re.Iterator = tag_pattern.finditer(xml_str)

    for match in matches:
        tag_name: str = match.group(1)
        # Content might be None for incomplete tags
        content: str = match.group(2) if match.group(2) is not None else ""
        content = content.strip()

        # Skip incomplete tags or empty content
        if not tag_name or not content:
            continue

        # For nested content, try to parse it recursively
        if re.search(r"<\w+>", content):
            nested_content: dict = _extract_partial_content(content)
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
            # Handle non-nested content
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
    # Check if model is already a partial model
    if model.__name__.startswith("Partial"):
        return model

    model_name: str = model.__name__
    partial_name: str = f"Partial{model_name}"

    # Make all fields optional for partial model
    fields: dict = {}
    for field, field_info in model.model_fields.items():
        # Get default empty value based on type
        if field_info.annotation is str:
            default = ""
        elif field_info.annotation is list or (
            hasattr(field_info.annotation, "__origin__")
            and field_info.annotation.__origin__ is list
        ):
            default = []
        elif field_info.annotation is dict:
            default = {}
        elif field_info.annotation is int:
            default = 0
        elif field_info.annotation is float:
            default = 0.0
        elif field_info.annotation is bool:
            default = False
        elif hasattr(field_info.annotation, "model_fields"):  # Handle nested models
            nested_partial = _create_partial_model(field_info.annotation, {})
            default = nested_partial()
            field_info.annotation = nested_partial
        else:
            default = None

        fields[field] = (field_info.annotation | None, default)

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
        data = _extract_partial_content(xml_str)

    # Process the data according to the model's fields
    processed_data: dict = _process_dict_for_model(data, model)

    # Create and return the model instance
    if not processed_data:
        return _create_partial_model(model, {})()

    try:
        return model(**processed_data)
    except Exception:
        # Create empty processed data with proper nested structure
        empty_processed_data: dict = {}
        for field_name, field_info in model.model_fields.items():
            if hasattr(field_info.annotation, "model_fields"):
                # For nested models, create a partial instance
                nested_partial = _create_partial_model(field_info.annotation, {})
                empty_processed_data[field_name] = nested_partial()
            elif (
                hasattr(field_info.annotation, "__origin__")
                and field_info.annotation.__origin__ is list
            ):
                empty_processed_data[field_name] = []
            else:
                empty_processed_data[field_name] = None

        # Create partial model with proper field types
        partial_model = _create_partial_model(model, empty_processed_data)
        instance = partial_model()

        # Manually set each field to ensure proper typing
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
