import pytest

from eth_abi import encode_abi

from eth_abi.grammar import parse

from ..common import CORRECT_TUPLE_ENCODINGS


@pytest.mark.parametrize('type_str,python_value,expected', CORRECT_TUPLE_ENCODINGS)
def test_encode_abi(type_str, python_value, expected):
    abi_type = parse(type_str)
    types = [str(t) for t in abi_type.components]

    actual = encode_abi(types, python_value)
    assert actual == expected
