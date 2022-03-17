#!/usr/bin/env python3
# -*- coding: utf-8 -*-
#
# Copyright (c) 2012-2022 Snowflake Computing Inc. All rights reserved.
#
# Code in this file may constitute partial or total reimplementation, or modification of
# existing code originally distributed by the Apache Software Foundation as part of the
# Apache Spark project, under the Apache License, Version 2.0.
import ast
import ctypes
import datetime
import decimal
import re
import sys
import typing  # type: ignore
from array import array
from typing import Any, Dict, List, Optional, Tuple, Type, Union, get_args, get_origin

import snowflake.snowpark.types  # type: ignore
from snowflake.snowpark.types import (
    ArrayType,
    BinaryType,
    BooleanType,
    ByteType,
    DataType,
    DateType,
    DecimalType,
    DoubleType,
    FloatType,
    Geography,
    GeographyType,
    IntegerType,
    LongType,
    MapType,
    NullType,
    ShortType,
    StringType,
    StructField,
    StructType,
    TimestampType,
    TimeType,
    Variant,
    VariantType,
    _NumericType,
)


def convert_to_sf_type(datatype: DataType) -> str:
    if isinstance(datatype, DecimalType):
        return f"NUMBER({datatype.precision}, {datatype.scale})"
    if isinstance(datatype, IntegerType):
        return "INT"
    if isinstance(datatype, ShortType):
        return "SMALLINT"
    if isinstance(datatype, ByteType):
        return "BYTEINT"
    if isinstance(datatype, LongType):
        return "BIGINT"
    if isinstance(datatype, FloatType):
        return "FLOAT"
    if isinstance(datatype, DoubleType):
        return "DOUBLE"
    # We regard NullType as String, which is required when creating
    # a dataframe from local data with all None values
    if isinstance(datatype, (StringType, NullType)):
        return "STRING"
    if isinstance(datatype, BooleanType):
        return "BOOLEAN"
    if isinstance(datatype, DateType):
        return "DATE"
    if isinstance(datatype, TimeType):
        return "TIME"
    if isinstance(datatype, TimestampType):
        return "TIMESTAMP"
    if isinstance(datatype, BinaryType):
        return "BINARY"
    if isinstance(datatype, ArrayType):
        return "ARRAY"
    if isinstance(datatype, MapType):
        return "OBJECT"
    if isinstance(datatype, VariantType):
        return "VARIANT"
    if isinstance(datatype, GeographyType):
        return "GEOGRAPHY"
    raise TypeError(f"Unsupported data type: {datatype.type_name}")


# #####################################################################################
# Converting python types to types
# Taken as is or modified from:
# https://spark.apache.org/docs/3.1.1/api/python/_modules/pyspark/sql/types.html

# Mapping Python types to Spark SQL DataType
NoneType = type(None)
_type_mappings = {
    NoneType: NullType,
    bool: BooleanType,
    int: LongType,
    float: FloatType,
    str: StringType,
    bytearray: BinaryType,
    decimal.Decimal: DecimalType,
    datetime.date: DateType,
    datetime.datetime: TimestampType,
    datetime.time: TimeType,
    bytes: BinaryType,
}


_VALID_PYTHON_TYPES_FOR_LITERAL_VALUE = tuple(_type_mappings.keys())
_VALID_SNOWPARK_TYPES_FOR_LITERAL_VALUE = (
    *_type_mappings.values(),
    _NumericType,
)

# Mapping Python array types to Spark SQL DataType
# We should be careful here. The size of these types in python depends on C
# implementation. We need to make sure that this conversion does not lose any
# precision. Also, JVM only support signed types, when converting unsigned types,
# keep in mind that it require 1 more bit when stored as signed types.
#
# Reference for C integer size, see:
# ISO/IEC 9899:201x specification, chapter 5.2.4.2.1 Sizes of integer types <limits.h>.
# Reference for python array typecode, see:
# https://docs.python.org/2/library/array.html
# https://docs.python.org/3.6/library/array.html
# Reference for JVM's supported integral types:
# http://docs.oracle.com/javase/specs/jvms/se8/html/jvms-2.html#jvms-2.3.1

_array_signed_int_typecode_ctype_mappings = {
    "b": ctypes.c_byte,
    "h": ctypes.c_short,
    "i": ctypes.c_int,
    "l": ctypes.c_long,
    "q": ctypes.c_longlong,
}

