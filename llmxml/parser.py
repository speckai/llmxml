import re
import types
from enum import Enum
from types import NoneType
from typing import Any, Type, TypeVar, Union, get_args, get_origin

from pydantic import BaseModel, create_model

ModelType = TypeVar("ModelType", bound=BaseModel)

"""
XML Parsing Flow:
1. parse_xml(xml, model) -> Entry point
    - Inspects model structure with _inspect_type_annotation()
    - Calls _parse_xml() with fallback option if initial parse fails

2. _parse_xml(xml, model, type_dict) -> Handles XML cleaning and parsing
    - Cleans XML with _clean_xml() or _clean_xml_fallback()
    - Initiates recursive parsing with _recurse()
    - Fills missing fields with _fill_with_empty()

3. _recurse(xml, open_arg, pos) -> Core parsing logic
    - Processes XML content recursively
    - Handles lists, models, and primitive types
    - Uses _handle_primitive_content(), _handle_no_matches(), _handle_closing_tag()
"""


def _camel_to_snake(string: str) -> str:
    """
    Convert a camelCase string to a snake_case string.
    :param string: The string to convert
    :return: The converted string
    """
    return re.sub("(?!^)([A-Z]+)", r"_\1", string).lower()


def _inspect_type_annotation(annotation, name: str = "") -> dict:
    """
    Recursively inspect a type annotation to extract its components.

    :param annotation: A type annotation (can be GenericAlias, Union, or other typing constructs)
    :param name: The name of the type (used for debugging)
    :return: A dictionary of the type structure
    """
    # Handle list or other generics
    if isinstance(annotation, types.GenericAlias):
        origin: type = get_origin(annotation)
        args: list = get_args(annotation)

        if origin is list and len(args) == 1:
            inner_type = args[0]
            if isinstance(inner_type, type) and issubclass(inner_type, BaseModel):
                return {
                    "origin": origin,
                    "name": name,
                    "args": [_inspect_type_annotation(inner_type)],
                }

            if inner_type in (str, int, float):
                return {
                    "origin": origin,
                    "name": name,
                    "args": [
                        {
                            "origin": inner_type,
                            "name": inner_type.__name__,  # 'str', 'int', 'float'
                        }
                    ],
                }

        return {
            "origin": origin,
            "name": name,
            "args": [_inspect_type_annotation(arg) for arg in args],
        }

    if hasattr(annotation, "__origin__"):
        origin: type = get_origin(annotation)
        args: list = get_args(annotation)
        return {
            "origin": origin,
            "args": [_inspect_type_annotation(arg, name) for arg in args],
        }

    if isinstance(annotation, type) and issubclass(annotation, BaseModel):
        origin: type = annotation
        name: str = _camel_to_snake(annotation.__name__)
        args: list = [
            (value.annotation, field)
            for field, value in annotation.model_fields.items()
        ]
        return {
            "origin": origin,
            "name": name,
            "args": [
                _inspect_type_annotation(arg, arg_name) for (arg, arg_name) in args
            ],
        }

    # Otherwise, assume it's a primitive/enumeration
    return {
        "origin": annotation,
        "name": name,
    }


def _get_all_possible_tags(type_dict: dict) -> set[str]:
    """
    Recursively get all possible tag names from a type dictionary.
    :param type_dict: The type dictionary to extract tags from
    :return: A set of all possible tag names
    """
    tags: set[str] = set()
    if "name" in type_dict and type_dict["name"]:
        tags.add(type_dict["name"])

    for arg in type_dict.get("args", []):
        tags.update(_get_all_possible_tags(arg))

    return tags


def _clean_xml(xml_content: str) -> str:
    """
    Clean the XML content by removing the leading and trailing tags.
    :param xml_content: The XML content to clean
    :return: The cleaned XML content
    """
    xml_content: str = re.sub(r"^[^<]*", "", xml_content)
    xml_content: str = re.sub(r"[^>]*$", "", xml_content)
    return xml_content


def _is_list_type(t: type) -> bool:
    """
    Check if the type is a list.
    :param t: The type to check
    :return: True if the type is a list, False otherwise
    """
    if t is list:
        return True

    return t.__origin__ is list if isinstance(t, types.GenericAlias) else False


