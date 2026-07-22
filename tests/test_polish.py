import unittest

from aparte.polish import NBSP, HeuristicPolisher, PolishOptions, resolve_language


class HeuristicPolisherTest(unittest.TestCase):
    def test_polish_capitalizes_and_punctuates(self):
        polisher = HeuristicPolisher()
        self.assertEqual(
            polisher.polish("hey sarah thanks i will review it tomorrow"),
            "Hey sarah thanks I will review it tomorrow.",
        )

    def test_polish_removes_basic_fillers(self):
        polisher = HeuristicPolisher()
        self.assertEqual(polisher.polish("um hello euh this is ready"), "Hello this is ready.")

    def test_polish_spoken_punctuation(self):
        polisher = HeuristicPolisher()
        self.assertEqual(
            polisher.polish("hello comma are you there question mark"),
            "Hello, are you there?",
        )

    def test_spoken_punctuation_only_matches_whole_words(self):
        polisher = HeuristicPolisher()
        self.assertEqual(
            polisher.polish("je passe une commande demain"),
            "Je passe une commande demain.",
        )
        self.assertEqual(
            polisher.polish("voici la colonne de gauche"),
            "Voici la colonne de gauche.",
        )

    def test_numbers_stay_inline(self):
        polisher = HeuristicPolisher()
        self.assertEqual(
            polisher.polish("il y a 1 chien et 2 chats"),
            "Il y a 1 chien et 2 chats.",
        )

    def test_casual_style_does_not_force_period(self):
        polisher = HeuristicPolisher()
        self.assertEqual(
            polisher.polish("sounds good", PolishOptions(style="casual")),
            "Sounds good",
        )

    def test_polish_preserves_technical_tokens(self):
        polisher = HeuristicPolisher()
        self.assertEqual(
            polisher.polish("use whisper.cpp with meeting.wav and http://127.0.0.1:11434"),
            "Use whisper.cpp with meeting.wav and http://127.0.0.1:11434.",
        )

    def test_custom_replacements_and_snippets(self):
        polisher = HeuristicPolisher()
        output = polisher.polish(
            "please mention whisper flow slash signature",
            PolishOptions(
                replacements={"whisper flow": "Wispr Flow"},
                snippets={"signature": "Best,\nAlexandre"},
            ),
        )
        self.assertEqual(output, "Please mention Wispr Flow Best,\nAlexandre.")


class LanguageResolutionTest(unittest.TestCase):
    def test_explicit_setting_wins(self):
        self.assertEqual(resolve_language("fr", "this is english"), "fr")
        self.assertEqual(resolve_language("en", "ceci est du français"), "en")

    def test_unsupported_language_falls_back_to_english_rules(self):
        self.assertEqual(resolve_language("es", "hola que tal"), "en")

    def test_detects_french_from_accents_or_function_words(self):
        self.assertEqual(resolve_language(None, "il a déjà mangé"), "fr")
        self.assertEqual(resolve_language(None, "je pense que tu as raison"), "fr")
        self.assertEqual(resolve_language(None, "please send me the report"), "en")


class FrenchTypographyTest(unittest.TestCase):
    """French puts a space before double punctuation; English does not."""

    def setUp(self):
        self.polisher = HeuristicPolisher()

    def polish_fr(self, text, **kwargs):
        return self.polisher.polish(text, PolishOptions(language="fr", **kwargs))

    def test_nonbreaking_space_before_double_punctuation(self):
        self.assertEqual(self.polish_fr("tu viens question mark"), f"Tu viens{NBSP}?")
        self.assertEqual(self.polish_fr("attention deux points c'est prêt"), f"Attention{NBSP}: c’est prêt.")

    def test_no_space_before_comma_or_period(self):
        self.assertEqual(self.polish_fr("oui virgule bien sûr"), "Oui, bien sûr.")

    def test_urls_and_times_keep_their_colon(self):
        self.assertEqual(
            self.polish_fr("va sur https://exemple.com à 14:30"),
            "Va sur https://exemple.com à 14:30.",
        )

    def test_straight_quotes_become_french_quotes(self):
        self.assertEqual(
            self.polish_fr('il a dit "bonjour" ce matin'),
            f"Il a dit «{NBSP}bonjour{NBSP}» ce matin.",
        )

    def test_unpaired_quote_is_left_alone(self):
        self.assertIn('"', self.polish_fr('il a dit "bonjour ce matin'))

    def test_apostrophes_become_typographic(self):
        self.assertEqual(self.polish_fr("c'est l'ami de Paul"), "C’est l’ami de Paul.")

    def test_standalone_i_is_not_upper_cased(self):
        self.assertEqual(self.polish_fr("il reste un i dans le mot"), "Il reste un i dans le mot.")

    def test_setting_swaps_nonbreaking_for_a_plain_space(self):
        out = self.polish_fr("tu viens question mark", nonbreaking_spaces=False)
        self.assertEqual(out, "Tu viens ?")
        self.assertNotIn(NBSP, out)

    def test_english_keeps_tight_punctuation(self):
        self.assertEqual(
            self.polisher.polish("are you there question mark", PolishOptions(language="en")),
            "Are you there?",
        )