_array_unsigned_int_typecode_ctype_mappings = {
    "B": ctypes.c_ubyte,
    "H": ctypes.c_ushort,
    "I": ctypes.c_uint,
    "L": ctypes.c_ulong,
    "Q": ctypes.c_ulonglong,
}


def _int_size_to_type(size: int) -> Type[DataType]:
    """
    Return the Catalyst datatype from the size of integers.
    """
    if size <= 8:
        return ByteType
    if size <= 16:
        return ShortType
    if size <= 32:
        return IntegerType
    if size <= 64:
        return LongType


# The list of all supported array typecodes, is stored here
_array_type_mappings = {
    # Warning: Actual properties for float and double in C is not specified in C.
    # On almost every system supported by both python and JVM, they are IEEE 754
    # single-precision binary floating-point format and IEEE 754 double-precision
    # binary floating-point format. And we do assume the same thing here for now.
    "f": FloatType,
    "d": DoubleType,
}

# compute array typecode mappings for signed integer types
for _typecode in _array_signed_int_typecode_ctype_mappings.keys():
    size = ctypes.sizeof(_array_signed_int_typecode_ctype_mappings[_typecode]) * 8
    dt = _int_size_to_type(size)
    if dt is not None:
        _array_type_mappings[_typecode] = dt

# compute array typecode mappings for unsigned integer types
for _typecode in _array_unsigned_int_typecode_ctype_mappings.keys():
    # JVM does not have unsigned types, so use signed types that is at least 1
    # bit larger to store
    size = ctypes.sizeof(_array_unsigned_int_typecode_ctype_mappings[_typecode]) * 8 + 1
    dt = _int_size_to_type(size)
    if dt is not None:
        _array_type_mappings[_typecode] = dt

# Type code 'u' in Python's array is deprecated since version 3.3, and will be
# removed in version 4.0. See: https://docs.python.org/3/library/array.html
if sys.version_info[0] < 4:
    _array_type_mappings["u"] = StringType


def _infer_type(obj: Any) -> DataType:
    """Infer the DataType from obj"""
    if obj is None:
        return NullType()

    # user-defined types
    if hasattr(obj, "__UDT__"):
        return obj.__UDT__

    datatype = _type_mappings.get(type(obj))
    if datatype is DecimalType:
        # the precision and scale of `obj` may be different from row to row.
        return DecimalType(38, 18)
    elif datatype is not None:
        return datatype()

    if isinstance(obj, dict):
        for key, value in obj.items():
            if key is not None and value is not None:
                return MapType(_infer_type(key), _infer_type(value))
        return MapType(NullType(), NullType())
    elif isinstance(obj, (list, tuple)):
        for v in obj:
            if v is not None:
                return ArrayType(_infer_type(obj[0]))
        return ArrayType(NullType())
    elif isinstance(obj, array):
        if obj.typecode in _array_type_mappings:
            return ArrayType(_array_type_mappings[obj.typecode]())
        else:
            raise TypeError("not supported type: array(%s)" % obj.typecode)
    else:
        raise TypeError("not supported type: %s" % type(obj))


def _infer_schema(
    row: Union[Dict, List, Tuple], names: Optional[List] = None
) -> StructType:
    if row is None or (isinstance(row, (tuple, list, dict)) and not row):
        items = zip(names if names else ["_1"], [None])
    else:
        if isinstance(row, dict):
            items = row.items()
        elif isinstance(row, (tuple, list)):
            row_fields = getattr(row, "_fields", None)
            if row_fields:  # Row or namedtuple
                items = zip(row_fields, row)
            else:
                if names is None:
                    names = [f"_{i}" for i in range(1, len(row) + 1)]
                elif len(names) < len(row):
                    names.extend(f"_{i}" for i in range(len(names) + 1, len(row) + 1))
                items = zip(names, row)
        elif isinstance(row, _VALID_PYTHON_TYPES_FOR_LITERAL_VALUE):
            items = zip(names if names else ["_1"], [row])
        else:
            raise TypeError("Can not infer schema for type: %s" % type(row))

    fields = []
    for k, v in items:
        try:
            fields.append(StructField(k, _infer_type(v), True))
        except TypeError as e:
            raise TypeError(
                "Unable to infer the type of the field {}.".format(k)
            ) from e
    return StructType(fields)