def _is_pydantic_model(t) -> bool:
    """
    Check if the type is a pydantic model.
    :param t: The type to check
    :return: True if the type is a pydantic model, False otherwise
    """
    return isinstance(t, type) and issubclass(t, BaseModel)


def _is_field_optional(type_dict: dict, field: str) -> bool:
    """
    Check if the field is optional.
    :param type_dict: The type dictionary
    :param field: The field to check
    :return: True if the field is optional, False otherwise
    """
    args: list = type_dict.get("args", [])
    for arg in args:
        if "name" not in arg:
            union_args: list = arg.get("args", [])
            if union_args[0]["name"] != field:
                continue

            return any(union_arg["origin"] is NoneType for union_arg in union_args)

    return False


def _get_possible_opening_tags(type_dict: dict, seen_tags: set[str] = set()) -> dict:
    """
    Get the possible opening tags for a given type dictionary.
    :param type_dict: The type dictionary
    :param seen_tags: The set of tags already seen
    :return: The possible opening tags
    """

    def field_names_at_level(args: list) -> dict:
        return {
            arg["name"]: arg
            for arg in args
            if "name" in arg and arg["origin"] is not NoneType
        }

    args: list = type_dict.get("args", [])

    first_level: dict = field_names_at_level(args)
    second_level: dict = {}
    for arg in args:
        if "name" not in arg:
            second_level |= field_names_at_level(arg.get("args", []))

    combined: dict = first_level | second_level
    return {k: v for k, v in combined.items() if k not in seen_tags}


def _get_default_for_primitive(arg: dict) -> Union[str, int, float, bool, None]:
    """
    Get the default value for a primitive type.
    :param arg: The argument dictionary
    :return: The default value
    """
    if arg["origin"] is str:
        return ""
    elif arg["origin"] is int:
        return 0
    elif arg["origin"] is float:
        return 0.0
    elif arg["origin"] is bool:
        return False
    return None


def _handle_primitive_content(
    xml_content: str, open_arg: dict, pos: int
) -> tuple[Any, int, bool]:
    """
    Handle primitive content parsing from XML.
    :param xml_content: The XML content to parse
    :param open_arg: The current opening tag dictionary
    :param pos: The current position in the XML content
    :return: A tuple of (content, new position, has_content)
    """
    opening_tag_string: str = f"<{open_arg['name']}>"
    opening_tag_idx: int = xml_content.rfind(opening_tag_string, 0, len(xml_content))
    content: str = xml_content[opening_tag_idx + len(opening_tag_string) :]
    return content, len(xml_content), True


def _handle_no_matches(
    xml_content: str,
    open_arg: dict,
    attribute_list: list,
    attribute_dict: dict,
    possible_next_opening_tags: dict,
) -> tuple[Any, int, bool]:
    """
    Handle case when no opening or closing tags are found.
    :param xml_content: The XML content to parse
    :param open_arg: The current opening tag dictionary
    :param attribute_list: The list of attributes collected so far
    :param attribute_dict: The dictionary of attributes collected so far
    :param possible_next_opening_tags: Dictionary of possible next opening tags
    :return: A tuple of (parsed content, new position, has_content)
    """
    if _is_list_type(open_arg["origin"]):
        if not attribute_list:
            return [], len(xml_content), False
        return (
            attribute_list[:-1]
            + [
                _fill_with_empty(
                    attribute_list[-1], possible_next_opening_tags[open_arg["name"]]
                )
            ],
            len(xml_content),
            False,
        )

    if _is_pydantic_model(open_arg["origin"]):
        return _fill_with_empty(attribute_dict, open_arg), len(xml_content), False

    return _handle_primitive_content(xml_content, open_arg, len(xml_content))


