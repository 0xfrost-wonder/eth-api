from __future__ import unicode_literals

from eth_utils import (
    force_text,
    to_tuple,
    to_normalized_address,
)

from eth_abi.exceptions import (
    InsufficientDataBytes,
    NonEmptyPaddingBytes,
)
from eth_abi.utils.numeric import (
    big_endian_to_int,
    ceil32,
)


def get_decoder(processed_types):
    decoders = tuple(
        get_decoder_for_type(base, sub, arrlist) for base, sub, arrlist in processed_types
    )
    return MultiDecoder.as_decoder(decoders=decoders)


def get_decoder_for_type(base, sub, arrlist):
    if arrlist:
        sub_decoder = get_decoder_for_type(base, sub, arrlist[:-1])
        if arrlist[-1]:
            return SizedArrayDecoder.as_decoder(
                array_size=arrlist[-1][0],
                sub_decoder=sub_decoder,
            )
        else:
            return DynamicArrayDecoder.as_decoder(sub_decoder=sub_decoder)
    elif base == 'address':
        return decode_address
    elif base == 'bool':
        return decode_bool
    elif base == 'bytes':
        if sub:
            return BytesDecoder.as_decoder(value_bit_size=int(sub) * 8)
        else:
            return decode_bytes
    elif base == 'int':
        return IntDecoder.as_decoder(value_bit_size=int(sub))
    elif base == 'string':
        return decode_string
    elif base == 'uint':
        return UIntDecoder.as_decoder(value_bit_size=int(sub))
    else:
        raise ValueError(
            "Unsupported type: {0} - must be one of "
            "address/bool/bytesXX/bytes/string/uintXXX/intXXX"
        )


class BaseDecoder(object):
    @classmethod
    def as_decoder(cls, name=None, **kwargs):
        for key in kwargs:
            if not hasattr(cls, key):
                raise AttributeError(
                    "Property {0} not found on Decoder class. "
                    "`Decoder.factory` only accepts keyword arguments which are "
                    "present on the Decoder class".format(key)
                )
        if name is None:
            name = cls.__name__
        sub_cls = type(name, (cls,), kwargs)
        sub_cls.validate()
        instance = sub_cls()
        return instance

    @classmethod
    def validate(cls):
        pass

    def __call__(self, stream):
        return self.decode(stream)


class HeadTailDecoder(BaseDecoder):
    sub_decoder = None

    @classmethod
    def validate(cls):
        super(HeadTailDecoder, cls).validate()
        if cls.sub_decoder is None:
            raise ValueError("No `sub_decoder` set")

    @classmethod
    def decode(cls, stream):
        start_pos = decode_uint_256(stream)
        anchor_pos = stream.tell()
        stream.seek(start_pos)
        value = cls.sub_decoder(stream)
        stream.seek(anchor_pos)
        return value


class MultiDecoder(BaseDecoder):
    decoders = None

    @classmethod
    def validate(cls):
        super(MultiDecoder, cls).validate()
        if cls.decoders is None:
            raise ValueError("No `decoders` set")

    @classmethod
    @to_tuple
    def decode(cls, stream):
        for decoder in cls.decoders:
            if isinstance(decoder, (DynamicArrayDecoder, StringDecoder)):
                yield HeadTailDecoder.as_decoder(sub_decoder=decoder)(stream)
            else:
                yield decoder(stream)


class SingleDecoder(BaseDecoder):
    decoder_fn = None

    @classmethod
    def validate(cls):
        super(SingleDecoder, cls).validate()
        if cls.decoder_fn is None:
            raise ValueError("No `decoder_fn` set")

    @classmethod
    def decode(cls, stream):
        raw_data = cls.read_data_from_stream(stream)
        data = cls.normalize_raw_data(raw_data)
        value = cls.decoder_fn(data)

        return value

    @classmethod
    def read_data_from_stream(cls, stream):
        raise NotImplementedError("Must be implemented by subclasses")

    @classmethod
    def normalize_raw_data(cls, raw_data):
        return raw_data


class BaseArrayDecoder(BaseDecoder):
    sub_decoder = None

    @classmethod
    def validate(cls):
        super(BaseArrayDecoder, cls).validate()
        if cls.sub_decoder is None:
            raise ValueError("No `sub_decoder` set")


class SizedArrayDecoder(BaseArrayDecoder):
    array_size = None

    @classmethod
    @to_tuple
    def decode(cls, stream):
        for _ in range(cls.array_size):
            yield cls.sub_decoder(stream)


