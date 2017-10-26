from __future__ import unicode_literals

import pytest

import decimal
from io import BytesIO

from hypothesis import (
    given,
    settings,
    example,
    strategies as st,
)

from eth_utils import (
    decode_hex,
    to_normalized_address,
)

from eth_abi.constants import (
    TT256M1,
)
from eth_abi.exceptions import (
    InsufficientDataBytes,
    NonEmptyPaddingBytes,
)
from eth_abi.decoding import (
    UnsignedIntegerDecoder,
    SignedIntegerDecoder,
    UnsignedRealDecoder,
    SignedRealDecoder,
    StringDecoder,
    BytesDecoder,
    MultiDecoder,
    BooleanDecoder,
    AddressDecoder,
    DynamicArrayDecoder,
    get_single_decoder,
)

from eth_abi.utils.parsing import (
    process_type,
)
from eth_abi.utils.padding import (
    zpad32,
)
from eth_abi.utils.numeric import (
    big_endian_to_int,
    int_to_big_endian,
    compute_signed_integer_bounds,
    quantize_value,
    ceil32,
)


def is_non_empty_non_null_byte_string(value):
    return value and big_endian_to_int(value) != 0


@settings(max_examples=1000)
@given(
    integer_bit_size=st.integers(min_value=1, max_value=32).map(lambda v: v * 8),
    stream_bytes=st.binary(min_size=0, max_size=32, average_size=32),
    data_byte_size=st.integers(min_value=0, max_value=32),
)
def test_decode_unsigned_int(integer_bit_size, stream_bytes, data_byte_size):
    if integer_bit_size % 8 != 0:
        with pytest.raises(ValueError):
            UnsignedIntegerDecoder.as_decoder(
                value_bit_size=integer_bit_size,
                data_byte_size=data_byte_size,
            )
        return
    elif integer_bit_size > data_byte_size * 8:
        with pytest.raises(ValueError):
            UnsignedIntegerDecoder.as_decoder(
                value_bit_size=integer_bit_size,
                data_byte_size=data_byte_size,
            )
        return
    else:
        decoder = UnsignedIntegerDecoder.as_decoder(
            value_bit_size=integer_bit_size,
            data_byte_size=data_byte_size,
        )


    stream = BytesIO(stream_bytes)
    actual_value = big_endian_to_int(stream_bytes[:data_byte_size])

    if len(stream_bytes) < data_byte_size:
        with pytest.raises(InsufficientDataBytes):
            decoder(stream)
        return
    elif actual_value > 2 ** integer_bit_size - 1:
        with pytest.raises(NonEmptyPaddingBytes):
            decoder(stream)
        return
    else:
        decoded_value = decoder(stream)

    assert decoded_value == actual_value


@settings(max_examples=1000)
@given(
    integer_bit_size=st.integers(min_value=1, max_value=32).map(lambda v: v * 8),
    stream_bytes=st.binary(min_size=0, max_size=32, average_size=32),
    data_byte_size=st.integers(min_value=0, max_value=32),
)
@example(8, b'\x00\x80', 2)
@example(8, b'\xff\xff', 2)
def test_decode_signed_int(integer_bit_size, stream_bytes, data_byte_size):
    if integer_bit_size % 8 != 0:
        with pytest.raises(ValueError):
            SignedIntegerDecoder.as_decoder(
                value_bit_size=integer_bit_size,
                data_byte_size=data_byte_size,
            )
        return
    elif integer_bit_size > data_byte_size * 8:
        with pytest.raises(ValueError):
            SignedIntegerDecoder.as_decoder(
                value_bit_size=integer_bit_size,
                data_byte_size=data_byte_size,
            )
        return
    else:
        decoder = SignedIntegerDecoder.as_decoder(
            value_bit_size=integer_bit_size,
            data_byte_size=data_byte_size,
        )


    stream = BytesIO(stream_bytes)

    padding_bytes = data_byte_size - integer_bit_size // 8

    raw_value = big_endian_to_int(stream_bytes[padding_bytes:data_byte_size])
    if raw_value >= 2 ** (integer_bit_size - 1):
        actual_value = raw_value - 2 ** integer_bit_size
    else:
        actual_value = raw_value

    if len(stream_bytes) < data_byte_size:
        with pytest.raises(InsufficientDataBytes):
            decoder(stream)
        return
    elif (
        (actual_value >= 0 and any(byte != 0 for byte in stream_bytes[:padding_bytes])) or
        (actual_value < 0 and any(byte != 255 for byte in stream_bytes[:padding_bytes]))
    ):
        with pytest.raises(NonEmptyPaddingBytes):
            decoder(stream)
        return
    else:
        decoded_value = decoder(stream)

    assert decoded_value == actual_value