def _handle_closing_tag(
    xml_content: str,
    open_arg: dict,
    attribute_list: list,
    attribute_dict: dict,
    pos: int,
    closing_match: re.Match,
) -> tuple[Any, int, bool]:
    """
    Handle closing tag parsing.
    :param xml_content: The XML content to parse
    :param open_arg: The current opening tag dictionary
    :param attribute_list: The list of attributes collected so far
    :param attribute_dict: The dictionary of attributes collected so far
    :param pos: The current position in the XML content
    :param closing_match: The regex match object for the closing tag
    :return: A tuple of (parsed content, new position, has_content)
    """
    if _is_list_type(open_arg["origin"]):
        if not attribute_list:
            return [], closing_match.end(), True
        # if not attribute_list and any(arg.get("args", []) for arg in open_arg["args"]):
        #     first_variant: dict = open_arg["args"][0]
        #     empty_dict: dict = _fill_with_empty({}, first_variant)
        #     return [empty_dict], closing_match.end(), True
        return attribute_list, closing_match.end(), True

    if _is_pydantic_model(open_arg["origin"]):
        if not attribute_dict:
            return {}, closing_match.end(), True
        return attribute_dict, closing_match.end(), True

    opening_tag_string: str = f"<{open_arg['name']}>"
    opening_tag_idx: int = xml_content.rfind(opening_tag_string, 0, pos)
    content: str = xml_content[
        opening_tag_idx + len(opening_tag_string) : closing_match.start()
    ]

    if isinstance(open_arg["origin"], type) and issubclass(open_arg["origin"], Enum):
        content: str = content.strip()
        enum_value: Enum | str | None = _convert_enum_content(
            open_arg["origin"], content
        )
        attribute_dict[open_arg["name"]] = enum_value
        return enum_value, closing_match.end(), True

    return content, closing_match.end(), True


def _recurse(
    xml_content: str, open_arg: dict, pos: int
) -> tuple[Union[dict, list], int, bool]:
    """
    Recursively parse the XML content.
    :param xml_content: The XML content to parse
    :param open_arg: The current opening tag dictionary
    :param pos: The current position in the XML content
    :return: A tuple of (parsed content, new position, has_content)
    """
    possible_next_opening_tags: dict = _get_possible_opening_tags(
        open_arg, {open_arg.get("name", "")}
    )

    attribute_dict: dict = {}
    attribute_list: list = []
    has_child_content: bool = False

    if _is_list_type(open_arg["origin"]):
        attribute_dict[open_arg["name"]] = []

    while pos < len(xml_content):
        # Find next opening and closing tags
        open_tag_pattern: str = "|".join(possible_next_opening_tags.keys())
        opening_tag_regex: re.Pattern = re.compile(f"<({open_tag_pattern})>")
        opening_match: Union[re.Match, None] = opening_tag_regex.search(
            xml_content, pos
        )
        if not possible_next_opening_tags:
            opening_match = None

        close_tag_regex: re.Pattern = re.compile(f"</({open_arg['name']})>")
        closing_match: Union[re.Match, None] = close_tag_regex.search(xml_content, pos)

        if not opening_match and not closing_match:
            return _handle_no_matches(
                xml_content,
                open_arg,
                attribute_list,
                attribute_dict,
                possible_next_opening_tags,
            )

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
            elif dict_entry or (new_open_arg["origin"] is str and dict_entry == ""):
                attribute_dict[new_open_arg["name"]] = dict_entry

            pos = new_pos
        elif closing_match:
            return _handle_closing_tag(
                xml_content,
                open_arg,
                attribute_list,
                attribute_dict,
                pos,
                closing_match,
            )

    if _is_list_type(open_arg["origin"]):
        return attribute_list, len(xml_content), has_child_content

    if _is_pydantic_model(open_arg["origin"]):
        return (
            _fill_with_empty(attribute_dict, open_arg),
            len(xml_content),
            has_child_content,
        )

    return _get_default_for_primitive(open_arg), len(xml_content), False


def _fill_with_empty(parsed_dict: dict, type_dict: dict) -> dict:
    """
    Fill the parsed dictionary with empty values for fields that are not present in the XML.
    :param parsed_dict: The parsed dictionary
    :param type_dict: The type dictionary
    :return: The filled dictionary
    """
    for unseen_tag, arg in _get_possible_opening_tags(
        type_dict, set(parsed_dict.keys())
    ).items():
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


def _handle_list_field(field_type: type, field_value: Any) -> tuple[Any, Any]:
    """
    Handle list fields for partial model creation.
    :param field_type: The type of the field
    :param field_value: The value of the field
    :return: A tuple of (field type, field value)
    """
    if field_value is None or field_value == []:
        return (list, [])

    inner_type = get_args(field_type)[0]
    if isinstance(inner_type, type) and issubclass(inner_type, BaseModel):
        new_value = [
            _make_partial(inner_type, item) if isinstance(item, dict) else item
            for item in field_value
        ]
        return (list[inner_type], new_value)
    return (list[inner_type], field_value)