class DynamicArrayDecoder(BaseArrayDecoder):
    @classmethod
    @to_tuple
    def decode(cls, stream):
        array_size = decode_uint_256(stream)
        for _ in range(array_size):
            yield cls.sub_decoder(stream)


class FixedByteSizeDecoder(SingleDecoder):
    decoder_fn = None
    value_bit_size = None
    data_byte_size = None
    is_big_endian = None

    @classmethod
    def validate(cls):
        super(FixedByteSizeDecoder, cls).validate()

        if cls.value_bit_size is None:
            raise ValueError("`value_bit_size` may not be None")
        if cls.data_byte_size is None:
            raise ValueError("`data_byte_size` may not be None")
        if cls.decoder_fn is None:
            raise ValueError("`decoder_fn` may not be None")
        if cls.is_big_endian is None:
            raise ValueError("`is_big_endian` may not be None")

        if cls.value_bit_size % 8 != 0:
            raise ValueError(
                "Invalid value bit size: {0}.  Must be a multiple of 8".format(
                    cls.value_bit_size,
                )
            )

        if cls.value_bit_size > cls.data_byte_size * 8:
            raise ValueError("Value byte size exceeds data size")

    @classmethod
    def read_data_from_stream(cls, stream):
        data = stream.read(cls.data_byte_size)

        if len(data) != cls.data_byte_size:
            raise InsufficientDataBytes(
                "Tried to read {0} bytes.  Only got {1} bytes".format(
                    cls.data_byte_size,
                    len(data),
                )
            )

        return data

    @classmethod
    def normalize_raw_data(cls, raw_data):
        value_byte_size = cls._get_value_byte_size()
        padding_size = cls.data_byte_size - value_byte_size

        if cls.is_big_endian:
            padding_bytes = raw_data[:padding_size]
            data = raw_data[padding_size:]
        else:
            data = raw_data[:value_byte_size]
            padding_bytes = raw_data[value_byte_size:]

        if padding_bytes != b'\x00' * padding_size:
            raise NonEmptyPaddingBytes(
                "Padding bytes were not empty: {0}".format(force_text(padding_bytes))
            )

        return data

    @classmethod
    def _get_value_byte_size(cls):
        value_byte_size = cls.value_bit_size // 8
        return value_byte_size


class Fixed32ByteSizeDecoder(FixedByteSizeDecoder):
    data_byte_size = 32


class BooleanDecoder(Fixed32ByteSizeDecoder):
    value_bit_size = 8
    is_big_endian = True

    @classmethod
    def decoder_fn(cls, data):
        if data == b'\x00':
            return False
        elif data == b'\x01':
            return True
        else:
            raise NonEmptyPaddingBytes(
                "Boolean must be either 0x0 or 0x1.  Got: {0}".format(force_text(data))
            )


decode_bool = BooleanDecoder.as_decoder()


class AddressDecoder(Fixed32ByteSizeDecoder):
    value_bit_size = 20 * 8
    is_big_endian = True
    decoder_fn = staticmethod(to_normalized_address)


decode_address = AddressDecoder.as_decoder()


#
# Unsigned Integer Decoders
#
class UIntDecoder(Fixed32ByteSizeDecoder):
    decoder_fn = staticmethod(big_endian_to_int)
    is_big_endian = True


decode_uint_256 = UIntDecoder.as_decoder(value_bit_size=256)


#
# Signed Integer Decoders
#
class IntDecoder(Fixed32ByteSizeDecoder):
    is_big_endian = True

    @classmethod
    def decoder_fn(cls, data):
        value = big_endian_to_int(data)
        if value >= 2 ** (cls.value_bit_size - 1):
            return value - 2 ** cls.value_bit_size
        else:
            return value


#
# Bytes1..32
#
class BytesDecoder(Fixed32ByteSizeDecoder):
    is_big_endian = False

    @classmethod
    def decoder_fn(cls, data):
        return data


#
# String and Bytes
#
class StringDecoder(SingleDecoder):
    @classmethod
    def decoder_fn(cls, data):
        return data

    @classmethod
    def read_data_from_stream(cls, stream):
        data_length = decode_uint_256(stream)
        padded_length = ceil32(data_length)

        data = stream.read(padded_length)

        if len(data) < padded_length:
            raise InsufficientDataBytes(
                "Tried to read {0} bytes.  Only got {1} bytes".format(
                    padded_length,
                    len(data),
                )
            )
        return data[:data_length]


decode_string = decode_bytes = StringDecoder.as_decoder()
