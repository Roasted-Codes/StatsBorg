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


class ActiveVariantNameTests(unittest.TestCase):
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

    def test_uses_variant_cached_before_pgcr_memory_is_cleared(self):
        reader = Halo2StatsReader(
            cast(Any, RelocatedDataClient(0x034DD6E0, "MLG FFA"))
        )

        self.assertEqual(reader.cache_active_variant_name(), "MLG FFA")
        reader.client.variant_bytes = b"\x00" * 0x20

        info = reader.read_variant_info()

        self.assertEqual((info or {}).get("variant"), "MLG FFA")

    def test_clears_cached_variant_after_match(self):
        reader = Halo2StatsReader(
            cast(Any, RelocatedDataClient(0x034DD6E0, "MLG FFA"))
        )
        reader.cache_active_variant_name()

        reader.clear_variant_name_cache()
        reader.client.variant_bytes = b"\x00" * 0x20

        self.assertIsNone(reader.read_variant_info())


if __name__ == "__main__":
    unittest.main()
