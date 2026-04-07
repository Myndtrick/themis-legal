from app.services.source_url import extract_ver_id, extract_celex, probe_url


class TestExtractVerId:
    def test_basic_detalii_document(self):
        assert extract_ver_id("https://legislatie.just.ro/Public/DetaliiDocument/109884") == "109884"

    def test_detalii_document_afis(self):
        assert extract_ver_id("https://legislatie.just.ro/Public/DetaliiDocumentAfis/132456") == "132456"

    def test_with_query_params(self):
        assert extract_ver_id("https://legislatie.just.ro/Public/DetaliiDocument/109884?foo=bar") == "109884"

    def test_wrong_host(self):
        assert extract_ver_id("https://eur-lex.europa.eu/legal-content/RO/TXT/?uri=CELEX:32016R0679") is None

    def test_malformed(self):
        assert extract_ver_id("not a url") is None

    def test_empty(self):
        assert extract_ver_id("") is None


class TestExtractCelex:
    def test_legal_content_basic(self):
        assert extract_celex("https://eur-lex.europa.eu/legal-content/RO/TXT/?uri=CELEX:32016R0679") == "32016R0679"

    def test_legal_content_url_encoded_colon(self):
        assert extract_celex("https://eur-lex.europa.eu/legal-content/EN/TXT/?uri=CELEX%3A32016R0679") == "32016R0679"

    def test_legal_content_extra_params(self):
        assert extract_celex("https://eur-lex.europa.eu/legal-content/EN/TXT/?uri=CELEX:32016R0679&qid=12345") == "32016R0679"

    def test_legal_content_pdf_variant(self):
        assert extract_celex("https://eur-lex.europa.eu/legal-content/EN/TXT/PDF/?uri=CELEX:32016R0679") == "32016R0679"

    def test_eli_regulation(self):
        # /eli/reg/2016/679/oj → 32016R0679
        assert extract_celex("https://eur-lex.europa.eu/eli/reg/2016/679/oj") == "32016R0679"

    def test_eli_directive(self):
        # /eli/dir/2011/83/oj → 32011L0083
        assert extract_celex("https://eur-lex.europa.eu/eli/dir/2011/83/oj") == "32011L0083"

    def test_eli_decision(self):
        # /eli/dec/2020/1234/oj → 32020D1234
        assert extract_celex("https://eur-lex.europa.eu/eli/dec/2020/1234/oj") == "32020D1234"

    def test_wrong_host(self):
        assert extract_celex("https://legislatie.just.ro/Public/DetaliiDocument/109884") is None

    def test_malformed(self):
        assert extract_celex("not a url") is None


class TestProbeUrl:
    def test_ro_url(self):
        result = probe_url("https://legislatie.just.ro/Public/DetaliiDocument/109884")
        assert result["kind"] == "ro"
        assert result["identifier"] == "109884"
        assert result["error"] is None

    def test_eu_url(self):
        result = probe_url("https://eur-lex.europa.eu/legal-content/RO/TXT/?uri=CELEX:32016R0679")
        assert result["kind"] == "eu"
        assert result["identifier"] == "32016R0679"
        assert result["error"] is None

    def test_unknown_host(self):
        result = probe_url("https://example.com/foo")
        assert result["kind"] == "unknown"
        assert result["identifier"] is None
        assert result["error"] == "URL host not recognized"

    def test_known_host_no_identifier(self):
        result = probe_url("https://eur-lex.europa.eu/homepage.html")
        assert result["kind"] == "eu"
        assert result["identifier"] is None
        assert result["error"] == "Could not extract identifier"