class ShortTextTest(unittest.TestCase):
    """A few words are a search field or a chat reply, not a sentence."""

    def setUp(self):
        self.polisher = HeuristicPolisher()

    def test_a_short_dictation_keeps_its_lowercase_and_gets_no_period(self):
        options = PolishOptions(language="fr", short_text_words=5)
        self.assertEqual(self.polisher.polish("billets de train", options), "billets de train")

    def test_the_threshold_is_exclusive(self):
        """"Moins de 3 mots" means two, not three."""
        options = PolishOptions(language="fr", short_text_words=3)
        self.assertEqual(self.polisher.polish("billets de train", options), "Billets de train.")
        self.assertEqual(self.polisher.polish("billets train", options), "billets train")

    def test_the_setting_is_off_by_default(self):
        self.assertEqual(self.polisher.polish("billets", PolishOptions(language="fr")), "Billets.")

    def test_replacements_still_apply_to_a_short_dictation(self):
        options = PolishOptions(
            language="fr", short_text_words=5, replacements={"pipe wire": "PipeWire"}
        )
        self.assertEqual(self.polisher.polish("pipe wire", options), "PipeWire")


class NumbersInThePipelineTest(unittest.TestCase):
    def setUp(self):
        self.polisher = HeuristicPolisher()

    def test_a_dictated_number_comes_out_in_digits(self):
        self.assertEqual(
            self.polisher.polish("il y a vingt-deux personnes", PolishOptions(language="fr")),
            "Il y a 22 personnes.",
        )

    def test_an_hour_survives_the_punctuation_pass(self):
        """Les nombres passent avant l'espacement : la règle qui protège
        « 14:30 » a besoin de voir les chiffres."""
        self.assertEqual(
            self.polisher.polish(
                "rendez-vous à quatorze heures trente virgule c'est noté",
                PolishOptions(language="fr"),
            ),
            f"Rendez-vous à 14{NBSP}h{NBSP}30, c’est noté.",
        )

    def test_english_is_left_alone(self):
        self.assertEqual(
            self.polisher.polish("twenty two people", PolishOptions(language="en")),
            "Twenty two people.",
        )


class TrailingSpaceTest(unittest.TestCase):
    def setUp(self):
        self.polisher = HeuristicPolisher()

    def test_the_dictation_ends_with_a_space_when_asked(self):
        options = PolishOptions(language="fr", trailing_space=True)
        self.assertEqual(self.polisher.polish("bonjour à tous", options), "Bonjour à tous. ")

    def test_nothing_is_added_by_default(self):
        self.assertEqual(self.polisher.polish("bonjour à tous", PolishOptions(language="fr")), "Bonjour à tous.")

    def test_an_empty_dictation_stays_empty(self):
        options = PolishOptions(language="fr", trailing_space=True)
        self.assertEqual(self.polisher.polish("   ", options), "")


class FillerLanguageTest(unittest.TestCase):
    def test_ambiguous_words_are_only_stripped_for_their_own_language(self):
        polisher = HeuristicPolisher()
        # "genre" is a real French noun, so a French dictation keeps it unless
        # cleanup is set to high; English "like" never touches French text.
        self.assertEqual(
            polisher.polish("c'est un genre de rapport", PolishOptions(language="fr")),
            "C’est un genre de rapport.",
        )
        self.assertEqual(
            polisher.polish(
                "c'est genre un rapport",
                PolishOptions(language="fr", cleanup_level="high"),
            ),
            "C’est un rapport.",
        )


if __name__ == "__main__":
    unittest.main()
