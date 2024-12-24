import re
import types
from enum import Enum
from types import NoneType
from typing import Any, Type, TypeVar, Union, get_args, get_origin

from pydantic import BaseModel, create_model

ModelType = TypeVar("ModelType", bound=BaseModel)


def camel_to_snake(string: str) -> str:
    """
    Convert a camelCase string to a snake_case string.
    """
    return re.sub("(?!^)([A-Z]+)", r"_\1", string).lower()


def inspect_type_annotation(annotation, name: str = "") -> dict:
    """
    Recursively inspect a type annotation to extract its components.

    :param annotation: A type annotation (can be GenericAlias, Union, or other typing constructs)
    :param name: The name of the type (used for debugging)
    :return: A dictionary of the type structure
    """
    # Mainly for list
    if isinstance(annotation, types.GenericAlias):
        origin: type = get_origin(annotation)
        args: list = get_args(annotation)
        assert all(
            hasattr(arg, "__origin__")
            or (isinstance(arg, type) and issubclass(arg, BaseModel))
            for arg in args
        ), "Lists of primitives not allowed. Wrap the naked field in a pydantic model."

        return {
            "origin": origin,
            "name": name,
            "args": [inspect_type_annotation(arg) for arg in args],
        }

    # Mainly for Union
    if hasattr(annotation, "__origin__"):
        origin: type = get_origin(annotation)
        args: list = get_args(annotation)

        return {
            "origin": origin,
            "args": [inspect_type_annotation(arg, name) for arg in args],
        }

    # For pydantic models
    if isinstance(annotation, type) and issubclass(annotation, BaseModel):
        origin: type = annotation
        name: str = camel_to_snake(annotation.__name__)
        args: list = [
            (value.annotation, field)
            for field, value in annotation.model_fields.items()
        ]

        return {
            "origin": origin,
            "name": name,
            "args": [
                inspect_type_annotation(arg, arg_name) for (arg, arg_name) in args
            ],
        }

    # For primitives
    return {
        "origin": annotation,
        "name": name,
    }


def _clean_xml(xml_content: str) -> str:
    """
    Clean the XML content by:
    1. Removing content before first < and after last >
    2. Closing any unclosed tags
    """

    # Find all opening and closing tags
    opening_tags = re.findall(r"<([^/][^>]*)>", xml_content)
    closing_tags = re.findall(r"</([^>]*)>", xml_content)

    # Add missing closing tags in reverse order
    for tag in reversed(opening_tags):
        if tag not in closing_tags:
            xml_content += f"</{tag}>"

    return xml_content


def _clean_xml_fallback(xml_content: str) -> str:
    """Clean the XML content by removing the leading and trailing tags."""
    xml_content: str = re.sub(r"^[^<]*", "", xml_content)
    xml_content: str = re.sub(r"[^>]*$", "", xml_content)
    return xml_content


def _is_list_type(t: type) -> bool:
    """Check if the type is a list."""
    if t is list:
        return True

    # Check if it's a generic list type
    return t.__origin__ is list if isinstance(t, types.GenericAlias) else False


def _is_pydantic_model(t) -> bool:
    return isinstance(t, type) and issubclass(t, BaseModel)


def _is_field_optional(type_dict: dict, field: str) -> bool:
    args = type_dict.get("args", [])
    for arg in args:
        if "name" not in arg:
            union_args = arg.get("args", [])
            if union_args[0]["name"] != field:
                continue

            return any(union_arg["origin"] is NoneType for union_arg in union_args)

    return False


def _get_possible_opening_tags(type_dict: dict, seen_tags: set[str] = set()) -> dict:
    def field_names_at_level(args: list) -> dict:
        return {
            arg["name"]: arg
            for arg in args
            if "name" in arg and arg["origin"] is not NoneType
        }

    args = type_dict.get("args", [])

    first_level = field_names_at_level(args)
    second_level = {}
    for arg in args:
        if "name" not in arg:
            second_level |= field_names_at_level(arg.get("args", []))

    combined: dict = first_level | second_level
    return {k: v for k, v in combined.items() if k not in seen_tags}


def _get_default_for_primitive(arg: dict) -> Union[str, int, float, bool, None]:
    if arg["origin"] is str:
        return ""
    elif arg["origin"] is int:
        return 0
    elif arg["origin"] is float:
        return 0.0
    elif arg["origin"] is bool:
        return False
    return None


"""
Returns
    - Constructed instance of type, filled with default fields if dict + necessary
    - New position of xml parser
    - IsContent - Whether there is any content or is it all default
"""


