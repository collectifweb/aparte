import unittest

from murmur.polish import HeuristicPolisher, PolishOptions


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


if __name__ == "__main__":
    unittest.main()
