"""Offline regression tests for LuatVietnam DocsNewestAjax query encoding."""

from __future__ import annotations

import importlib.util
import sys
import unittest
from pathlib import Path


PROJECT_DIR = Path(__file__).resolve().parents[1]


def load_crawler_module():
    module_name = "luatvietnam_crawler_query_params_test"
    spec = importlib.util.spec_from_file_location(
        module_name,
        PROJECT_DIR / "07_crawl_luatvietnam_list_by_field.py",
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


crawler = load_crawler_module()


def ajax_params(effect_status_ids: list[int]) -> dict:
    return {
        "field_ids": [1, 24, 5],
        "doc_type_ids": [58, 10, 11, 21],
        "effect_status_ids": effect_status_ids,
        "organ_ids": [],
        "show_sapo": 0,
        "order_by": 0,
    }


class BuildQueryParamsTests(unittest.TestCase):
    def test_multiple_effect_status_ids_are_encoded_once_as_comma_separated(self):
        params = crawler.build_query_params(ajax_params([4, 3, 9, 8, 2, 11, 6]), 1, 20)
        effect_status_params = [item for item in params if item[0] == "EffectStatusIds"]

        self.assertEqual([("EffectStatusIds", "4,3,9,8,2,11,6")], effect_status_params)

    def test_two_effect_status_ids_do_not_repeat_the_query_key(self):
        params = crawler.build_query_params(ajax_params([4, 6]), 1, 20)
        effect_status_params = [item for item in params if item[0] == "EffectStatusIds"]

        self.assertEqual([("EffectStatusIds", "4,6")], effect_status_params)

    def test_empty_effect_status_ids_omit_the_query_key(self):
        params = crawler.build_query_params(ajax_params([]), 1, 20)

        self.assertNotIn("EffectStatusIds", [key for key, _value in params])

    def test_field_and_doc_type_ids_remain_single_comma_separated_parameters(self):
        params = crawler.build_query_params(ajax_params([4, 6]), 3, 50)

        self.assertEqual([("FieldIds", "1,24,5")], [item for item in params if item[0] == "FieldIds"])
        self.assertEqual(
            [("DocTypeIds", "58,10,11,21")],
            [item for item in params if item[0] == "DocTypeIds"],
        )


if __name__ == "__main__":
    unittest.main()
