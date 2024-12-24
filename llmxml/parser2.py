import json
import re
from types import UnionType, NoneType
from typing import Any, Type, TypeVar, Union, get_args, get_origin
import types
from xml.etree import ElementTree as ET

from pydantic import BaseModel, Field, GetJsonSchemaHandler, create_model
from pydantic_core import CoreSchema, core_schema

T = TypeVar("T", bound=BaseModel)


def camel_to_snake(string: str) -> str:
    return re.sub("(?!^)([A-Z]+)", r"_\1", string).lower()


def inspect_type_annotation(annotation, name: str = "") -> dict:
    """
    Recursively inspect a type annotation to extract its components.

    Args:
        annotation: A type annotation (can be GenericAlias, Union, or other typing constructs)

    Returns:
        dict: A dictionary of the type structure
    """
    # Mainly for list
    if isinstance(annotation, types.GenericAlias):
        # print(1)
        origin = get_origin(annotation)
        origin = annotation
        args = get_args(annotation)
        assert all(
            hasattr(arg, "__origin__")
            or (isinstance(arg, type) and issubclass(arg, BaseModel))
            for arg in args
        ), "Lists of primitives not allowed. Wrap the naked field in a pydantic model."
        # print(f"{origin=} {name=} {args=}")

        return {
            "origin": origin,
            "name": name,
            "args": [inspect_type_annotation(arg) for arg in args],
        }

    # Mainly for Union
    if hasattr(annotation, "__origin__"):
        # print(2)
        origin = get_origin(annotation)
        origin = annotation
        name = camel_to_snake(name)
        args = get_args(annotation)
        # print(f"{origin=} {name=} {args=}")

        return {
            "origin": origin,
            # no 'name' because one of the children will have it
            "args": [inspect_type_annotation(arg, name) for arg in args],
        }

    # For pydantic models
    if isinstance(annotation, type) and issubclass(annotation, BaseModel):
        # print(3)
        origin = annotation
        name = camel_to_snake(annotation.__name__)
        args = [
            (value.annotation, field)
            for field, value in annotation.model_fields.items()
        ]
        # print(f"{origin=} {name=} {args=}")

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
    xml_content = re.sub(r"^[^<]*", "", xml_content)
    xml_content = re.sub(r"[^>]*$", "", xml_content)
    return xml_content


def _is_list_type(t) -> bool:
    # Check if it's a raw list
    if t is list:
        return True
    
    # Check if it's a generic list type
    if isinstance(t, types.GenericAlias):
        return t.__origin__ is list
    
    return False

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
        return {arg["name"]: arg for arg in args if "name" in arg and arg["origin"] is not NoneType}

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
    print(f"ALERT RETURNING NONE {arg["origin"]=}")
    return None

"""
Returns
    - Constructed instance of type, filled with default fields if dict + necessary
    - New position of xml parser
    - IsContent - Whether there is any content or is it all default
"""
def _recurse(xml_content: str, open_arg: dict, pos: int) -> tuple[Union[dict, list], int, bool]:
    # print(f"----\n{open_arg=} \n{pos=}")
    possible_next_opening_tags = _get_possible_opening_tags(open_arg, set([open_arg.get("name", "")]))

    attribute_dict: dict = {} # lists only
    attribute_list: list = []
    has_child_content = False
    
    if _is_list_type(open_arg["origin"]):
        attribute_dict[open_arg["name"]] = []
    while pos < len(xml_content):
        open_tag_pattern = '|'.join(possible_next_opening_tags.keys())
        opening_tag_regex = re.compile(f"<({open_tag_pattern})>")
        opening_match = opening_tag_regex.search(xml_content, pos)
        if len(possible_next_opening_tags) == 0:
            opening_match = None
        
        close_tag_regex = re.compile(f"</({open_arg["name"]})>")
        closing_match = close_tag_regex.search(xml_content, pos)

        if not opening_match and not closing_match:
            if _is_list_type(open_arg["origin"]):
                if len(attribute_list) == 0:
                    return [], len(xml_content), False
                return attribute_list[:-1] + [_fill_with_empty(attribute_list[-1], possible_next_opening_tags[open_arg["name"]])], len(xml_content), False

            if _is_pydantic_model(open_arg["origin"]):
                return _fill_with_empty(attribute_dict, open_arg), len(xml_content), False
            
            # Primitive
            opening_tag_string = f"<{open_arg['name']}>"
            opening_tag_idx = xml_content.rfind(opening_tag_string, 0, len(xml_content))

            content = xml_content[opening_tag_idx + len(opening_tag_string):]
            return content, len(xml_content), True
        if opening_match and (
            not closing_match or opening_match.start() < closing_match.start()
        ):
            # We should recurse on the lower text, with the current open_arg passed in
            new_open_arg = possible_next_opening_tags[opening_match.group(1)]

            dict_entry, new_pos, is_content = _recurse(xml_content, new_open_arg, opening_match.end())
            has_child_content |= is_content
            # print(f"----\n{dict_entry=} \n{new_pos=}")

            if _is_list_type(open_arg["origin"]) and is_content:
                attribute_list.append(dict_entry)
                print(f"{open_arg["name"]} closed")
            elif dict_entry:
                attribute_dict[new_open_arg["name"]] = dict_entry # TODO might be fishy
                print(f"{new_open_arg["name"]} closed")
            pos = new_pos
        elif closing_match:
            if _is_list_type(open_arg["origin"]):
                return attribute_list, closing_match.end(), True

            if _is_pydantic_model(open_arg["origin"]):
                return attribute_dict, closing_match.end(), True
            
            # Primitive
            opening_tag_string = f"<{open_arg['name']}>"
            opening_tag_idx = xml_content.rfind(opening_tag_string, 0, pos)

            content = xml_content[opening_tag_idx + len(opening_tag_string):closing_match.start()]
            attribute_dict[open_arg["name"]] = content
            return content, closing_match.end(), True

    if _is_list_type(open_arg["origin"]):
        return attribute_list, len(xml_content), has_child_content

    if _is_pydantic_model(open_arg["origin"]):
        return _fill_with_empty(attribute_dict, open_arg), len(xml_content), has_child_content
    
    # Primitive
    return _get_default_for_primitive(open_arg), len(xml_content), False


def _fill_with_empty(parsed_dict: dict, type_dict: dict) -> dict:
    for unseen_tag, arg in _get_possible_opening_tags(type_dict, set(parsed_dict.keys())).items():
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
        

def parse_xml(model: Type[T], xml_content: str) -> T:
    xml_content = _clean_xml(xml_content)
    type_dict = inspect_type_annotation(model)
    print(type_dict)

    parsed_dict, _, _ = _recurse(xml_content, type_dict, 0)
    if not parsed_dict:
        parsed_dict = {}
    parsed_dict = _fill_with_empty(parsed_dict, type_dict)
    
    print(parsed_dict)
    return model(**parsed_dict)