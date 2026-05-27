from cmx_remote_access.docs import _documentation_abstract


def test_documentation_abstract_explains_how_to_read_document_without_description() -> None:
    abstract = _documentation_abstract({"name": "example-api", "version": "1.2.3", "description": ""})

    assert "example-api API package" in abstract
    assert "Release History first" in abstract
    assert "installation sections" in abstract


def test_documentation_abstract_ignores_placeholder_description() -> None:
    abstract = _documentation_abstract(
        {"name": "example-api", "version": "1.2.3", "description": "Add your description here"}
    )

    assert "Add your description here" not in abstract


def test_documentation_abstract_keeps_real_description() -> None:
    abstract = _documentation_abstract(
        {"name": "example-api", "version": "1.2.3", "description": "Controls a test instrument."}
    )

    assert "Controls a test instrument." in abstract