def _handle_union_field(field_type: type, field_value: Any) -> tuple[Any, Any]:
    """
    Handle union fields for partial model creation.
    :param field_type: The type of the field
    :param field_value: The value of the field
    :return: A tuple of (field type, field value)
    """
    if field_value is None:
        return (field_type, None)

    for possible_type in get_args(field_type):
        if isinstance(possible_type, type) and issubclass(possible_type, BaseModel):
            try:
                return (field_type, _make_partial(possible_type, field_value))
            except Exception:
                continue
    return (field_type, field_value)


def _handle_nested_model(field_type: type, field_value: Any) -> tuple[Any, Any]:
    """
    Handle nested model fields for partial model creation.
    :param field_type: The type of the field
    :param field_value: The value of the field
    :return: A tuple of (field type, field value)
    """
    if field_value is None:
        return (field_type, None)
    return (field_type, _make_partial(field_type, field_value))


def _make_partial(model: Type[ModelType], data: dict[str, Any]) -> ModelType:
    """
    Creates a partial version of a Pydantic model where missing fields become None
    and nested models are also made partial.

    :param model: The Pydantic model class to make partial
    :param data: The data dictionary to parse
    :return: A new instance of the model with partial fields
    """
    fields = model.model_fields
    new_fields: dict[str, tuple[Any, Any]] = {}

    for field_name, field in fields.items():
        field_type = field.annotation
        field_value = data.get(field_name)

        if get_origin(field_type) is list:
            new_fields[field_name] = _handle_list_field(field_type, field_value)
        elif isinstance(field_type, type) and issubclass(field_type, BaseModel):
            new_fields[field_name] = _handle_nested_model(field_type, field_value)
        elif get_origin(field_type) is Union:
            new_fields[field_name] = _handle_union_field(field_type, field_value)
        else:
            new_fields[field_name] = (field_type, field_value)

    partial_model = create_model(
        f"Partial{model.__name__}",
        __base__=model,
        **{name: (type_, None) for name, (type_, _) in new_fields.items()},
    )

    return partial_model(**{k: v for k, (_, v) in new_fields.items() if v is not None})


def _convert_enum_content(enum_type: type[Enum], content: str) -> Enum | str | None:
    """
    Converts XML content to the correct Enum member if possible.
    - If 'content' is purely digits, interpret "1" => the first enum member, "2" => second, etc.
    - Otherwise, pass the raw string along, which might match the enum's string value or raise error.
    """
    content = content.strip()
    if not content.isdigit():
        # Just return the stripped string.
        # If it matches an Enum's string value or name, pydantic can parse it.
        return content
    # Attempt 1-based indexing into the enum members
    try:
        idx = int(content) - 1
        members = list(enum_type)
        return members[idx]  # Return the actual Enum member
    except (IndexError, ValueError):
        # If out of range or invalid integer, default to None (pydantic may raise validation error if required)
        return None


def _parse_xml(
    xml_content: str,
    model: Type[ModelType],
    type_dict: dict,
    failed_initial: bool = False,
) -> ModelType:
    """
    Parse the XML content into a Pydantic model.
    :param model: The Pydantic model to parse
    :param xml_content: The XML content to parse
    :param type_dict: The type dictionary from inspect_type_annotation
    :param failed_initial: If the initial parse failed, clean the XML content
    :return: The parsed Pydantic model
    """
    if failed_initial:
        xml_content: str = _clean_xml(xml_content)

    parsed_dict: dict
    parsed_dict, _, _ = _recurse(xml_content, type_dict, 0)
    if not parsed_dict:
        parsed_dict = {}
    parsed_dict = _fill_with_empty(parsed_dict, type_dict)
    return model(**parsed_dict)


def parse_xml(xml_content: str, model: Type[ModelType]) -> ModelType:
    """
    Parse the XML content into a Pydantic model.
    :param xml_content: The XML content to parse
    :param model: The Pydantic model to parse
    :return: The parsed Pydantic model
    """
    assert isinstance(model, type) and issubclass(
        model, BaseModel
    ), "Model must be a Pydantic model"
    type_dict: dict = _inspect_type_annotation(model)
    try:
        return _parse_xml(xml_content, model, type_dict)
    except Exception:
        return _parse_xml(xml_content, model, type_dict, failed_initial=True)
