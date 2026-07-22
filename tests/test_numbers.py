import unittest

from aparte.numbers import NBSP, convert


class CardinalTest(unittest.TestCase):
    def test_simple_numbers(self):
        self.assertEqual(convert("il y a vingt-deux personnes"), "il y a 22 personnes")
        self.assertEqual(convert("il en reste dix"), "il en reste 10")
        self.assertEqual(convert("seize ans"), "16 ans")

    def test_the_seventies_and_eighties(self):
        """Les deux seules dizaines qui prennent 10 à 19 comme unités."""
        self.assertEqual(convert("soixante-dix-sept"), "77")
        self.assertEqual(convert("quatre-vingt-dix-sept euros"), "97 euros")
        self.assertEqual(convert("quatre-vingt-onze"), "91")
        self.assertEqual(convert("quatre-vingts ans"), "80 ans")

    def test_the_dictation_may_forget_the_hyphens(self):
        self.assertEqual(convert("quatre vingt dix sept euros"), "97 euros")
        self.assertEqual(convert("vingt deux personnes"), "22 personnes")

    def test_the_belgian_and_swiss_tens(self):
        self.assertEqual(convert("septante-sept"), "77")
        self.assertEqual(convert("nonante-neuf"), "99")
        self.assertEqual(convert("huitante et un"), "81")

    def test_the_et_of_twenty_one(self):
        self.assertEqual(convert("vingt et un chiens"), "21 chiens")
        self.assertEqual(convert("cinquante et une personnes"), "51 personnes")

    def test_hundreds_and_thousands(self):
        self.assertEqual(convert("cent personnes"), "100 personnes")
        self.assertEqual(convert("deux cents"), "200")
        self.assertEqual(convert("mille deux cent cinquante euros"), "1250 euros")
        self.assertEqual(convert("trois cent mille"), f"300{NBSP}000")

    def test_a_year_keeps_its_four_digits_together(self):
        """Le séparateur de milliers commence à cinq chiffres, sinon 2026
        deviendrait « 2 026 »."""
        self.assertEqual(convert("l'an deux mille vingt-six"), "l'an 2026")
        self.assertEqual(convert("trente mille euros"), f"30{NBSP}000 euros")

    def test_millions_keep_their_word(self):
        """« 2 millions » est la forme française, pas « 2000000 »."""
        self.assertEqual(convert("deux millions de fois"), "2 millions de fois")
        self.assertEqual(convert("un million"), "1 million")

    def test_a_capital_at_the_start_of_a_sentence(self):
        self.assertEqual(convert("Vingt-deux personnes sont venues"), "22 personnes sont venues")


class ThresholdTest(unittest.TestCase):
    def test_below_the_threshold_the_number_stays_in_words(self):
        self.assertEqual(convert("j'ai deux chiens"), "j'ai deux chiens")

    def test_the_threshold_is_configurable(self):
        self.assertEqual(convert("il en reste dix", minimum=17), "il en reste dix")
        self.assertEqual(convert("j'ai deux chiens", minimum=1), "j'ai 2 chiens")

    def test_zero_disables_everything(self):
        self.assertEqual(convert("vingt-deux personnes", minimum=0), "vingt-deux personnes")
        self.assertEqual(convert("quatorze heures trente", minimum=0), "quatorze heures trente")


class TrapTest(unittest.TestCase):
    """Les cas où convertir serait une faute."""

    def test_a_lone_un_is_an_article(self):
        self.assertEqual(convert("un chien et une chatte"), "un chien et une chatte")
        self.assertEqual(convert("j'arrive dans une minute", minimum=1), "j'arrive dans une minute")

    def test_des_mille_et_des_cents_is_an_idiom(self):
        self.assertEqual(convert("des mille et des cents"), "des mille et des cents")
        self.assertEqual(convert("les mille de la course"), "les mille de la course")

    def test_a_hyphenated_word_that_is_not_a_number(self):
        self.assertEqual(convert("porte-parole"), "porte-parole")
        self.assertEqual(convert("premier ministre"), "premier ministre")

    def test_punctuation_cuts_a_run_in_two(self):
        self.assertEqual(convert("vingt, deux"), "20, deux")

    def test_an_ill_formed_run_is_left_alone(self):
        self.assertEqual(convert("vingt douze"), "vingt douze")

    def test_a_text_without_numbers_comes_back_identical(self):
        text = "Bonjour, je confirme notre rendez-vous de mardi prochain."
        self.assertEqual(convert(text), text)


class UnitTest(unittest.TestCase):
    """Heures et pourcentages : toujours en chiffres, seuil ou pas."""

    def test_an_hour_with_its_minutes(self):
        self.assertEqual(convert("quatorze heures trente"), f"14{NBSP}h{NBSP}30")
        self.assertEqual(convert("rendez-vous à neuf heures cinq"), f"rendez-vous à 9{NBSP}h{NBSP}05")

    def test_an_hour_on_its_own(self):
        self.assertEqual(convert("il est huit heures"), f"il est 8{NBSP}h")
        self.assertEqual(convert("une heure"), f"1{NBSP}h")

    def test_an_hour_ignores_the_threshold(self):
        self.assertEqual(convert("deux heures", minimum=10), f"2{NBSP}h")

    def test_what_follows_the_hour_is_not_always_minutes(self):
        self.assertEqual(convert("vingt-quatre heures sur vingt-quatre"), f"24{NBSP}h sur 24")

    def test_percentages(self):
        self.assertEqual(convert("vingt pour cent de réduction"), f"20{NBSP}% de réduction")
        self.assertEqual(convert("cent pour cent"), f"100{NBSP}%")
        self.assertEqual(convert("cinq pour cent"), f"5{NBSP}%")

    def test_plain_spaces_when_the_setting_asks_for_them(self):
        self.assertEqual(convert("quatorze heures trente", space=" "), "14 h 30")
        self.assertEqual(convert("vingt pour cent", space=" "), "20 %")


if __name__ == "__main__":
    unittest.main()
