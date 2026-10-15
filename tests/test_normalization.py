import unittest

from normalization import MAX_TITLE_LENGTH, NORMALIZATION_VERSION, normalize_title, validate_options


class NormalizationTests(unittest.TestCase):
    def test_compatibility_forms_case_and_whitespace_share_a_versioned_form(self):
        original = "　ＢＡＢＹＭＥＴＡＬ\tﾌｨｷﾞｭｱ\n 限定　"
        self.assertEqual(normalize_title(original), "babymetal フィギュア 限定")
        self.assertEqual(original, "　ＢＡＢＹＭＥＴＡＬ\tﾌｨｷﾞｭｱ\n 限定　")
        self.assertEqual(NORMALIZATION_VERSION, 1)

    def test_model_numbers_scale_symbols_and_accents_remain_meaningful(self):
        self.assertEqual(normalize_title("Ｂ－０１ １／８ A×B Café"), "b-01 1/8 a×b café")
        self.assertNotEqual(normalize_title("1/8"), normalize_title("18"))
        self.assertNotEqual(normalize_title("A×B"), normalize_title("AB"))
        self.assertNotEqual(normalize_title("café"), normalize_title("cafe"))

    def test_kana_folding_is_optional_and_preserves_voicing_and_sound_marks(self):
        self.assertNotEqual(normalize_title("ガンダム"), normalize_title("がんだむ"))
        self.assertEqual(normalize_title("ｶﾞﾝﾀﾞﾑ フィギュア ケース", {"kana_fold": True}), "がんだむ ふぃぎゅあ けーす")
        self.assertNotEqual(normalize_title("カ", {"kana_fold": True}), normalize_title("ガ", {"kana_fold": True}))
        self.assertEqual(normalize_title("ヷヽヾ", {"kana_fold": True}), "わ\u3099ゝゞ")

    def test_japanese_wave_marks_small_kana_and_hyphens_are_not_guessed_equivalent(self):
        self.assertNotEqual(normalize_title("A〜B"), normalize_title("A～B"))
        self.assertNotEqual(normalize_title("ケースー"), normalize_title("ケース-"))
        self.assertNotEqual(normalize_title("キャ", {"kana_fold": True}), normalize_title("キヤ", {"kana_fold": True}))

    def test_options_can_preserve_case_width_and_spacing(self):
        options = {"nfkc": False, "casefold": False, "collapse_whitespace": False, "kana_fold": False}
        original = " Ａ  Katakana\n"
        self.assertEqual(normalize_title(original, options), original)
        self.assertEqual(normalize_title("Ａ B", {"casefold": False}), "A B")
        self.assertEqual(normalize_title("ﾊﾞ", {"nfkc": False, "kana_fold": True}), "ﾊﾞ")

    def test_unicode_casefold_does_not_guess_transliteration(self):
        self.assertEqual(normalize_title("Straße"), "strasse")
        self.assertNotEqual(normalize_title("ガンダム"), normalize_title("Gundam"))

    def test_invalid_types_unknown_options_and_expansion_are_bounded(self):
        for text, options in ((None, None), (1, None), ("x", {"unknown": True}),
                              ("x", {"nfkc": "true"}), ("x", []),
                              ("x" * (MAX_TITLE_LENGTH + 1), None), ("\ufdfa" * 1000, None)):
            with self.subTest(text=str(text)[:30], options=options), self.assertRaises(ValueError):
                normalize_title(text, options)

    def test_options_and_input_are_not_mutated_and_normalization_is_idempotent(self):
        options = {"kana_fold": True}
        normalized = normalize_title(" ＢＡＢＹＭＥＴＡＬ\nﾌｨｷﾞｭｱ", options)
        self.assertEqual(normalize_title(normalized, options), normalized)
        self.assertEqual(options, {"kana_fold": True})
        defaults = validate_options()
        defaults["nfkc"] = False
        self.assertTrue(validate_options()["nfkc"])


if __name__ == "__main__":
    unittest.main()