def _merge_type(a: DataType, b: DataType, name: Optional[str] = None) -> DataType:
    if name is None:
        new_msg = lambda msg: msg
        new_name = lambda n: "field %s" % n
    else:
        new_msg = lambda msg: "{}: {}".format(name, msg)
        new_name = lambda n: "field {} in {}".format(n, name)

    # null type
    if isinstance(a, NullType):
        return b
    elif isinstance(b, NullType):
        return a
    elif type(a) is not type(b):
        raise TypeError(new_msg("Cannot merge type {} and {}".format(type(a), type(b))))

    # same type
    if isinstance(a, StructType):
        nfs = {f.name: f.datatype for f in b.fields}
        fields = [
            StructField(
                f.name,
                _merge_type(
                    f.datatype, nfs.get(f.name, NullType()), name=new_name(f.name)
                ),
            )
            for f in a.fields
        ]
        names = {f.name for f in fields}
        for n in nfs:
            if n not in names:
                fields.append(StructField(n, nfs[n]))
        return StructType(fields)

    elif isinstance(a, ArrayType):
        return ArrayType(
            _merge_type(
                a.element_type, b.element_type, name="element in array %s" % name
            )
        )

    elif isinstance(a, MapType):
        return MapType(
            _merge_type(a.key_type, b.key_type, name="key of map %s" % name),
            _merge_type(a.value_type, b.value_type, name="value of map %s" % name),
        )
    else:
        return a


def _python_type_str_to_object(tp_str: str) -> Type:
    # handle several special cases, which we want to support currently
    if tp_str == "Decimal":
        return decimal.Decimal
    elif tp_str == "date":
        return datetime.date
    elif tp_str == "time":
        return datetime.time
    elif tp_str == "datetime":
        return datetime.datetime
    else:
        return eval(tp_str)


def _python_type_to_snow_type(tp: Union[str, Type]) -> Tuple[DataType, bool]:
    """Converts a Python type or a Python type string to a Snowpark type.
    Returns a Snowpark type and whether it's nullable.
    """
    # convert a type string to a type object
    if isinstance(tp, str):
        tp = _python_type_str_to_object(tp)

    if tp is decimal.Decimal:
        return DecimalType(38, 18), False
    elif tp in _type_mappings:
        return _type_mappings[tp](), False

    tp_origin = get_origin(tp)
    tp_args = get_args(tp)

    # only typing.Optional[X], i.e., typing.Union[X, None] is accepted
    if (
        tp_origin
        and tp_origin == Union
        and tp_args
        and len(tp_args) == 2
        and tp_args[1] == NoneType
    ):
        return _python_type_to_snow_type(tp_args[0])[0], True

    # typing.List, typing.Tuple, list, tuple
    list_tps = [list, tuple, List, Tuple]
    if tp in list_tps or (tp_origin and tp_origin in list_tps):
        element_type = (
            _python_type_to_snow_type(tp_args[0])[0] if tp_args else StringType()
        )
        return ArrayType(element_type), False

    # typing.Dict, dict
    dict_tps = [dict, Dict]
    if tp in dict_tps or (tp_origin and tp_origin in dict_tps):
        key_type = _python_type_to_snow_type(tp_args[0])[0] if tp_args else StringType()
        value_type = (
            _python_type_to_snow_type(tp_args[1])[0] if tp_args else StringType()
        )
        return MapType(key_type, value_type), False

    if tp == Variant:
        return VariantType(), False

    if tp == Geography:
        return GeographyType(), False

    raise TypeError(f"invalid type {tp}")


