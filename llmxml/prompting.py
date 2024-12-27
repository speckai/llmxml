import types
from enum import Enum
from typing import Literal, Union, get_args

from pydantic import BaseModel
from pydantic.fields import FieldInfo

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

    # Handle Enum types
    if isinstance(field_info.annotation, type) and issubclass(field_info.annotation, Enum):
        enum_values = [e.value for e in field_info.annotation]
        output = f"<{field_name}>\n[type: {field_info.annotation.__name__}]\n[{required_info}]"
        if field_info.description:
            output += f"\n[{field_info.description}]"
        output += f"\n[{field_info.annotation.__name__} values: {', '.join(map(str, enum_values))}]\n</{field_name}>"
        return output

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
            output = f"<{field_name}>\n[type: list[{item_type.__name__}]]\n[{required_info}]"
            if field_info.description:
                output += f"\n[{field_info.description}]"
            output += (
                f"\n<{item_name}>\n"
                + "\n".join(nested_prompts)
                + f"\n</{item_name}>\n</{field_name}>"
            )
            return output

        # If the list contains enums, show possible values
        if isinstance(item_type, type) and issubclass(item_type, Enum):
            enum_values = [e.value for e in item_type]
            output = f"<{field_name}>\n[type: list[{item_type.__name__}]]\n[{required_info}]"
            if field_info.description:
                output += f"\n[{field_info.description}]"
            output += f"\n[{item_type.__name__} values: {', '.join(map(str, enum_values))}]\n</{field_name}>"
            return output

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
        output = f"<{field_name}>\n[{type_info}]\n[{required_info}]"
        if field_info.description:
            output += f"\n[{field_info.description}]"
        output += "\n" + "\n".join(nested_prompts) + f"\n</{field_name}>"
        return output

    output = f"<{field_name}>\n[{type_info}]\n[{required_info}]"
    if field_info.description:
        output += f"\n[{field_info.description}]"
    output += f"\n</{field_name}>"
    return output
