import unittest

from backend.app.research import _rank_sources, _source_relevance


class ResearchRankingTests(unittest.TestCase):
    def test_relevance_normalizes_accents_and_ignores_stopwords(self):
        relevance, matched = _source_relevance(
            "Tecnologia sustentável em casa",
            "Tecnologia sustentavel transforma a casa",
            "Solucoes para energia limpa",
        )
        self.assertGreaterEqual(relevance, 0.5)
        self.assertEqual(matched, ["casa", "sustentavel", "tecnologia"])

    def test_rank_sources_deduplicates_and_prefers_topic_match(self):
        ranked = _rank_sources(
            "horta urbana em apartamento",
            [
                {"title": "Horta urbana em apartamento: guia prático", "url": "https://example.com/guide", "snippet": "Como plantar em casa", "published_at": "Mon, 15 Sep 2026 10:00:00 GMT"},
                {"title": "Notícias gerais do mercado", "url": "https://example.com/noise", "snippet": "Atualizações variadas", "published_at": "Mon, 15 Sep 2026 10:00:00 GMT"},
                {"title": "Horta urbana em apartamento: guia prático", "url": "https://example.com/guide", "snippet": "versão duplicada", "published_at": "Mon, 15 Sep 2026 10:00:00 GMT"},
            ],
        )
        self.assertEqual(len(ranked), 1)
        self.assertEqual(ranked[0]["url"], "https://example.com/guide")
        self.assertIn("horta", ranked[0]["matched_terms"])

    def test_generic_word_does_not_ground_an_unrelated_subject(self):
        relevance, matched = _source_relevance(
            "História do Japão: da formação até a era moderna",
            "A história da inteligência artificial",
            "Uma retrospectiva sobre tecnologia e inovação.",
        )
        self.assertEqual(relevance, 0.0)
        self.assertEqual(matched, [])

    def test_rank_sources_can_return_no_related_sources(self):
        ranked = _rank_sources(
            "História do Japão",
            [{"title": "A história da inteligência artificial", "url": "https://example.com/noise", "snippet": "Tecnologia", "published_at": ""}],
        )
        self.assertEqual(ranked, [])


if __name__ == "__main__":
    unittest.main()