def _retrieve_func_type_hints_from_source(
    file_path: str, func_name: str, _source: Optional[str] = None
) -> Dict[str, Type]:
    """
    Retrieve type hints of a function from a source file, or a source string (test only).
    """

    def parse_arg_annotation(annotation: ast.expr) -> str:
        if isinstance(annotation, (ast.Tuple, ast.List)):
            return ", ".join([parse_arg_annotation(e) for e in annotation.elts])
        if isinstance(annotation, ast.Attribute):
            return f"{parse_arg_annotation(annotation.value)}.{annotation.attr}"
        if isinstance(annotation, ast.Subscript):
            return f"{parse_arg_annotation(annotation.value)}[{parse_arg_annotation(annotation.slice)}]"
        if isinstance(annotation, ast.Index):
            return parse_arg_annotation(annotation.value)
        if isinstance(annotation, ast.Constant) and annotation.value is None:
            return "NoneType"
        if isinstance(annotation, ast.Name):
            return annotation.id
        raise TypeError(f"invalid type annotation: {annotation}")

    class NodeVisitor(ast.NodeVisitor):
        type_hints = {}
        func_exist = False

        def visit_FunctionDef(self, node):
            if node.name == func_name:
                for arg in node.args.args:
                    if arg.annotation:
                        self.type_hints[arg.arg] = parse_arg_annotation(arg.annotation)
                    else:
                        raise TypeError(
                            f"arg {arg.arg} does not have a type annotation"
                        )

                if node.returns:
                    self.type_hints["return"] = parse_arg_annotation(node.returns)
                else:
                    raise TypeError(f"return does not have a type annotation")
                self.func_exist = True

    if not _source:
        if not file_path.endswith(".py"):
            raise ValueError(
                f"{file_path} is not a Python file, so type hints cannot be extracted"
            )
        with open(file_path, "r") as f:
            _source = f.read()

    visitor = NodeVisitor()
    visitor.visit(ast.parse(_source))
    if not visitor.func_exist:
        raise ValueError(f"function {func_name} is not found in file {file_path}")
    return visitor.type_hints


# Get a mapping from type string to type object, for cast() function
def _get_data_type_string_object_mappings(
    to_fill_dict: Optional[Dict[str, Type[DataType]]] = None,
    data_type: Optional[Type[DataType]] = None,
) -> None:
    if data_type is None:
        if to_fill_dict is None:
            to_fill_dict = dict()
        return _get_data_type_string_object_mappings(to_fill_dict, DataType)
    for child in data_type.__subclasses__():
        if not child.__name__.startswith("_") and child is not DecimalType:
            to_fill_dict[child.__name__[:-4].lower()] = child
        _get_data_type_string_object_mappings(to_fill_dict, child)
    return to_fill_dict


_DATA_TYPE_STRING_OBJECT_MAPPINGS = {}
_get_data_type_string_object_mappings(_DATA_TYPE_STRING_OBJECT_MAPPINGS)
# Add additional mappings to match snowflake db data types
_DATA_TYPE_STRING_OBJECT_MAPPINGS["int"] = IntegerType
_DATA_TYPE_STRING_OBJECT_MAPPINGS["smallint"] = ShortType
_DATA_TYPE_STRING_OBJECT_MAPPINGS["byteint"] = ByteType
_DATA_TYPE_STRING_OBJECT_MAPPINGS["bigint"] = LongType
_DATA_TYPE_STRING_OBJECT_MAPPINGS["number"] = DecimalType
_DATA_TYPE_STRING_OBJECT_MAPPINGS["numeric"] = DecimalType
_DATA_TYPE_STRING_OBJECT_MAPPINGS["object"] = MapType
_DATA_TYPE_STRING_OBJECT_MAPPINGS["array"] = ArrayType

_DECIMAL_RE = re.compile(
    r"^\s*(numeric|number|decimal)\s*\(\s*(\s*)(\d*)\s*,\s*(\d*)\s*\)\s*$"
)
# support type string format like "  decimal  (  2  ,  1  )  "


def _get_number_precision_scale(type_str: str) -> Optional[Tuple[int, int]]:
    decimal_matches = _DECIMAL_RE.match(type_str)
    if decimal_matches:
        return int(decimal_matches.group(3)), int(decimal_matches.group(4))


def _type_string_to_type_object(type_str: str) -> DataType:
    precision_scale = _get_number_precision_scale(type_str)
    if precision_scale:
        return DecimalType(*precision_scale)
    type_str = type_str.replace(" ", "")
    type_str = type_str.lower()
    try:
        return _DATA_TYPE_STRING_OBJECT_MAPPINGS[type_str]()
    except KeyError:
        raise ValueError(f"'{type_str}' is not a supported type")


# Type hints
ColumnOrName = Union["snowflake.snowpark.column.Column", str]
LiteralType = Union[_VALID_PYTHON_TYPES_FOR_LITERAL_VALUE]
ColumnOrLiteral = Union["snowflake.snowpark.column.Column", LiteralType]