@settings(max_examples=1000)
@given(
    string_bytes=st.binary(min_size=0, max_size=256),
    pad_size=st.integers(min_value=0, max_value=32),
)
def test_decode_bytes_and_string(string_bytes, pad_size):
    size_bytes = zpad32(int_to_big_endian(len(string_bytes)))
    padded_string_bytes = string_bytes + b'\x00' * pad_size
    stream_bytes = size_bytes + padded_string_bytes
    stream = BytesIO(stream_bytes)

    decoder = StringDecoder.as_decoder()

    if len(padded_string_bytes) < ceil32(len(string_bytes)):
        with pytest.raises(InsufficientDataBytes):
            decoder(stream)
        return

    decoded_value = decoder(stream)
    assert decoded_value == string_bytes


@settings(max_examples=1000)
@given(
    stream_bytes=st.binary(min_size=1, max_size=32, average_size=32),
    data_byte_size=st.integers(min_value=1, max_value=32),
)
def test_decode_boolean(stream_bytes, data_byte_size):
    stream = BytesIO(stream_bytes)

    decoder = BooleanDecoder.as_decoder(data_byte_size=data_byte_size)

    if len(stream_bytes) < data_byte_size:
        with pytest.raises(InsufficientDataBytes):
            decoder(stream)
        return

    padding_bytes = stream_bytes[:data_byte_size][:-1]
    if is_non_empty_non_null_byte_string(padding_bytes):
        with pytest.raises(NonEmptyPaddingBytes):
            decoder(stream)
        return

    byte_value = stream_bytes[data_byte_size - 1]

    if byte_value in {0, b'\x00'}:
        actual_value = False
    elif byte_value in {1, b'\x01'}:
        actual_value = True
    else:
        with pytest.raises(NonEmptyPaddingBytes):
            decoder(stream)
        return

    decoded_value = decoder(stream)
    assert decoded_value is actual_value


@settings(max_examples=1000)
@given(
    value_byte_size=st.integers(min_value=1, max_value=32),
    stream_bytes=st.binary(min_size=0, max_size=32, average_size=32),
    data_byte_size=st.integers(min_value=0, max_value=32),
)
def test_decode_bytes_xx(value_byte_size, stream_bytes, data_byte_size):
    if value_byte_size > data_byte_size:
        with pytest.raises(ValueError):
            BytesDecoder.as_decoder(
                value_bit_size=value_byte_size * 8,
                data_byte_size=data_byte_size,
            )
        return
    else:
        decoder = BytesDecoder.as_decoder(
            value_bit_size=value_byte_size * 8,
            data_byte_size=data_byte_size,
        )

    stream = BytesIO(stream_bytes)
    actual_value = stream_bytes[:value_byte_size]
    padding_bytes = stream_bytes[value_byte_size:data_byte_size]

    if len(stream_bytes) < data_byte_size:
        with pytest.raises(InsufficientDataBytes):
            decoder(stream)
        return
    elif is_non_empty_non_null_byte_string(padding_bytes):
        with pytest.raises(NonEmptyPaddingBytes):
            decoder(stream)
        return
    else:
        decoded_value = decoder(stream)

    assert decoded_value == actual_value