def _recurse(
    xml_content: str, open_arg: dict, pos: int
) -> tuple[Union[dict, list], int, bool]:
    possible_next_opening_tags: dict = _get_possible_opening_tags(
        open_arg, {open_arg.get("name", "")}
    )

    attribute_dict: dict = {}
    attribute_list: list = []
    has_child_content: bool = False

    if _is_list_type(open_arg["origin"]):
        attribute_dict[open_arg["name"]] = []

    while pos < len(xml_content):
        open_tag_pattern: str = "|".join(possible_next_opening_tags.keys())
        opening_tag_regex: re.Pattern = re.compile(f"<({open_tag_pattern})>")
        opening_match: Union[re.Match, None] = opening_tag_regex.search(
            xml_content, pos
        )
        if len(possible_next_opening_tags) == 0:
            opening_match = None

        close_tag_regex: re.Pattern = re.compile(f"</({open_arg['name']})>")
        closing_match: Union[re.Match, None] = close_tag_regex.search(xml_content, pos)

        if not opening_match and not closing_match:
            if _is_list_type(open_arg["origin"]):
                if not attribute_list:
                    return [], len(xml_content), False
                return (
                    attribute_list[:-1]
                    + [
                        _fill_with_empty(
                            attribute_list[-1],
                            possible_next_opening_tags[open_arg["name"]],
                        )
                    ],
                    len(xml_content),
                    False,
                )

            if _is_pydantic_model(open_arg["origin"]):
                return (
                    _fill_with_empty(attribute_dict, open_arg),
                    len(xml_content),
                    False,
                )

            # Primitive (final fallback)
            opening_tag_string: str = f"<{open_arg['name']}>"
            opening_tag_idx: int = xml_content.rfind(
                opening_tag_string, 0, len(xml_content)
            )
            content: str = xml_content[opening_tag_idx + len(open_tag_string) :]
            return content, len(xml_content), True

        if opening_match and (
            not closing_match or opening_match.start() < closing_match.start()
        ):
            # Recurse into child tag
            new_open_arg: dict = possible_next_opening_tags[opening_match.group(1)]
            dict_entry, new_pos, is_content = _recurse(
                xml_content, new_open_arg, opening_match.end()
            )
            has_child_content |= is_content

            if _is_list_type(open_arg["origin"]) and is_content:
                attribute_list.append(dict_entry)
            elif dict_entry:
                attribute_dict[new_open_arg["name"]] = dict_entry

            pos = new_pos

        elif closing_match:
            if _is_list_type(open_arg["origin"]):
                if not attribute_list and any(
                    arg.get("args", []) for arg in open_arg["args"]
                ):
                    first_variant = open_arg["args"][0]
                    empty_dict = _fill_with_empty({}, first_variant)
                    return [empty_dict], closing_match.end(), True
                return attribute_list, closing_match.end(), True

            if _is_pydantic_model(open_arg["origin"]):
                if not attribute_dict:
                    return {}, closing_match.end(), True
                return attribute_dict, closing_match.end(), True

            # Primitive or Enum
            opening_tag_string = f"<{open_arg['name']}>"
            opening_tag_idx = xml_content.rfind(opening_tag_string, 0, pos)
            content = xml_content[
                opening_tag_idx + len(opening_tag_string) : closing_match.start()
            ]

            # If this is an Enum, perform special handling to map numeric or string.
            if isinstance(open_arg["origin"], type) and issubclass(
                open_arg["origin"], Enum
            ):
                content = content.strip()
                enum_value = _convert_enum_content(open_arg["origin"], content)
                attribute_dict[open_arg["name"]] = enum_value
                return enum_value, closing_match.end(), True
            else:
                attribute_dict[open_arg["name"]] = content
                return content, closing_match.end(), True

    if _is_list_type(open_arg["origin"]):
        return attribute_list, len(xml_content), has_child_content

    if _is_pydantic_model(open_arg["origin"]):
        return (
            _fill_with_empty(attribute_dict, open_arg),
            len(xml_content),
            has_child_content,
        )

    # Primitive fallback
    return _get_default_for_primitive(open_arg), len(xml_content), False


