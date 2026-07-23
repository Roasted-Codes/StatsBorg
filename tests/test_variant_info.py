import unittest
from typing import Any, cast

from halo2_stats import Halo2StatsReader, build_snapshot


class RelocatedDataClient:
    """Minimal QMP-like client with a relocatable Halo 2 .data section."""

    DATA_SECTION_VA = 0x46D6E0
    ACTIVE_VARIANT_VA = 0x4BA490

    def __init__(self, data_section_physical: int, variant: str):
        self.data_section_physical = data_section_physical
        self.variant_physical = (
            data_section_physical + self.ACTIVE_VARIANT_VA - self.DATA_SECTION_VA
        )
        self.variant_bytes = variant.encode("utf-16-le").ljust(0x20, b"\x00")

    def translate_va(self, address: int):
        if address == self.DATA_SECTION_VA:
            return self.data_section_physical
        return None

    def _read_physical(self, address: int, length: int):
        if address == self.variant_physical:
            return self.variant_bytes[:length]
        return b"\x00" * length

    def read_memory(self, _address: int, length: int):
        return b"\x00" * length


class StaleLegacyAddressClient(RelocatedDataClient):
    def __init__(self):
        super().__init__(0x034DD6E0, "")

    def _read_physical(self, address: int, length: int):
        if address == 0x035E2490:
            return "STALE VARIANT".encode("utf-16-le").ljust(length, b"\x00")
        return super()._read_physical(address, length)


class ActiveVariantNameTests(unittest.TestCase):
    def test_does_not_trust_instance_specific_physical_fallback(self):
        reader = Halo2StatsReader(cast(Any, StaleLegacyAddressClient()))

        value = reader._read_active_variant_name()

        self.assertEqual(value, "")

    def test_utf16_reader_stops_at_first_nul_terminator(self):
        data = "MLG TS 2007\x00OLD".encode("utf-16-le")

        value = Halo2StatsReader._read_utf16_z_from_bytes(data)

        self.assertEqual(value, "MLG TS 2007")

    def test_reads_variant_relative_to_relocated_data_section(self):
        for physical_base in (0x034DD6E0, 0x035956E0):
            with self.subTest(physical_base=physical_base):
                reader = Halo2StatsReader(
                    cast(Any, RelocatedDataClient(physical_base, "MLG TS 2007"))
                )

                info = reader.read_variant_info()

                self.assertIsNotNone(info)
                self.assertEqual((info or {}).get("variant"), "MLG TS 2007")

                snapshot = build_snapshot(
                    [], variant_name=(info or {}).get("variant")
                )
                self.assertEqual(snapshot.get("variant"), "MLG TS 2007")


if __name__ == "__main__":
    unittest.main()