@settings(max_examples=1000)
@given(
    address_bytes=st.binary(min_size=0, max_size=32, average_size=20),
    padding_size=st.integers(min_value=10, max_value=14),
    data_byte_size=st.integers(min_value=0, max_value=32),
)
def test_decode_address(address_bytes, padding_size, data_byte_size):
    stream_bytes = b'\x00' * padding_size + address_bytes
    if data_byte_size < 20:
        with pytest.raises(ValueError):
            AddressDecoder.as_decoder(
                data_byte_size=data_byte_size,
            )
        return
    else:
        decoder = AddressDecoder.as_decoder(
            data_byte_size=data_byte_size,
        )

    stream = BytesIO(stream_bytes)
    padding_bytes = stream_bytes[:data_byte_size][:-20]

    if len(stream_bytes) < data_byte_size:
        with pytest.raises(InsufficientDataBytes):
            decoder(stream)
        return
    elif is_non_empty_non_null_byte_string(padding_bytes):
        with pytest.raises(NonEmptyPaddingBytes):
            decoder(stream)
        return
    else:
        decoded_value = decoder(stream)

    actual_value = to_normalized_address(stream_bytes[:data_byte_size][-20:])

    assert decoded_value == actual_value


@settings(max_examples=1000)
@given(
    array_size=st.integers(min_value=0, max_value=32),
    array_values=st.lists(st.integers(min_value=0, max_value=TT256M1), min_size=0, max_size=64, average_size=32).map(tuple),
)
def test_decode_array_of_unsigned_integers(array_size, array_values):
    size_bytes = zpad32(int_to_big_endian(array_size))
    values_bytes = b''.join((
        zpad32(int_to_big_endian(v)) for v in array_values
    ))
    stream_bytes = size_bytes + values_bytes

    decoder = DynamicArrayDecoder.as_decoder(
        item_decoder=UnsignedIntegerDecoder.as_decoder(value_bit_size=256),
    )
    stream = BytesIO(stream_bytes)

    if len(array_values) < array_size:
        with pytest.raises(InsufficientDataBytes):
            decoder(stream)
        return

    actual_values = decoder(stream)
    assert actual_values == array_values[:array_size]


@pytest.mark.parametrize(
    'types,data,expected',
    (
        (
            ('address', 'uint256'),
            (
                '0x'
                '000000000000000000000000abf7d8b5c1322b3e553d2fac90ff006c30f1b875'
                '0000000000000000000000000000000000000000000000000000005d21dba000'
            ),
            ('0xabf7d8b5c1322b3e553d2fac90ff006c30f1b875', 400000000000)
        ),
        (
            ('uint256', 'bytes'),
            (
                '0x'
                '0000000000000000000000000000000000000000000000000000000000000000'
                '0000000000000000000000000000000000000000000000000000000000000040'
                '0000000000000000000000000000000000000000000000000000000000000000'
                '0000000000000000000000000000000000000000000000000000000000000000'
            ),
            (0, b''),
        ),
    ),
)
def test_multi_decoder(types, data, expected):
    decoders = tuple((
        get_single_decoder(*process_type(t)) for t in types
    ))
    decoder = MultiDecoder.as_decoder(decoders=decoders)
    stream = BytesIO(decode_hex(data))
    actual = decoder(stream)
    assert actual == expected