def _fill_with_empty(parsed_dict: dict, type_dict: dict) -> dict:
    for unseen_tag, arg in _get_possible_opening_tags(
        type_dict, set(parsed_dict.keys())
    ).items():
        # print(arg, unseen_tag)
        if _is_field_optional(type_dict, unseen_tag):
            continue
        if _is_pydantic_model(arg["origin"]):
            parsed_dict[unseen_tag] = _fill_with_empty({}, arg)
        elif _is_list_type(arg["origin"]):
            parsed_dict[unseen_tag] = []
        # Enum Type
        elif isinstance(arg["origin"], type) and issubclass(arg["origin"], Enum):
            parsed_dict[unseen_tag] = next(iter(arg["origin"]))
        # Primitive Type
        elif isinstance(arg["origin"], type):
            parsed_dict[unseen_tag] = _get_default_for_primitive(arg)

    return parsed_dict


def _parse_xml(
    model: Type[ModelType], xml_content: str, fallback: bool = False
) -> ModelType:
    if fallback:
        xml_content: str = _clean_xml_fallback(xml_content)
    else:
        xml_content: str = _clean_xml(xml_content)
    type_dict: dict = inspect_type_annotation(model)

    parsed_dict: dict
    parsed_dict, _, _ = _recurse(xml_content, type_dict, 0)
    if not parsed_dict:
        parsed_dict = {}
    parsed_dict = _fill_with_empty(parsed_dict, type_dict)

    return model(**parsed_dict)


def parse_xml(model: Type[ModelType], xml_content: str) -> ModelType:
    try:
        return _parse_xml(model, xml_content)
    except Exception:
        return _parse_xml(model, xml_content, fallback=True)


def make_partial(model: Type[ModelType], data: dict[str, Any]) -> ModelType:
    """
    Creates a partial version of a Pydantic model where missing fields become None
    and nested models are also made partial.

    :param model: The Pydantic model class to make partial
    :param data: The data dictionary to parse
    :return: A new instance of the model with partial fields
    """
    # Get all fields and their types from the model
    fields = model.model_fields

    # Prepare new field definitions
    new_fields: dict[str, tuple[Any, Any]] = {}

    for field_name, field in fields.items():
        field_type = field.annotation
        field_value = data.get(field_name)

        # Handle lists
        if get_origin(field_type) is list:
            if field_value is None or field_value == []:
                new_fields[field_name] = (list, [])
                continue

            # Get the type inside the list
            inner_type = get_args(field_type)[0]
            if isinstance(inner_type, type) and issubclass(inner_type, BaseModel):
                # Make each item in the list partial
                new_value = [
                    make_partial(inner_type, item) if isinstance(item, dict) else item
                    for item in field_value
                ]
                new_fields[field_name] = (list[inner_type], new_value)
            else:
                new_fields[field_name] = (list[inner_type], field_value)

        # Handle nested models
        elif isinstance(field_type, type) and issubclass(field_type, BaseModel):
            if field_value is None:
                new_fields[field_name] = (field_type, None)
            else:
                new_fields[field_name] = (
                    field_type,
                    make_partial(field_type, field_value),
                )

        # Handle Union types
        elif get_origin(field_type) is Union:
            if field_value is None:
                new_fields[field_name] = (field_type, None)
            else:
                # Try to determine the correct type from the Union
                for possible_type in get_args(field_type):
                    if isinstance(possible_type, type) and issubclass(
                        possible_type, BaseModel
                    ):
                        try:
                            new_fields[field_name] = (
                                field_type,
                                make_partial(possible_type, field_value),
                            )
                            break
                        except:
                            continue
                if field_name not in new_fields:
                    new_fields[field_name] = (field_type, field_value)

        # Handle primitive types
        else:
            new_fields[field_name] = (field_type, field_value)

    # Create a new model with all fields optional
    partial_model = create_model(
        f"Partial{model.__name__}",
        __base__=model,
        **{name: (type_, None) for name, (type_, _) in new_fields.items()},
    )

    # Create an instance with the provided data
    return partial_model(**{k: v for k, (_, v) in new_fields.items() if v is not None})


def _convert_enum_content(enum_type: type[Enum], content: str) -> Enum | str | None:
    """
    Converts XML content to the correct Enum member if possible.
    - If 'content' is purely digits, interpret "1" => the first enum member, "2" => second, etc.
    - Otherwise, pass the raw string along, which might match the enum's string value or raise error.
    """
    content = content.strip()
    if content.isdigit():
        # Attempt 1-based indexing into the enum members
        try:
            idx = int(content) - 1
            members = list(enum_type)
            return members[idx]  # Return the actual Enum member
        except (IndexError, ValueError):
            # If out of range or invalid integer, default to None (pydantic may raise validation error if required)
            return None
    else:
        # Just return the stripped string.
        # If it matches an Enum's string value or name, pydantic can parse it.
        return content
