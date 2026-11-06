import json
import unittest
from unittest.mock import patch
from urllib.error import HTTPError, URLError

from health_tools.pubmed import MAX_RESPONSE_BYTES, _request, search_pubmed


SEARCH = json.dumps({"esearchresult": {"count": "2", "idlist": ["123", "456"]}}).encode()
ARTICLES = b'''<PubmedArticleSet>
<PubmedArticle><MedlineCitation><PMID>456</PMID><Article>
<ArticleTitle>Record without abstract</ArticleTitle>
</Article></MedlineCitation></PubmedArticle>
<PubmedArticle><MedlineCitation><PMID>123</PMID><Article>
<ArticleTitle>PCOS <i>research</i> example</ArticleTitle>
<Journal><Title>Example Journal</Title><JournalIssue><PubDate>
<Year>2025</Year><Month>Jan</Month></PubDate></JournalIssue></Journal>
<Abstract><AbstractText Label="BACKGROUND">Example background.</AbstractText>
<AbstractText Label="RESULTS">An <b>example</b> result.</AbstractText></Abstract>
<PublicationTypeList><PublicationType>Review</PublicationType></PublicationTypeList>
</Article><CommentsCorrectionsList><CommentsCorrections RefType="RetractionIn">
<PMID>789</PMID></CommentsCorrections></CommentsCorrectionsList>
</MedlineCitation></PubmedArticle></PubmedArticleSet>'''