@settings(max_examples=1000)
@given(
    high_bit_size=st.integers(min_value=1, max_value=32).map(lambda v: v * 8),
    low_bit_size=st.integers(min_value=1, max_value=32).map(lambda v: v * 8),
    integer_bit_size=st.integers(min_value=1, max_value=32).map(lambda v: v * 8),
    stream_bytes=st.binary(min_size=0, max_size=32, average_size=32),
    data_byte_size=st.integers(min_value=0, max_value=32),
)
def test_decode_unsigned_real(high_bit_size,
                              low_bit_size,
                              integer_bit_size,
                              stream_bytes,
                              data_byte_size):
    if integer_bit_size > data_byte_size * 8:
        with pytest.raises(ValueError):
            UnsignedRealDecoder.as_decoder(
                value_bit_size=integer_bit_size,
                high_bit_size=high_bit_size,
                low_bit_size=low_bit_size,
                data_byte_size=data_byte_size,
            )
        return
    elif high_bit_size + low_bit_size != integer_bit_size:
        with pytest.raises(ValueError):
            UnsignedRealDecoder.as_decoder(
                value_bit_size=integer_bit_size,
                high_bit_size=high_bit_size,
                low_bit_size=low_bit_size,
                data_byte_size=data_byte_size,
            )
        return
    else:
        decoder = UnsignedRealDecoder.as_decoder(
            value_bit_size=integer_bit_size,
            high_bit_size=high_bit_size,
            low_bit_size=low_bit_size,
            data_byte_size=data_byte_size,
        )

    stream = BytesIO(stream_bytes)
    padding_bytes = stream_bytes[:data_byte_size][:data_byte_size - integer_bit_size // 8]

    if len(stream_bytes) < data_byte_size:
        with pytest.raises(InsufficientDataBytes):
            decoder(stream)
        return
    elif is_non_empty_non_null_byte_string(padding_bytes):
        with pytest.raises(NonEmptyPaddingBytes):
            decoder(stream)
        return
    else:
        decoded_value = decoder(stream)

    unsigned_integer_value = big_endian_to_int(stream_bytes[:data_byte_size])
    raw_real_value = decimal.Decimal(unsigned_integer_value) / 2 ** low_bit_size
    actual_value = quantize_value(raw_real_value, low_bit_size)

    assert decoded_value == actual_value


@settings(max_examples=1000)
@given(
    high_bit_size=st.integers(min_value=1, max_value=32).map(lambda v: v * 8),
    low_bit_size=st.integers(min_value=1, max_value=32).map(lambda v: v * 8),
    integer_bit_size=st.integers(min_value=1, max_value=32).map(lambda v: v * 8),
    stream_bytes=st.binary(min_size=0, max_size=32, average_size=32),
    data_byte_size=st.integers(min_value=0, max_value=32),
)
def test_decode_signed_real(high_bit_size,
                            low_bit_size,
                            integer_bit_size,
                            stream_bytes,
                            data_byte_size):
    if integer_bit_size > data_byte_size * 8:
        with pytest.raises(ValueError):
            SignedRealDecoder.as_decoder(
                value_bit_size=integer_bit_size,
                high_bit_size=high_bit_size,
                low_bit_size=low_bit_size,
                data_byte_size=data_byte_size,
            )
        return
    elif high_bit_size + low_bit_size != integer_bit_size:
        with pytest.raises(ValueError):
            SignedRealDecoder.as_decoder(
                value_bit_size=integer_bit_size,
                high_bit_size=high_bit_size,
                low_bit_size=low_bit_size,
                data_byte_size=data_byte_size,
            )
        return
    else:
        decoder = SignedRealDecoder.as_decoder(
            value_bit_size=integer_bit_size,
            high_bit_size=high_bit_size,
            low_bit_size=low_bit_size,
            data_byte_size=data_byte_size,
        )

    stream = BytesIO(stream_bytes)
    padding_bytes = stream_bytes[:data_byte_size][:data_byte_size - integer_bit_size // 8]

    if len(stream_bytes) < data_byte_size:
        with pytest.raises(InsufficientDataBytes):
            decoder(stream)
        return
    elif is_non_empty_non_null_byte_string(padding_bytes):
        with pytest.raises(NonEmptyPaddingBytes):
            decoder(stream)
        return
    else:
        decoded_value = decoder(stream)

    _, upper_bound = compute_signed_integer_bounds(high_bit_size + low_bit_size)

    unsigned_integer_value = big_endian_to_int(stream_bytes[:data_byte_size])
    if unsigned_integer_value >= upper_bound:
        signed_integer_value = unsigned_integer_value - 2 ** (high_bit_size + low_bit_size)
    else:
        signed_integer_value = unsigned_integer_value

    raw_actual_value = decimal.Decimal(signed_integer_value) / 2 ** low_bit_size
    actual_value = quantize_value(raw_actual_value, low_bit_size)

    assert decoded_value == actual_value
