import re
import types
from types import NoneType
from typing import Type, TypeVar, Union, get_args, get_origin

from pydantic import BaseModel

ModelType = TypeVar("ModelType", bound=BaseModel)


def _camel_to_snake(string: str) -> str:
    """
    Convert a camelCase string to a snake_case string.
    :param string: The string to convert.
    :return: The converted string.
    """
    return re.sub("(?!^)([A-Z]+)", r"_\1", string).lower()


def _inspect_type_annotation(annotation: type, name: str = "") -> dict:
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
            "args": [_inspect_type_annotation(arg) for arg in args],
        }

    # Mainly for Union
    if hasattr(annotation, "__origin__"):
        origin: type = get_origin(annotation)
        args: list = get_args(annotation)

        return {
            "origin": origin,
            "args": [_inspect_type_annotation(arg, name) for arg in args],
        }

    # For pydantic models
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

    # For primitives
    return {
        "origin": annotation,
        "name": name,
    }


def _clean_xml(xml_content: str) -> str:
    """
    Clean the XML content by removing the leading and trailing tags.
    :param xml_content: The XML content to clean.
    :return: The cleaned XML content.
    """
    xml_content: str = re.sub(r"^[^<]*", "", xml_content)
    xml_content: str = re.sub(r"[^>]*$", "", xml_content)
    return xml_content


def _is_list_type(t: type) -> bool:
    """
    Check if the type is a list.
    :param t: The type to check.
    :return: True if the type is a list, False otherwise.
    """
    if t is list:
        return True

    # Check if it's a generic list type
    return t.__origin__ is list if isinstance(t, types.GenericAlias) else False


def _is_pydantic_model(t: type) -> bool:
    """
    Check if the type is a pydantic model.
    :param t: The type to check.
    :return: True if the type is a pydantic model, False otherwise.
    """
    return isinstance(t, type) and issubclass(t, BaseModel)


def _is_field_optional(type_dict: dict, field: str) -> bool:
    """
    Check if the field is optional.
    :param type_dict: The type dictionary.
    :param field: The field to check.
    :return: True if the field is optional, False otherwise.
    """
    args = type_dict.get("args", [])
    for arg in args:
        if "name" not in arg:
            union_args = arg.get("args", [])
            if union_args[0]["name"] != field:
                continue

            return any(union_arg["origin"] is NoneType for union_arg in union_args)

    return False


def _get_possible_opening_tags(type_dict: dict, seen_tags: set[str] = set()) -> dict:
    """
    Get the possible opening tags for a given type.
    :param type_dict: The type dictionary.
    :param seen_tags: The set of tags that have already been seen.
    :return: The possible opening tags.
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
    :param arg: The type dictionary.
    :return: The default value for the primitive type.
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


def _recurse(
    xml_content: str, open_arg: dict, pos: int
) -> tuple[Union[dict, list], int, bool]:
    """
    Recurse through the XML content to construct the model.
    :param xml_content: The XML content to parse.
    :param open_arg: The type dictionary.
    :param pos: The current position in the XML content.
    :return: A tuple containing the constructed model, the new position, and whether there is any content.
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

            # Primitive
            opening_tag_string: str = f"<{open_arg['name']}>"
            opening_tag_idx: int = xml_content.rfind(
                opening_tag_string, 0, len(xml_content)
            )

            content: str = xml_content[opening_tag_idx + len(opening_tag_string) :]
            return content, len(xml_content), True
        if opening_match and (
            not closing_match or opening_match.start() < closing_match.start()
        ):
            # We should recurse on the lower text, with the current open_arg passed in
            new_open_arg: dict = possible_next_opening_tags[opening_match.group(1)]

            dict_entry: Union[dict, list, str, int, float, bool, None]
            new_pos: int
            is_content: bool
            dict_entry, new_pos, is_content = _recurse(
                xml_content, new_open_arg, opening_match.end()
            )
            has_child_content |= is_content

            if _is_list_type(open_arg["origin"]) and is_content:
                attribute_list.append(dict_entry)
            elif dict_entry:
                attribute_dict[new_open_arg["name"]] = dict_entry  # TODO might be fishy
            pos = new_pos
        elif closing_match:
            if _is_list_type(open_arg["origin"]):
                return attribute_list, closing_match.end(), True

            if _is_pydantic_model(open_arg["origin"]):
                return attribute_dict, closing_match.end(), True

            # Primitive
            opening_tag_string = f"<{open_arg['name']}>"
            opening_tag_idx = xml_content.rfind(opening_tag_string, 0, pos)

            content = xml_content[
                opening_tag_idx + len(opening_tag_string) : closing_match.start()
            ]
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

    # Primitive
    return _get_default_for_primitive(open_arg), len(xml_content), False


def _fill_with_empty(parsed_dict: dict, type_dict: dict) -> dict:
    for unseen_tag, arg in _get_possible_opening_tags(
        type_dict, set(parsed_dict.keys())
    ).items():
        if _is_field_optional(parsed_dict, unseen_tag):
            continue
        if _is_pydantic_model(arg["origin"]):
            parsed_dict[unseen_tag] = _fill_with_empty({}, arg)
        elif _is_list_type(arg["origin"]):
            parsed_dict[unseen_tag] = []
        # Primitive Type
        elif isinstance(arg["origin"], type):
            parsed_dict[unseen_tag] = _get_default_for_primitive(arg)

    return parsed_dict


def parse_xml(model: Type[ModelType], xml_content: str) -> ModelType:
    """
    Parse the XML content into a pydantic model.
    :param model: The pydantic model to parse the XML content into.
    :param xml_content: The XML content to parse.
    :return: The parsed pydantic model.
    """
    xml_content: str = _clean_xml(xml_content)
    type_dict: dict = _inspect_type_annotation(model)

    parsed_dict: dict
    parsed_dict, _, _ = _recurse(xml_content, type_dict, 0)
    if not parsed_dict:
        parsed_dict = {}
    parsed_dict = _fill_with_empty(parsed_dict, type_dict)

    return model(**parsed_dict)