class PubMedTests(unittest.TestCase):
    @patch("health_tools.pubmed._request", side_effect=[SEARCH, ARTICLES])
    def test_retrieval_provenance_order_and_missing_abstract(self, request):
        result = search_pubmed("PCOS systematic review", 2)
        self.assertEqual(result.status, "ok")
        articles = result.data["articles"]
        self.assertEqual([item["pmid"] for item in articles], ["123", "456"])
        self.assertEqual(articles[0]["title"], "PCOS research example")
        self.assertEqual(articles[0]["abstract"], "BACKGROUND: Example background.\nRESULTS: An example result.")
        self.assertEqual(articles[0]["publication_date"], "2025 Jan")
        self.assertEqual(articles[0]["related_notices"][0]["type"], "RetractionIn")
        self.assertIsNone(articles[1]["abstract"])
        self.assertEqual(articles[1]["evidence_kind"], "citation_only")
        self.assertEqual(result.sources[0].excerpt, articles[0]["abstract"])
        self.assertEqual(result.sources[1].excerpt, "")
        self.assertEqual(result.sources[0].url, "https://pubmed.ncbi.nlm.nih.gov/123/")
        self.assertEqual(request.call_count, 2)
        json.dumps(result.to_dict())

    @patch("health_tools.pubmed._request", return_value=b'{"esearchresult":{"count":"0","idlist":[]}}')
    def test_no_results_does_not_fetch(self, request):
        result = search_pubmed("unmatched topic")
        self.assertEqual(result.status, "insufficient_data")
        self.assertEqual(result.data["returned_count"], 0)
        self.assertEqual(request.call_count, 1)

    @patch("health_tools.pubmed._request")
    def test_invalid_inputs_never_access_network(self, request):
        for kwargs in (
            {"query": ""}, {"query": " "}, {"query": None}, {"query": "x" * 501},
            {"query": "PCOS", "max_results": 0}, {"query": "PCOS", "max_results": 6},
            {"query": "PCOS", "max_results": True}, {"query": "PCOS", "timeout": 0},
            {"query": "PCOS", "timeout": float("nan")},
            {"query": "PCOS", "timeout": float("inf")},
        ):
            with self.subTest(kwargs=kwargs):
                self.assertEqual(search_pubmed(**kwargs).status, "error")
        request.assert_not_called()

    @patch("health_tools.pubmed._request")
    def test_failures_are_sanitized_and_not_retried(self, request):
        for exception, code, retryable in (
            (HTTPError("secret", 429, "secret", {}, None), "rate_limited", True),
            (HTTPError("secret", 503, "secret", {}, None), "http_error", True),
            (HTTPError("secret", 400, "secret", {}, None), "http_error", False),
            (URLError("secret"), "network_error", True),
            (TimeoutError("secret"), "timeout", True),
        ):
            with self.subTest(code=code, exception=exception):
                request.reset_mock()
                request.side_effect = exception
                result = search_pubmed("PCOS")
                self.assertEqual(result.error.code, code)
                self.assertEqual(result.error.retryable, retryable)
                self.assertNotIn("secret", json.dumps(result.to_dict()))
                self.assertEqual(request.call_count, 1)
                if isinstance(exception, HTTPError):
                    self.assertIn(f"HTTP {exception.code}", result.error.message)
                    self.assertIn("search", result.error.message)

    @patch("health_tools.pubmed._request", side_effect=[
        SEARCH, HTTPError("secret", 502, "secret", {}, None)
    ])
    def test_fetch_failure_identifies_stage_without_partial_results(self, request):
        result = search_pubmed("PCOS")
        self.assertEqual(result.error.code, "http_error")
        self.assertIn("abstract retrieval returned HTTP 502", result.error.message)
        self.assertTrue(result.error.retryable)
        self.assertEqual(result.data, {})
        self.assertNotIn("secret", result.error.message)

    @patch("health_tools.pubmed._request")
    def test_invalid_search_payloads(self, request):
        for body in (
            b'not json', b'[]', b'{"error":"bad"}',
            b'{"esearchresult":{"count":"2","idlist":[]}}',
            b'{"esearchresult":{"count":"1","idlist":["wrong"]}}',
            b'{"esearchresult":{"count":"1","idlist":["123","123"]}}',
            b'{"esearchresult":{"count":"0","idlist":["123"]}}',
        ):
            with self.subTest(body=body):
                request.return_value = body
                self.assertEqual(search_pubmed("PCOS").error.code, "invalid_response")

    @patch("health_tools.pubmed._request")
    def test_bad_or_incomplete_fetch_never_returns_partial_success(self, request):
        for body in (b'<broken', b'<ERROR>Unavailable</ERROR>', b'<PubmedArticleSet/>',
                     ARTICLES.replace(b'<PMID>123</PMID>', b'<PMID>999</PMID>')):
            with self.subTest(body=body[:60]):
                request.side_effect = [SEARCH, body]
                result = search_pubmed("PCOS")
                self.assertEqual(result.error.code, "invalid_response")
                self.assertEqual(result.data, {})
                self.assertEqual(result.sources, ())

    @patch.dict("os.environ", {"NCBI_API_KEY": "secret-key", "NCBI_EMAIL": "private@example.org"})
    @patch("health_tools.pubmed._request", side_effect=[SEARCH, ARTICLES])
    def test_credentials_are_sent_but_not_returned(self, request):
        result = search_pubmed("PCOS")
        self.assertEqual(request.call_args_list[0].args[1]["api_key"], "secret-key")
        self.assertNotIn("secret-key", json.dumps(result.to_dict()))
        self.assertNotIn("private@example.org", json.dumps(result.to_dict()))

    @patch("health_tools.pubmed.time.sleep")
    @patch("health_tools.pubmed.urlopen")
    def test_transport_posts_to_ncbi_and_bounds_read(self, open_url, sleep):
        response = open_url.return_value.__enter__.return_value
        response.read.return_value = b'{}'
        self.assertEqual(_request("esearch.fcgi", {"term": "PCOS"}, 5), b'{}')
        req = open_url.call_args.args[0]
        self.assertEqual(req.full_url, "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi")
        self.assertEqual(req.get_method(), "POST")
        self.assertEqual(req.data, b'term=PCOS')
        response.read.assert_called_once_with(MAX_RESPONSE_BYTES + 1)
        response.read.return_value = b'x' * (MAX_RESPONSE_BYTES + 1)
        with self.assertRaises(Exception) as raised:
            _request("esearch.fcgi", {}, 5)
        self.assertEqual(str(raised.exception), "oversized response")


if __name__ == "__main__":
    unittest.main()
